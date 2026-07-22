"""Hindcast backtest harness for the forecast methodology.

Truncates real wells' production history at T months, runs the truncated series
through the REAL engine path (classify_well → analog type curve → build_curve →
project), and scores the forecast against the held-out actuals. Methodology
variants change ONLY how the cohort/subject b-factor is sourced; everything else
(analog set, fitting, routing, projection) is held identical so comparisons are
apples-to-apples.

Variants:
    production  — the engine as shipped: gated+clamped cohort b
                  (orchestrator._build_type_curve_with_stats) and own-b fits for
                  ≥30-post-peak HISTORY subjects (routing.build_curve).
    legacy      — the pre-2026-07 engine, kept as the permanent regression
                  comparator: cohort b = ungated median of free-b fits on ALL
                  analogs; HISTORY subjects always borrow the cohort b.
    late_window — shelved alternative (b fit on mature analogs' late-life
                  segments, on top of the production type curve's qi/di).
                  Lost to `production` on the 2026-07-21 run — worst MAE,
                  erratic at T=36 — retained for future re-testing.

Point-in-time discipline: for a subject truncated at cutoff month D, analogs
only ever contribute production with prod_date ≤ D — no variant sees data that
didn't exist at the forecast date. Subjects are sampled from contiguous
(gap-free) series only, so the engine's contiguous-months assumption is
satisfied by construction and doesn't confound the b comparison.

Run:  .venv/bin/python -m server.valuation.backtest --per-formation 75
"""
import argparse
import hashlib
import json
import math
from datetime import date, datetime

import numpy as np
from dateutil.relativedelta import relativedelta

from server.valuation.forecast import (
    fit_curve, fit_curve_best_b, override_b, percentile_curves, project,
)
from server.valuation.orchestrator import (
    _build_type_curve_with_stats, _B_CLAMP, CohortError,
)
from server.valuation.routing import (
    _MIN_POST_PEAK_HISTORY, _SERVER_DEFAULT_B, _OWN_B_MIN_POST_PEAK, B_GRID,
    AnalogRequired, WellState, build_curve, classify_well,
)
from server.valuation.types import DeclineCurve, Forecast
from utils.db import query

# ── knobs (documented in the run record so results are self-describing) ──────
DEFAULT_FORMATIONS = ["LOWER EAGLE FORD", "MIDDLE BAKKEN", "WOLFCAMP A", "NIOBRARA B"]
MIN_HISTORY_MONTHS = 48        # subject eligibility: total reported months
HOLDOUT_MONTHS = 24            # score horizon past the truncation point
MAX_ANALOGS = 15               # cohort cap, nearest-first
CANDIDATE_POOL = 60            # distance-ordered candidates fetched per subject
MIN_ANALOG_MONTHS = 12         # analog must have this much history at cutoff
LATERAL_BAND = 0.30            # analog lateral within ±30% of subject (when both known)
LATE_WINDOW_START = 18         # late-life segment starts this many months post-peak
LATE_WINDOW_MIN_SEG = 12       # minimum months in the late segment
PV_ANNUAL_RATE = 0.10          # discounted-volume metric rate

VARIANTS = ("production", "legacy", "late_window")


# ── small date/series helpers ────────────────────────────────────────────────

def _d(iso: str) -> date:
    return date.fromisoformat(iso[:10])


def _post_peak_months(q: np.ndarray) -> int:
    if len(q) == 0:
        return 0
    return len(q) - 1 - int(np.argmax(q))


def _truncate_at(prod: dict, cutoff: str) -> dict:
    """Point-in-time view of a production entry: months ≤ cutoff (ISO date str)."""
    months = prod["months"]
    n = sum(1 for m in months if m[:10] <= cutoff[:10])
    return {
        "months": months[:n],
        "oil_bbl": prod["oil_bbl"][:n],
        "gas_mcf": prod["gas_mcf"][:n],
    }


# ── eligibility + sampling ───────────────────────────────────────────────────

def load_eligible(formations: list[str], min_months: int, cache_path: str | None,
                  refresh: bool = False) -> list[dict]:
    """Producing wells in the given formations with ≥min_months of contiguous
    history whose loaded series starts at the well's actual first production
    (partial-coverage series would silently shift the truncation window — seen
    on old MT Bakken wells). One heavy query (~minutes over the full production
    table), cached to disk keyed by (formations, min_months)."""
    key = hashlib.md5(f"v2|{sorted(formations)}|{min_months}".encode()).hexdigest()[:12]
    if cache_path and not refresh:
        try:
            with open(cache_path) as f:
                cached = json.load(f)
            if cached.get("key") == key:
                return cached["wells"]
        except (OSError, json.JSONDecodeError, KeyError):
            pass
    rows = query(
        """
        WITH p AS (
            SELECT well_api, COUNT(*) AS n_months,
                   MIN(prod_date) AS first_prod, MAX(prod_date) AS last_prod,
                   (EXTRACT(YEAR FROM MAX(prod_date))*12 + EXTRACT(MONTH FROM MAX(prod_date)))
                 - (EXTRACT(YEAR FROM MIN(prod_date))*12 + EXTRACT(MONTH FROM MIN(prod_date))) + 1 AS span
            FROM public.production
            GROUP BY well_api
        )
        SELECT w.well_api, w.formation, w.basin, w.county,
               w.lateral_length_ft, p.n_months::int AS n_months
        FROM public.wells w
        JOIN p ON p.well_api = w.well_api
        WHERE w.well_status = 'PRODUCING'
          AND w.formation = ANY(%s)
          AND p.n_months >= %s
          AND p.n_months = p.span
          AND w.first_prod_date IS NOT NULL
          AND p.first_prod <= w.first_prod_date + INTERVAL '3 months'
        """,
        params=[formations, min_months],
        statement_timeout_ms=600_000,
    )
    if cache_path:
        with open(cache_path, "w") as f:
            json.dump({"key": key, "built_at": datetime.now().isoformat(), "wells": rows},
                      f, default=str)
    return rows


def sample_subjects(eligible: list[dict], per_formation: int) -> list[dict]:
    """Deterministic pseudo-random spread: md5 order within each formation."""
    by_formation: dict[str, list[dict]] = {}
    for w in eligible:
        by_formation.setdefault(w["formation"], []).append(w)
    out: list[dict] = []
    for formation in sorted(by_formation):
        rows = sorted(by_formation[formation],
                      key=lambda w: hashlib.md5(w["well_api"].encode()).hexdigest())
        out.extend(rows[:per_formation])
    return out


# ── analog candidates (deterministic picker) ─────────────────────────────────

def candidate_analogs(subject: dict) -> list[dict]:
    """Distance-ordered candidate analogs: same formation+basin producers.
    Per-truncation filtering (point-in-time history floor, lateral band, cap)
    happens later in ``pick_analogs`` — this is one query per subject."""
    return query(
        """
        SELECT w.well_api, w.lateral_length_ft, w.first_prod_date,
               ST_Distance(w.geom, s.geom) AS dist
        FROM public.wells w
        JOIN (SELECT geom FROM public.wells WHERE well_api = %s) s ON TRUE
        WHERE w.formation = %s AND w.basin = %s
          AND w.well_api != %s
          AND w.well_status = 'PRODUCING'
          AND w.first_prod_date IS NOT NULL
        ORDER BY (w.geom IS NULL), dist NULLS LAST, w.well_api
        LIMIT %s
        """,
        params=[subject["well_api"], subject["formation"], subject["basin"],
                subject["well_api"], CANDIDATE_POOL],
        statement_timeout_ms=60_000,
    )


def pick_analogs(candidates: list[dict], analog_prod: dict, subject_lateral,
                 cutoff: str) -> dict[str, dict]:
    """Nearest analogs with ≥MIN_ANALOG_MONTHS of pre-cutoff history and a
    comparable lateral (±LATERAL_BAND when both laterals are known). Returns
    {api: truncated_prod}, capped at MAX_ANALOGS, insertion-ordered by distance."""
    picked: dict[str, dict] = {}
    for c in candidates:
        if len(picked) >= MAX_ANALOGS:
            break
        api = c["well_api"]
        lat = c.get("lateral_length_ft")
        if subject_lateral and lat:
            if abs(float(lat) - float(subject_lateral)) > LATERAL_BAND * float(subject_lateral):
                continue
        full = analog_prod.get(api, {"months": [], "oil_bbl": [], "gas_mcf": []})
        # Full-life coverage guard: a series that starts long after the well's
        # first_prod_date is a mid-life fragment — its "peak" is a mid-life rate
        # and its fit would pollute the cohort qi. Skip it.
        first_prod = c.get("first_prod_date")
        if not full["months"] or (
            first_prod is not None
            and _d(full["months"][0]) > _d(str(first_prod)) + relativedelta(months=3)
        ):
            continue
        trunc = _truncate_at(full, cutoff)
        if len(trunc["months"]) < MIN_ANALOG_MONTHS:
            continue
        picked[api] = trunc
    return picked


# ── variant type curves ──────────────────────────────────────────────────────

def _free_fit(q: np.ndarray, stream: str) -> DeclineCurve | None:
    try:
        return fit_curve(np.arange(len(q), dtype=float), q, stream=stream, b_fixed=None)
    except ValueError:
        return None


def _late_segment_b(q: np.ndarray, stream: str) -> float | None:
    """b fit on the late-life window only: post-peak months ≥ LATE_WINDOW_START.
    The segment's own argmax is its first point, so the fit runs from t=0."""
    peak_idx = int(np.argmax(q))
    seg = q[peak_idx + LATE_WINDOW_START:]
    if len(seg) < LATE_WINDOW_MIN_SEG + 1 or float(seg.sum()) <= 0.0:
        return None
    try:
        best = fit_curve_best_b(np.arange(len(seg), dtype=float), seg, stream=stream,
                                b_grid=B_GRID, min_post_peak_months=LATE_WINDOW_MIN_SEG)
    except ValueError:
        return None
    return best.b


def _legacy_type_curve(analogs: dict[str, dict], stream: str) -> tuple[DeclineCurve, int] | None:
    """The pre-2026-07 cohort curve: parameter-wise median (b included, ungated,
    unclamped) of free-b fits on every analog that fits."""
    col = "oil_bbl" if stream == "oil" else "gas_mcf"
    curves = [c for prod in analogs.values()
              if (c := _free_fit(np.asarray(prod[col], dtype=float), stream)) is not None]
    if not curves:
        return None
    return percentile_curves(curves, pct=0.5), len(curves)


def build_type_curves(analogs: dict[str, dict], variant: str) -> dict | None:
    """Per-variant oil+gas type curves from the truncated analog cohort.
    Returns {"oil": tc, "gas": tc, "b_meta": {...}} or None when no analog fits.
    ``production`` is the shipped engine function verbatim; the others re-source
    ONLY the b on the same cohort."""
    if not analogs:
        return None
    if variant == "production":
        try:
            oil_tc, n_fit, n_skipped, b_meta = _build_type_curve_with_stats(analogs, "oil")
            gas_tc, _, _, _ = _build_type_curve_with_stats(analogs, "gas")
        except CohortError:
            return None
        return {"oil": oil_tc, "gas": gas_tc,
                "b_meta": {**b_meta, "n_fit_oil": n_fit, "n_skipped_oil": n_skipped}}

    if variant == "legacy":
        oil = _legacy_type_curve(analogs, "oil")
        gas = _legacy_type_curve(analogs, "gas")
        if oil is None or gas is None:
            return None
        return {"oil": oil[0], "gas": gas[0],
                "b_meta": {"b": round(oil[0].b, 4), "source": f"legacy_ungated_median(n={oil[1]})"}}

    # late_window: production qi/di (gating leaves qi/di untouched), late-life b.
    try:
        oil_tc, _, _, _ = _build_type_curve_with_stats(analogs, "oil")
        gas_tc, _, _, _ = _build_type_curve_with_stats(analogs, "gas")
    except CohortError:
        return None
    out = {}
    for stream, tc in (("oil", oil_tc), ("gas", gas_tc)):
        col = "oil_bbl" if stream == "oil" else "gas_mcf"
        bs = [b for prod in analogs.values()
              if (b := _late_segment_b(np.asarray(prod[col], dtype=float), stream)) is not None]
        if bs:
            b = min(max(float(np.median(bs)), _B_CLAMP[0]), _B_CLAMP[1])
            source = f"late_window_median(n={len(bs)})"
        else:
            b = _SERVER_DEFAULT_B
            source = "late_window_fallback_default"
        out[stream] = override_b(tc, b, note=f"b:{source}")
        if stream == "oil":
            meta = {"b": round(b, 4), "source": source}
    return {"oil": out["oil"], "gas": out["gas"], "b_meta": meta}


# ── per-subject forecast + scoring ───────────────────────────────────────────

def forecast_oil_curve(months: list[str], q_oil: np.ndarray, q_gas: np.ndarray,
                       tcs: dict | None, variant: str):
    """Subject oil curve. ``production``/``late_window`` go through the real
    routing path (own-b included). ``legacy`` reproduces the pre-2026-07 HISTORY
    branch: always borrow the cohort b (or 0.8), never fit your own."""
    oil_tc = tcs["oil"] if tcs else None
    if variant == "legacy" and classify_well(months, q_oil) == WellState.HISTORY:
        peak_idx = int(np.argmax(q_oil))
        zero_stream = (float(q_oil.sum()) <= 0.0
                       or (peak_idx < len(q_oil) - 1 and float(q_oil[peak_idx + 1:].sum()) <= 0.0))
        if not zero_stream:
            b = oil_tc.b if oil_tc is not None else _SERVER_DEFAULT_B
            curve = fit_curve(np.arange(len(q_oil), dtype=float), q_oil, stream="oil",
                              b_fixed=b, min_post_peak_months=_MIN_POST_PEAK_HISTORY)
            return curve, WellState.HISTORY, "history"
    return build_curve(months, q_oil, analog=oil_tc, stream="oil")


def score_forecast(curve: DeclineCurve, months_trunc: list[str],
                   oil_full: list[float], t_months: int, holdout: int) -> dict | None:
    """Project past the cutoff exactly as run_valuation places producing wells
    (anchor = last truncated month, peak = truncated argmax) and score the next
    ``holdout`` months against actuals. Series are contiguous by sampling."""
    q_trunc = np.asarray(oil_full[:t_months], dtype=float)
    anchor = _d(months_trunc[-1])
    peak = _d(months_trunc[int(np.argmax(q_trunc))])
    fc = Forecast(curve=curve, peak_date=peak, start_date=anchor, provenance=curve.provenance)
    _, rates = project(fc, horizon_months=holdout + 1)
    fcast = np.asarray(rates[1:], dtype=float)          # rates[0] is the anchor month itself
    actual = np.asarray(oil_full[t_months:t_months + holdout], dtype=float)
    n = min(len(fcast), len(actual))
    if n < 12:
        return None
    fcast, actual = fcast[:n], actual[:n]

    def _cum_err(k: int) -> float | None:
        if n < k or actual[:k].sum() <= 0:
            return None
        return float(fcast[:k].sum() / actual[:k].sum() - 1.0)

    disc = (1.0 + PV_ANNUAL_RATE) ** (-(np.arange(1, n + 1) / 12.0))
    pv_a = float((actual * disc).sum())
    pv_f = float((fcast * disc).sum())
    return {
        "cum12_err": _cum_err(12),
        "cum24_err": _cum_err(24),
        "pv10_err": (pv_f / pv_a - 1.0) if pv_a > 0 else None,
        "holdout_n": n,
    }


# ── the run loop ─────────────────────────────────────────────────────────────

def run_backtest(*, formations: list[str], per_formation: int, truncations: list[int],
                 variants: list[str], holdout: int, min_history: int,
                 cache_path: str | None, refresh_cache: bool = False,
                 progress=print) -> dict:
    from server.valuation.wells import bulk_load_production

    eligible = load_eligible(formations, min_history, cache_path, refresh=refresh_cache)
    subjects = sample_subjects(eligible, per_formation)
    progress(f"eligible={len(eligible)} sampled={len(subjects)} "
             f"formations={sorted({s['formation'] for s in subjects})}")

    rows: list[dict] = []
    skips: dict[str, int] = {}

    def _skip(reason: str):
        skips[reason] = skips.get(reason, 0) + 1

    for i, subj in enumerate(subjects):
        api = subj["well_api"]
        prod = bulk_load_production([api])[api]
        oil_full = [float(v) for v in prod["oil_bbl"]]
        candidates = candidate_analogs(subj)
        cand_apis = [c["well_api"] for c in candidates]
        cand_prod = bulk_load_production(cand_apis) if cand_apis else {}

        for t_m in truncations:
            if len(prod["months"]) < t_m + 12:      # need ≥12 holdout months
                _skip("short_holdout")
                continue
            months_t = prod["months"][:t_m]
            q_oil = np.asarray(oil_full[:t_m], dtype=float)
            q_gas = np.asarray(prod["gas_mcf"][:t_m], dtype=float)
            if q_oil.sum() <= 0:
                _skip("zero_oil_at_cutoff")
                continue
            if sum(oil_full[t_m:t_m + 12]) <= 0:
                _skip("zero_holdout")
                continue
            cutoff = months_t[-1]
            analogs = pick_analogs(candidates, cand_prod, subj.get("lateral_length_ft"), cutoff)

            state_label = classify_well(months_t, q_oil).value
            for variant in variants:
                tcs = build_type_curves(analogs, variant)
                try:
                    curve, _state, strategy = forecast_oil_curve(
                        months_t, q_oil, q_gas, tcs, variant)
                except AnalogRequired:
                    _skip(f"no_analogs_{variant}")
                    continue
                if strategy == "zero_stream":
                    _skip("zero_stream_curve")
                    continue
                scores = score_forecast(curve, months_t, oil_full, t_m, holdout)
                if scores is None:
                    _skip("unscorable")
                    continue
                rows.append({
                    "api": api, "formation": subj["formation"], "basin": subj["basin"],
                    "t_months": t_m, "cutoff": cutoff[:10], "variant": variant,
                    "classification": state_label, "strategy": strategy,
                    "n_analogs": len(analogs),
                    "b_used": round(curve.b, 4),
                    "b_meta": (tcs or {}).get("b_meta"),
                    **scores,
                })
        if (i + 1) % 25 == 0:
            progress(f"  {i + 1}/{len(subjects)} subjects done, {len(rows)} rows")

    return {
        "config": {
            "formations": formations, "per_formation": per_formation,
            "truncations": truncations, "variants": variants, "holdout": holdout,
            "min_history": min_history, "max_analogs": MAX_ANALOGS,
            "min_analog_months": MIN_ANALOG_MONTHS, "lateral_band": LATERAL_BAND,
            "late_window_start": LATE_WINDOW_START,
            "engine": {                     # shipped-engine constants, for the record
                "gated_min_post_peak": 24, "b_clamp": list(_B_CLAMP),
                "own_b_min_post_peak": _OWN_B_MIN_POST_PEAK,
                "b_grid": [B_GRID[0], B_GRID[-1]],
            },
            "pv_rate": PV_ANNUAL_RATE, "ran_at": datetime.now().isoformat(),
        },
        "skips": skips,
        "rows": rows,
    }


# ── summary ──────────────────────────────────────────────────────────────────

def _agg(vals: list[float]) -> dict | None:
    v = [x for x in vals if x is not None and math.isfinite(x)]
    if not v:
        return None
    a = np.asarray(v)
    return {
        "n": len(v),
        "median": round(float(np.median(a)), 4),
        "mae": round(float(np.mean(np.abs(a))), 4),
        "p10": round(float(np.percentile(a, 10)), 4),
        "p90": round(float(np.percentile(a, 90)), 4),
    }


def summarize(rows: list[dict], by: tuple[str, ...] = ("t_months", "variant")) -> dict:
    """Nested {group_key: {metric: agg}} for the three headline metrics.
    ``median`` of the signed error is the bias read; ``mae`` the accuracy read."""
    groups: dict[str, list[dict]] = {}
    for r in rows:
        key = " | ".join(str(r[k]) for k in by)
        groups.setdefault(key, []).append(r)
    return {
        key: {
            metric: _agg([r[metric] for r in rs])
            for metric in ("cum12_err", "cum24_err", "pv10_err")
        }
        for key, rs in sorted(groups.items())
    }


def format_table(summary: dict, title: str) -> str:
    lines = [title, f"{'group':<28} {'n':>5} {'cum12 med':>10} {'cum12 mae':>10} "
                    f"{'cum24 med':>10} {'pv10 med':>10}"]
    for key, metrics in summary.items():
        c12, c24, pv = metrics["cum12_err"], metrics["cum24_err"], metrics["pv10_err"]
        lines.append(
            f"{key:<28} {(c12 or {}).get('n', 0):>5} "
            f"{_pct((c12 or {}).get('median')):>10} {_pct((c12 or {}).get('mae')):>10} "
            f"{_pct((c24 or {}).get('median')):>10} {_pct((pv or {}).get('median')):>10}"
        )
    return "\n".join(lines)


def _pct(v) -> str:
    return "—" if v is None else f"{v * 100:+.1f}%"


# ── CLI ──────────────────────────────────────────────────────────────────────

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Forecast hindcast backtest")
    ap.add_argument("--formations", default=",".join(DEFAULT_FORMATIONS),
                    help="comma-separated public.wells.formation values")
    ap.add_argument("--per-formation", type=int, default=75)
    ap.add_argument("--truncations", default="12,24,36")
    ap.add_argument("--variants", default=",".join(VARIANTS))
    ap.add_argument("--holdout", type=int, default=HOLDOUT_MONTHS)
    ap.add_argument("--min-history", type=int, default=MIN_HISTORY_MONTHS)
    ap.add_argument("--out", default=None, help="results JSON path")
    ap.add_argument("--cache", default="results/backtest_eligible_cache.json")
    ap.add_argument("--refresh-cache", action="store_true")
    args = ap.parse_args(argv)

    import os
    os.makedirs("results", exist_ok=True)
    out_path = args.out or f"results/backtest_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

    result = run_backtest(
        formations=[f.strip() for f in args.formations.split(",") if f.strip()],
        per_formation=args.per_formation,
        truncations=[int(t) for t in args.truncations.split(",")],
        variants=[v.strip() for v in args.variants.split(",") if v.strip()],
        holdout=args.holdout,
        min_history=args.min_history,
        cache_path=args.cache,
        refresh_cache=args.refresh_cache,
    )
    result["summary"] = summarize(result["rows"])
    result["summary_by_classification"] = summarize(
        result["rows"], by=("classification", "variant"))

    with open(out_path, "w") as f:
        json.dump(result, f, default=str)
    print(f"\nwrote {out_path}  ({len(result['rows'])} rows; skips={result['skips']})\n")
    print(format_table(result["summary"], "== by truncation × variant =="))
    print()
    print(format_table(result["summary_by_classification"], "== by classification × variant =="))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
