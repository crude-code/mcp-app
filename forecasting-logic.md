This file is a merged representation of a subset of the codebase, containing specifically included files, combined into a single document by Repomix.

# File Summary

## Purpose
This file contains a packed representation of the entire repository's contents.
It is designed to be easily consumable by AI systems for analysis, code review,
or other automated processes.

## File Format
The content is organized as follows:
1. This summary section
2. Repository information
3. Directory structure
4. Multiple file entries, each consisting of:
  a. A header with the file path (## File: path/to/file)
  b. The full contents of the file in a code block

## Usage Guidelines
- This file should be treated as read-only. Any changes should be made to the
  original repository files, not this packed version.
- When processing this file, use the file path to distinguish
  between different files in the repository.
- Be aware that this file may contain sensitive information. Handle it with
  the same level of security as you would the original repository.

## Notes
- Some files may have been excluded based on .gitignore rules and Repomix's configuration
- Binary files are not included in this packed representation. Please refer to the Repository Structure section for a complete list of file paths, including binary files
- Only files matching these patterns are included: server/valuation/forecast.py, server/valuation/routing.py, server/valuation/types.py, server/valuation/config.py, server/valuation/orchestrator.py, server/valuation/backtest.py
- Files matching patterns in .gitignore are excluded
- Files matching default ignore patterns are excluded

## Additional Info

# Directory Structure
```
server/
  valuation/
    backtest.py
    config.py
    forecast.py
    orchestrator.py
    routing.py
    types.py
```

# Files

## File: server/valuation/backtest.py
```python
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
```

## File: server/valuation/config.py
```python
"""Tunable domain constants for the valuation engine.

Every economic parameter lives in the ``EconConfig`` dataclass (``ECON``
singleton below). Other engine constants still live next to their use sites
(post-peak threshold in ``routing.py``, server-default b in
``orchestrator.py``); consolidate here only when a real need appears.
"""
from dataclasses import dataclass, field
from datetime import date

from dateutil.relativedelta import relativedelta


# ── The valuation config: every economic parameter, one object ───────────────
#
# Single source for the economic side of a valuation. Forecast mechanics
# (server-default b, routing thresholds) deliberately live
# at their use sites — this object is deal economics only. Read it as
# `config.ECON.<field>`; never re-hardcode these values at a call site.

@dataclass(frozen=True)
class EconConfig:
    # Price deck — flat, v1 (NYMEX strip is a later slice).
    oil_price: float = 70.0          # $/bbl
    gas_price: float = 3.50          # $/MMBtu

    # Differentials off the deck.
    oil_diff: float = 0.0            # $/bbl
    gas_diff: float = 0.0            # $/MMBtu

    # Gas heat content, MMBtu per mcf. Production volumes are mcf; benchmark
    # prices (NYMEX Henry Hub / flat gas deck) are $/MMBtu — revenue must
    # convert: gas_mcf × btu × ($/MMBtu). 1.05 is a typical dry-gas heat
    # content; wet-gas areas run 1.1–1.3 (override per deal). NGL uplift and
    # shrink are out of scope — they partially offset at typical yields.
    gas_btu_factor: float = 1.05

    # Taxes / deductions (WI branch).
    tax_pct: float = 0.075           # severance/production
    gpt_pct: float = 0.05            # gathering, processing, transport

    # Operating + capital costs.
    opex_per_bbl_usd: float = 0.0
    opex_per_well_per_month_usd: float = 0.0
    capex_per_well_usd: float = 0.0  # drilling AFE, WI only

    # Cashflow horizon.
    horizon_months: int = 360        # 30 yr

    # Non-producing-well online timing (months from the first-of-next-month
    # anchor): a DUC is drilled awaiting completion (closer); a permit is not
    # yet spudded (further out).
    duc_months_to_first_prod: int = 18
    permit_months_to_first_prod: int = 36

    # Per-status annual discount-rate CENTERS (decimal). Each well-status stream
    # is discounted at its own cost of capital; uncertainty rises PDP → DUC → PUD.
    # The deal sheet bands each center by ``rate_spread`` into a 3-rung ladder
    # (center − spread / center / center + spread) and defaults to the center.
    # A user-supplied per-status rate overrides the center (see
    # ``resolve_rate_centers``); the spread stays fixed.
    default_rate_centers: dict[str, float] = field(default_factory=lambda: {
        "PDP": 0.15, "DUC": 0.20, "PUD": 0.25,
    })
    rate_spread: float = 0.025

    # Risked-cube flat oil reference decks ($/bbl), shown AFTER the base (strip)
    # column: the base prices off the run's path, then these flat-oil scenarios.
    # Gas is held at the run's gas path across every deck.
    deck_oil_flat: tuple[float, ...] = (70.0, 75.0, 80.0)


ECON = EconConfig()


def rate_ladder(center: float) -> tuple[float, float, float]:
    """A per-status discount ladder banded around ``center`` by ``ECON.rate_spread``:
    ``(center - spread, center, center + spread)``. Rounded to avoid IEEE-754
    subtraction artefacts (e.g. 0.15 − 0.025 = 0.12499…) that would otherwise
    break the percent-label keys (0.15 → 0.125 / 0.15 / 0.175)."""
    spread = ECON.rate_spread
    return (round(center - spread, 6), round(center, 6), round(center + spread, 6))


def resolve_rate_centers(econ_overrides: dict | None) -> dict[str, float]:
    """Per-status discount-rate centers for a deal: a user-supplied
    ``economics_overrides.discount_rates`` map (per status) overrides the
    config default center; any status the user omits keeps its default. The
    case file is validated at the MCP boundary, so values here are trusted."""
    overrides = (econ_overrides or {}).get("discount_rates") or {}
    return {
        code: float(overrides.get(code, default))
        for code, default in ECON.default_rate_centers.items()
    }


def deck_labels(price_mode: str = "strip") -> tuple[list[str], str]:
    """Ordered cube deck labels + the base label, for a given price mode.

    The first deck is the base — the run's actual oil path: the strip
    (``"Strip"``) or, under a flat override, ``"Flat"``. The remaining decks are
    fixed flat-oil reference scenarios from ``ECON.deck_oil_flat`` (``"$70"`` …).
    Both the cube builder and the deal-sheet spec read labels from here so the
    cube keys, the ``decks`` list, and the renderer's segmented control agree.
    """
    base = "Strip" if price_mode == "strip" else "Flat"
    return [base, *(f"${int(p)}" for p in ECON.deck_oil_flat)], base


def default_deck_label(price_mode: str = "strip") -> str:
    """The cube's default deck label — the base (first) deck: the run's price path."""
    return deck_labels(price_mode)[1]


def status_code(well_status: str | None) -> str:
    """Map a ``public.wells.well_status`` to the deal sheet's PV bucket.

    PRODUCING → PDP, DUC → DUC, PERMITTED → PUD. The ingest only loads those
    three statuses; anything else (or ``None``) falls back to the producing
    bucket so a well can never silently drop out of the cube.
    """
    s = (well_status or "").strip().upper()
    if s == "DUC":
        return "DUC"
    if s == "PERMITTED":
        return "PUD"
    return "PDP"


def first_of_next_month(d: date) -> date:
    """First day of the month following ``d`` (always rolls forward, even when
    ``d`` is already a first-of-month).

    This is the shared timeline anchor: the non-producing-well online dates and
    the economics NPV origin both reference it, so a DUC dated ``+18mo`` lands
    exactly 18 months into the cash-flow timeline.
    """
    return d.replace(day=1) + relativedelta(months=1)


def planned_first_prod_date(
    status: str | None,
    *,
    as_of: date,
    months_override: dict[str, int] | None = None,
) -> date | None:
    """Assumed first-production date for a non-producing well.

    Anchored at the first of the month following ``as_of`` (the valuation
    effective date, or today). DUCs come online ``ECON.duc_months_to_first_prod``
    months out; permits ``ECON.permit_months_to_first_prod``. Any other status
    (or ``None``) returns ``None`` — the engine has no basis to date it.

    ``months_override`` is a per-deal replacement of those default deltas, keyed
    by the deal-sheet status code (``DUC`` / ``PUD``, matching ``discount_rates``):
    e.g. ``{"PUD": 1}`` brings permitted wells online one month after the anchor
    instead of 36. A status absent from the map keeps its config default. The
    case file is validated at the MCP boundary, so values here are trusted.
    """
    anchor = first_of_next_month(as_of)
    s = (status or "").strip().upper()
    ov = months_override or {}
    if s == "DUC":
        return anchor + relativedelta(months=ov.get("DUC", ECON.duc_months_to_first_prod))
    if s == "PERMITTED":
        return anchor + relativedelta(months=ov.get("PUD", ECON.permit_months_to_first_prod))
    return None


def resolve_price_inputs(econ_overrides: dict | None) -> dict:
    """The deal's economic inputs for the cashflow math, read straight from the
    case file's ``economics_overrides`` — the single, validated input surface.

    The agent supplies NONE of these (same treatment ``interest`` and
    ``discount_rates`` already get): the server reads every number here, so the
    persisted record reflects what was *ordered*, not what the agent retyped. Any
    field the user omits falls back to its ``ECON`` house default. Values are
    trusted — the case file is shape-validated at the MCP boundary.

    Returns the kwargs the schedule builder consumes:
    ``{horizon_months, oil_price, gas_price, oil_diff, gas_diff, gas_btu_factor,
    tax_pct, gpt_pct}``.
    (Costs and discount rates are resolved separately, also from the case file.)
    """
    o = econ_overrides or {}
    deck = o.get("price_deck") or {}
    return {
        "horizon_months": int(o.get("forecast_horizon", ECON.horizon_months)),
        "oil_price": float(deck.get("oil_usd_bbl", ECON.oil_price)),
        "gas_price": float(deck.get("gas_usd_mmbtu", ECON.gas_price)),
        "oil_diff": float(o.get("oil_diff", ECON.oil_diff)),
        "gas_diff": float(o.get("gas_diff", ECON.gas_diff)),
        "gas_btu_factor": float(o.get("gas_btu_factor", ECON.gas_btu_factor)),
        "tax_pct": float(o.get("tax_pct", ECON.tax_pct)),
        "gpt_pct": float(o.get("gpt_pct", ECON.gpt_pct)),
    }


def resolve_as_of(effective_date: "str | date | None", *, today: date) -> date:
    """Resolve the valuation as-of date.

    Prefers ``effective_date`` (a ``date`` or ISO-8601 string) from the case
    file's ``economics_overrides``; falls back to ``today`` when it is absent
    or unparseable. Keeping ``today`` as a caller-supplied argument leaves this
    function pure and testable.
    """
    if effective_date is None:
        return today
    if isinstance(effective_date, date):
        return effective_date
    try:
        return date.fromisoformat(str(effective_date)[:10])
    except ValueError:
        return today
```

## File: server/valuation/forecast.py
```python
"""Decline curve fitting and projection. Pure math — no DB, no lateral norm."""
from datetime import date

import numpy as np
from dateutil.relativedelta import relativedelta
from scipy.optimize import curve_fit

from server.valuation.types import DeclineCurve, Forecast, ForecastProvenance


def _hyperbolic_q(t: np.ndarray, qi: float, di: float, b: float) -> np.ndarray:
    if b < 1e-6:
        return qi * np.exp(-di * t)
    return qi / np.power(1.0 + b * di * t, 1.0 / b)


def fit_curve(
    months: np.ndarray,
    q: np.ndarray,
    *,
    stream: str,
    terminal_di_annual: float = 0.05,
    min_post_peak_months: int = 6,
    b_fixed: float | None = None,
) -> DeclineCurve:
    """Fit hyperbolic decline to a well's production from peak forward.

    No ``lateral_norm_ft`` parameter — the cohort filter handles lateral matching.

    When ``b_fixed`` is set, fits only ``(qi_peak, di)`` with ``b`` held at the
    given value — Arps b is poorly identified on <~24 post-peak months and the
    3-param fit was riding the bounds (b≈0 or b≈2) on ~37% of wells. Pass a
    basin-typical b (0.7–1.0 for unconventional oil) for stable fits.

    Raises:
        ValueError if post-peak history is shorter than min_post_peak_months,
        or if all post-peak production is zero.
    """
    months = np.asarray(months, dtype=float)
    q = np.asarray(q, dtype=float)

    peak_idx = int(np.argmax(q))
    months_fit = months[peak_idx:]
    q_fit = q[peak_idx:]
    n_post_peak = len(q_fit) - 1
    if n_post_peak < min_post_peak_months:
        raise ValueError(
            f"thin history: need at least {min_post_peak_months} post-peak months, "
            f"got {n_post_peak} (peak at idx {peak_idx} of {len(q)})"
        )
    t_rel = months_fit - months_fit[0]
    if q_fit[1:].sum() <= 0.0:
        raise ValueError("fit_curve: no production data after peak")

    if b_fixed is None:
        p0 = [float(q_fit[0]), 0.05, 0.5]
        bounds = ([0.0, 0.0, 0.001], [1e8, 1.0, 2.0])
        popt, _ = curve_fit(_hyperbolic_q, t_rel, q_fit, p0=p0, bounds=bounds, maxfev=5000)
        qi_peak, di, b = (float(x) for x in popt)
    else:
        b = float(b_fixed)

        def _model_fixed_b(t, qi, di):
            return _hyperbolic_q(t, qi, di, b)

        p0 = [float(q_fit[0]), 0.05]
        bounds = ([0.0, 0.0], [1e8, 1.0])
        popt, _ = curve_fit(_model_fixed_b, t_rel, q_fit, p0=p0, bounds=bounds, maxfev=5000)
        qi_peak, di = (float(x) for x in popt)

    terminal_di_monthly = terminal_di_annual / 12.0
    if di > terminal_di_monthly and b > 1e-6:
        switch_month = max(0.0, (di / terminal_di_monthly - 1.0) / (b * di))
    else:
        switch_month = float("inf")

    return DeclineCurve(
        qi_peak=qi_peak,
        di=di,
        b=b,
        terminal_di_monthly=terminal_di_monthly,
        switch_month_from_peak=switch_month,
        stream=stream,
        provenance=ForecastProvenance(source="fit", fit_n_input_months=len(q_fit)),
    )


def percentile_curves(curves: list[DeclineCurve], *, pct: float = 0.5) -> DeclineCurve:
    """Aggregate N curves into a cohort curve via percentile.

    ``pct`` is in ``[0, 1]`` (0.5 = median, 0.1 = P10, 0.9 = P90). NO lateral
    rescaling — the cohort filter already constrains the inputs to comparable
    laterals.

    Raises:
        ValueError if ``curves`` is empty, if input curves mix streams, or if
        ``pct`` is outside ``[0, 1]``.
    """
    if not curves:
        raise ValueError("percentile_curves requires at least one input curve")
    if not 0.0 <= pct <= 1.0:
        raise ValueError(f"pct must be in [0, 1]; got {pct}")
    streams = {c.stream for c in curves}
    if len(streams) > 1:
        raise ValueError(f"all curves must share the same stream; got {streams}")

    qis = [c.qi_peak for c in curves]
    qi_pct = float(np.percentile(qis, pct * 100.0))
    di_pct = float(np.percentile([c.di for c in curves], pct * 100.0))
    b_pct = float(np.percentile([c.b for c in curves], pct * 100.0))
    terminal_di_pct = float(np.percentile([c.terminal_di_monthly for c in curves], pct * 100.0))
    if di_pct > terminal_di_pct and b_pct > 1e-6:
        switch_month = max(0.0, (di_pct / terminal_di_pct - 1.0) / (b_pct * di_pct))
    else:
        switch_month = float("inf")
    return DeclineCurve(
        qi_peak=qi_pct, di=di_pct, b=b_pct,
        terminal_di_monthly=terminal_di_pct,
        switch_month_from_peak=switch_month,
        stream=curves[0].stream,
        provenance=ForecastProvenance(
            source="percentile",
            component_curves=tuple(c.provenance for c in curves),
        ),
    )


def fit_curve_best_b(
    months: np.ndarray,
    q: np.ndarray,
    *,
    stream: str,
    b_grid: tuple[float, ...],
    terminal_di_annual: float = 0.05,
    min_post_peak_months: int = 6,
) -> DeclineCurve:
    """Fixed-b fits across ``b_grid``; returns the minimum-SSE curve.

    A bounded "free b" that cannot bound-ride: every candidate is a stable
    2-parameter :func:`fit_curve` at a fixed b, compared on post-peak SSE.
    Backtested 2026-07: for ≥30-post-peak-month wells this halves holdout MAE
    vs borrowing a cohort b (results/backtest_baseline_v1.json).

    Raises:
        ValueError if ``b_grid`` is empty, or wherever fit_curve raises (thin
        history, all-zero post-peak) — data validity is b-independent.
    """
    if not b_grid:
        raise ValueError("fit_curve_best_b requires a non-empty b_grid")
    q = np.asarray(q, dtype=float)
    peak_idx = int(np.argmax(q))
    q_fit = q[peak_idx:]
    t_rel = np.arange(len(q_fit), dtype=float)

    best: DeclineCurve | None = None
    best_sse = float("inf")
    for b in b_grid:
        curve = fit_curve(months, q, stream=stream, b_fixed=float(b),
                          terminal_di_annual=terminal_di_annual,
                          min_post_peak_months=min_post_peak_months)
        sse = float(np.sum((np.asarray(curve_rate(curve, t_rel)) - q_fit) ** 2))
        if sse < best_sse:
            best, best_sse = curve, sse
    return best


def override_b(curve: DeclineCurve, b: float, *, note: str) -> DeclineCurve:
    """The same curve with a re-sourced ``b``. The terminal switch month depends
    on (di, b), so it is recomputed; everything else is preserved. ``note`` lands
    in provenance.notes so the run record says where the b came from."""
    if curve.di > curve.terminal_di_monthly and b > 1e-6:
        switch = max(0.0, (curve.di / curve.terminal_di_monthly - 1.0) / (b * curve.di))
    else:
        switch = float("inf")
    return DeclineCurve(
        qi_peak=curve.qi_peak, di=curve.di, b=float(b),
        terminal_di_monthly=curve.terminal_di_monthly,
        switch_month_from_peak=switch,
        stream=curve.stream,
        provenance=ForecastProvenance(
            source=curve.provenance.source,
            fit_n_input_months=curve.provenance.fit_n_input_months,
            component_curves=curve.provenance.component_curves,
            notes=(*curve.provenance.notes, note),
        ),
    )


def curve_rate(curve: DeclineCurve, t_months: float | np.ndarray) -> float | np.ndarray:
    """Evaluate the curve at t months past peak.

    Accepts a scalar or an ``np.ndarray``; returns the same shape. Past
    ``switch_month_from_peak`` the curve follows an exponential at
    ``terminal_di_monthly``. Raises ValueError if any t is negative
    (no pre-peak extrapolation).
    """
    t = np.asarray(t_months, dtype=float)
    if np.any(t < 0):
        raise ValueError("curve_rate: negative t (pre-peak extrapolation) not supported")

    q_hyp = _hyperbolic_q(t, curve.qi_peak, curve.di, curve.b)
    if not np.isfinite(curve.switch_month_from_peak):
        result = q_hyp
    else:
        switch = curve.switch_month_from_peak
        q_at_switch = _hyperbolic_q(np.array([switch]), curve.qi_peak, curve.di, curve.b)[0]
        post = t >= switch
        result = np.where(
            post,
            q_at_switch * np.exp(-curve.terminal_di_monthly * (t - switch)),
            q_hyp,
        )
    if np.ndim(t_months) == 0:
        return float(result)
    return result


def project(forecast: Forecast, *, horizon_months: int) -> tuple[list[date], np.ndarray]:
    """Project a Forecast forward as monthly rates. NO lateral_scale.

    Returns ``(months, rates)`` where ``months[i]`` is the calendar month and
    ``rates[i]`` is the curve evaluated at ``t = peak_offset + i``, with
    ``peak_offset`` being the months between ``peak_date`` and ``start_date``.
    For wells where ``start_date == peak_date`` (PUDs, climbing wells)
    ``peak_offset == 0``. For PDP wells with history, ``peak_offset`` is the
    months elapsed between the historical peak and the forecast anchor.
    """
    if horizon_months <= 0:
        raise ValueError(f"horizon_months must be positive; got {horizon_months}")
    peak = forecast.peak_date.replace(day=1)
    start = forecast.start_date.replace(day=1)
    peak_offset = (start.year - peak.year) * 12 + (start.month - peak.month)
    if peak_offset < 0:
        raise ValueError(
            f"start_date {forecast.start_date} is before peak_date {forecast.peak_date}; "
            f"curve_rate does not support pre-peak extrapolation"
        )
    t_offsets = np.arange(peak_offset, peak_offset + horizon_months, dtype=float)
    rates = curve_rate(forecast.curve, t_offsets)

    months: list[date] = []
    cur = start
    for _ in range(horizon_months):
        months.append(cur)
        cur = cur + relativedelta(months=1)
    return months, rates


def aggregate(
    forecasts: list[Forecast],
    *,
    horizon_months: int,
    origin: date | None = None,
) -> tuple[list[date], np.ndarray]:
    """Sum N forecasts onto a shared monthly calendar axis.

    Each well is placed at its calendar offset from the axis ``origin`` (month
    0), so a well that comes online later contributes zeros until that month.
    ``origin`` defaults to the earliest ``start_date``; economics passes the
    valuation as-of month so a PUD coming online in 3 years is discounted as
    3 years out. A well whose ``start_date`` precedes ``origin`` (a producer
    already flowing at the as-of date) is clamped to month 0.

    Uses ``project`` per forecast so each well's ``peak_offset`` is honored.
    """
    if horizon_months <= 0:
        raise ValueError(f"horizon_months must be positive; got {horizon_months}")
    if not forecasts:
        return [], np.zeros(0)

    start = (origin or min(f.start_date for f in forecasts)).replace(day=1)
    months: list[date] = []
    cur = start
    for _ in range(horizon_months):
        months.append(cur)
        cur = cur + relativedelta(months=1)

    totals = np.zeros(horizon_months, dtype=float)
    for f in forecasts:
        f_start = f.start_date.replace(day=1)
        offset_months = (f_start.year - start.year) * 12 + (f_start.month - start.month)
        offset_months = max(0, offset_months)          # producing before origin -> month 0
        if offset_months >= horizon_months:
            continue
        per_forecast_horizon = horizon_months - offset_months
        _, rates = project(f, horizon_months=per_forecast_horizon)
        totals[offset_months:] += rates
    return months, totals
```

## File: server/valuation/orchestrator.py
```python
"""Valuation orchestrator. Runs forecast_wells → economics → deal-sheet assembly."""
import math
from datetime import date

import numpy as np
from dateutil.relativedelta import relativedelta

from server.valuation import config
from server.valuation import strip
from server.valuation.casefile import MAX_ASSET_WELLS, parse_run_params
from server.valuation.routing import (
    classify_well, build_curve, AnalogRequired, WellState,
)
from server.valuation.econ import cashflow_components, compute_gross_revenue, npv, resolve_well_interest
from server.valuation.forecast import fit_curve, override_b, percentile_curves, project
from server.valuation.run_record import ValuationRunStore
from server.valuation.types import DeclineCurve, Forecast, ForecastProvenance, WellMeta
from server.valuation.wells import bulk_load_production, bulk_load_wells


class CohortError(Exception):
    """Raised when no analog well can be fit into a type curve."""


class AnalogsRequired(Exception):
    """Bounce: one or more groups have wells needing analogs but supplied none."""
    def __init__(self, needs_analogs: list[dict]):
        self.needs_analogs = needs_analogs
        super().__init__("analogs_required")


# Server-default b when no cohort exists (all-history deal). Basin-typical
# unconventional oil. The plan picks 0.8.
_SERVER_DEFAULT_B = 0.8

# Cohort-b gating: b is only sourced from analogs mature enough to identify it
# (fit_curve's own docstring: poorly identified under ~24 post-peak months), and
# the sourced value is clamped to a sane unconventional band. Backtested
# 2026-07 (results/backtest_baseline_v1.json): consistent bias reduction vs the
# ungated median. qi/di stay full-cohort medians — young modern-completion
# analogs are the right source for rate level, just not for tail curvature.
_GATED_B_MIN_POST_PEAK = 24
_B_CLAMP = (0.3, 1.3)

_PLAN_FIELDS = {"cohort", "b"}


def validate_plan(plan: dict | None) -> dict:
    """Two-field plan: cohort (optional override) + b (optional override).

    Reject unknown fields aggressively — every field this grows is justified
    by a real deal that the current set couldn't express.

    Passes ``None`` through as ``{}`` (server uses defaults).
    """
    if plan is None:
        return {}
    if not isinstance(plan, dict):
        raise ValueError(f"plan must be an object, got {type(plan).__name__}")
    unknown = set(plan.keys()) - _PLAN_FIELDS
    if unknown:
        raise ValueError(f"unknown plan field(s): {sorted(unknown)}")
    if "b" in plan:
        b = plan["b"]
        if b == "cohort_median":
            pass                                   # server resolves
        elif isinstance(b, (int, float)) and not isinstance(b, bool):
            if not (0.001 <= b <= 2.0):
                raise ValueError(f"b must be in [0.001, 2.0] or 'cohort_median', got {b!r}")
        else:
            raise ValueError(f"b must be a number or 'cohort_median', got {b!r}")
    if "cohort" in plan and not isinstance(plan["cohort"], dict):
        raise ValueError("cohort must be an object")
    return plan


def _resolve_asset_list(asset_list: dict) -> list[str]:
    if asset_list.get("well_apis"):
        apis = list(dict.fromkeys(asset_list["well_apis"]))
        if len(apis) > MAX_ASSET_WELLS:
            raise ValueError(
                f"asset_list has {len(apis)} wells; at most {MAX_ASSET_WELLS} per valuation"
            )
        return apis

    # filter_sql is agent-authored — route through the SELECT-only guard.
    if not asset_list.get("filter_sql"):
        raise ValueError("asset_list must carry well_apis or filter_sql")
    where = asset_list["filter_sql"].strip()
    if not where.lower().startswith("where"):
        where = "WHERE " + where
    sql = f"SELECT well_api FROM public.wells {where}"

    from utils.sql_guard import GuardError, run_guarded
    from utils.schemas import EXPLORATION_SCHEMAS
    try:
        result = run_guarded(
            sql,
            schema="public",
            allowed_schemas=EXPLORATION_SCHEMAS,
            row_cap=MAX_ASSET_WELLS,
            size_cap_bytes=500_000,
        )
    except GuardError as exc:
        if "row cap" in str(exc):
            raise ValueError(
                f"filter_sql matched more than {MAX_ASSET_WELLS} wells — tighten the filter"
            ) from exc
        raise
    return [r["well_api"] for r in result["rows"]]


def _validate_by_api_membership(by_api: dict | None, known_apis: set[str]) -> None:
    """Every interest.by_api key must reference a well in the asset list.

    resolve_well_interest silently falls back to blanket interest for any well
    not in by_api — so a typo'd by_api key would silently misprice the well it
    was meant to override. Bounce it loudly instead."""
    if not by_api:
        return
    unknown = [api for api in by_api if api not in known_apis]
    if unknown:
        shown = ", ".join(unknown[:5])
        raise ValueError(
            f"{len(unknown)} interest.by_api key(s) are not in the asset list: "
            f"{shown}{'...' if len(unknown) > 5 else ''} — a typo here would "
            "silently misprice those wells"
        )


def _serialize_curve(c: DeclineCurve) -> dict:
    """DeclineCurve → JSON-safe dict. Infinity switch month persists as None.
    Provenance: only source + strategy are persisted; other fields are dropped."""
    switch = c.switch_month_from_peak
    return {
        "qi_peak": c.qi_peak, "di": c.di, "b": c.b,
        "terminal_di_monthly": c.terminal_di_monthly,
        "switch_month_from_peak": switch if math.isfinite(switch) else None,
        "stream": c.stream,
        "provenance": {"source": c.provenance.source, "strategy": c.provenance.strategy},
    }


def _deserialize_curve(c: dict) -> DeclineCurve:
    """Inverse of _serialize_curve. None switch month → float('inf').
    provenance is optional — curve dicts without it (e.g. raw dateless curves
    stored by the new forecast_wells stages) get a synthetic provenance."""
    switch = c["switch_month_from_peak"]
    if switch is None:
        switch = float("inf")
    prov = c.get("provenance") or {}
    return DeclineCurve(
        qi_peak=c["qi_peak"], di=c["di"], b=c["b"],
        terminal_di_monthly=c["terminal_di_monthly"],
        switch_month_from_peak=switch,
        stream=c["stream"],
        provenance=ForecastProvenance(
            source=prov.get("source", "cohort"),
            strategy=prov.get("strategy"),
        ),
    )


def _place_curve(*, self_curve: dict, start_date: str, strategy: str,
                 peak_date: str | None = None) -> dict:
    """Build a serialized-forecast dict from a (dateless) serialized curve and a
    start date. The forecast tools store dateless curves; run_valuation supplies
    start_date (PDP: the well's historical anchor; PUD: the status-derived online
    date). peak_date defaults to start_date (PUDs/climbing: peak is at the anchor).
    For producing wells with history, pass the historical peak month so project()
    sees a non-zero peak_offset and continues the decline instead of restarting."""
    return {
        "curve": self_curve,
        "peak_date": peak_date or start_date,
        "start_date": start_date,
        "strategy": strategy,
    }


def _deserialize_forecast(d: dict) -> Forecast:
    """Inverse of _serialize_forecast. Handles `None` switch_month as `float('inf')`.
    provenance is read from the curve dict when present (old serialized path) or
    synthesized when absent (new dateless-curve path from forecast_wells stages)."""
    curve_prov = (d["curve"].get("provenance") or {})
    return Forecast(
        curve=_deserialize_curve(d["curve"]),
        peak_date=date.fromisoformat(d["peak_date"]),
        start_date=date.fromisoformat(d["start_date"]),
        provenance=ForecastProvenance(
            source=curve_prov.get("source", "cohort"),
            strategy=d.get("strategy"),
        ),
    )


_SCHEDULE_COLS = (
    "oil_bbl", "gas_mcf", "net_oil", "net_gas", "gross_rev", "net_rev",
    "sev_tax", "gpt", "capex", "opex", "net_cashflow",
)


def _build_schedule(
    *,
    forecasts: dict,
    classifications: dict,
    origin: date,
    horizon: int,
    oil_price: float,
    gas_price: float,
    oil_diff: float,
    gas_diff: float,
    gas_btu_factor: float = config.ECON.gas_btu_factor,
    interest_type: str,
    wi_pct: float | None,
    nri_pct: float | None,
    decimal: float | None,
    tax_pct: float,
    gpt_pct: float,
    capex_per_well: float,
    opex_per_well_month: float,
    opex_per_bbl: float,
    by_api: dict | None = None,
) -> dict:
    """Per-well + total monthly cashflow schedule on the calendar axis.

    Each well is projected at its calendar offset from ``origin`` (PDP at month
    0, DUC/PUD at their online month), priced, costed (WI only — the AFE lands at
    a non-producing well's online month, opex accrues while it flows), and run
    through ``cashflow_components``. Totals are the elementwise sum across wells,
    so ``NPV(totals)`` equals the sum of the per-well NPVs by construction — the
    persisted schedule reconciles to the headline exactly.

    Returns ``{"by_well": {api: {col: ndarray}}, "totals": {col: ndarray}}`` with
    the columns in ``_SCHEDULE_COLS``.
    """
    month_index = np.arange(horizon, dtype=float)
    by_well: dict[str, dict[str, np.ndarray]] = {}
    for api, fs in forecasts.items():
        f_oil = _deserialize_forecast(fs["oil"])
        f_gas = _deserialize_forecast(fs["gas"])
        start = f_oil.start_date.replace(day=1)
        offset = max(0, (start.year - origin.year) * 12 + (start.month - origin.month))

        oil = np.zeros(horizon)
        gas = np.zeros(horizon)
        if offset < horizon:
            _, oil_rates = project(f_oil, horizon_months=horizon - offset)
            _, gas_rates = project(f_gas, horizon_months=horizon - offset)
            oil[offset:] = oil_rates
            gas[offset:] = gas_rates

        # Per-well interest: a by_api entry overrides the blanket scalars.
        eff = resolve_well_interest(
            interest_type, api, wi_pct=wi_pct, nri_pct=nri_pct, decimal=decimal, by_api=by_api,
        )
        w_wi, w_nri, w_dec = eff.get("wi_pct"), eff.get("nri_pct"), eff.get("decimal")

        gross = compute_gross_revenue(
            oil, gas, oil_price=oil_price, gas_price=gas_price,
            oil_diff=oil_diff, gas_diff=gas_diff, gas_btu_factor=gas_btu_factor,
        )
        capex = np.zeros(horizon)
        opex = np.zeros(horizon)
        if interest_type == "wi":
            online = (month_index >= offset).astype(float)
            opex = w_wi * (opex_per_well_month * online + opex_per_bbl * oil)
            if classifications.get(api) == "no_history" and offset < horizon:
                capex[offset] = w_wi * capex_per_well     # drilling AFE at the online month

        comp = cashflow_components(
            gross_rev=gross, interest_type=interest_type,
            capex_per_month=capex, opex_per_month=opex,
            tax_pct=tax_pct, gpt_pct=gpt_pct,
            wi_pct=w_wi, nri_pct=w_nri, decimal=w_dec,
        )
        # Net volumes scale gross by this well's revenue interest (nri for WI,
        # decimal for minerals) — so the production chart can sum true net volumes
        # even when interest varies well to well.
        net_frac = w_nri if interest_type == "wi" else w_dec
        by_well[api] = {
            "oil_bbl": oil, "gas_mcf": gas,
            "net_oil": oil * net_frac, "net_gas": gas * net_frac,
            **comp,
        }

    totals = {col: np.zeros(horizon) for col in _SCHEDULE_COLS}
    for sched in by_well.values():
        for col in _SCHEDULE_COLS:
            totals[col] += sched[col]
    return {"by_well": by_well, "totals": totals}


def _partition_net_cashflow(by_well: dict, statuses: dict) -> dict[str, np.ndarray]:
    """Sum per-well net cashflow into the three deal-sheet status buckets.

    Returns ``{code: ndarray}`` for every code in ``config.ECON.default_rate_centers``
    (zeros when no well maps to that bucket). Bucketing is by ``public.wells.well_status``
    via :func:`config.status_code`; a well missing from ``statuses`` falls back to
    the producing bucket. Because cashflows add, the three buckets sum exactly to
    ``schedule["totals"]["net_cashflow"]``.
    """
    horizon = len(next(iter(by_well.values()))["net_cashflow"]) if by_well else 0
    buckets = {code: np.zeros(horizon) for code in config.ECON.default_rate_centers}
    for api, cols in by_well.items():
        code = config.status_code(statuses.get(api))
        buckets[code] = buckets[code] + cols["net_cashflow"]
    return buckets


def _rate_label(rate: float) -> str:
    """Decimal annual rate → the cube's percent-string key (0.175 → '17.5')."""
    return f"{rate * 100:g}"


def _status_pv_cube(schedules_by_deck: dict[str, dict], statuses: dict, rate_centers: dict) -> dict:
    """The risked-PV cube: ``deck → status code → rate label → NPV (USD)``.

    Each status's three rungs are ``config.rate_ladder(rate_centers[code])`` —
    the per-status center banded ±spread. Status PVs are additive at a common
    rate, so the client sums the three selected cells for the headline.
    """
    cube: dict[str, dict] = {}
    for deck_label, sched in schedules_by_deck.items():
        buckets = _partition_net_cashflow(sched["by_well"], statuses)
        cube[deck_label] = {
            code: {_rate_label(r): npv(buckets[code], annual_rate=r)
                   for r in config.rate_ladder(center)}
            for code, center in rate_centers.items()
        }
    return cube


def _compute_npv_by_status(*, base_schedule_kwargs: dict, oil_price_vec, gas_price_vec,
                           price_mode: str, statuses: dict, rate_centers: dict) -> dict:
    """Build a cashflow schedule per deck and return the risked-PV cube.

    The first deck (``base``) prices off ``oil_price_vec`` — the run's actual oil
    path (the strip, or a flat override as a constant vector). The remaining
    decks are flat-oil reference scenarios from ``config.ECON.deck_oil_flat``
    (constant ``$/bbl`` vectors). Gas is held at ``gas_price_vec`` across every
    deck. ``base_schedule_kwargs`` are the :func:`_build_schedule` arguments
    minus ``oil_price``/``gas_price``. Volumes are price-independent, so only the
    oil price varies across decks — costs (capex/opex) are unchanged.
    """
    labels, base = config.deck_labels(price_mode)
    horizon = len(oil_price_vec)
    schedules = {
        base: _build_schedule(**base_schedule_kwargs,
                              oil_price=oil_price_vec, gas_price=gas_price_vec)
    }
    for price, label in zip(config.ECON.deck_oil_flat, labels[1:]):
        schedules[label] = _build_schedule(**base_schedule_kwargs,
                                           oil_price=np.full(horizon, price), gas_price=gas_price_vec)
    return _status_pv_cube(schedules, statuses, rate_centers)


_MAX_BY_WELL_AUDIT = 200  # per-well audit rows omitted above this count to keep JSONB manageable


def _serialize_schedule(sched: dict, *, origin: date, horizon: int, rate_centers: dict) -> dict:
    """JSON-safe, rounded form of a schedule for the run record (the audit trail).

    Column-oriented (parallel arrays index-aligned to ``months``) and rounded to
    cents to keep the JSONB compact.

    ``by_well`` is included only when the deal has ≤ ``_MAX_BY_WELL_AUDIT`` wells;
    for larger deals it is omitted (``by_well_omitted`` records why) to avoid
    generating hundreds of MB of JSONB. Totals are always built."""
    months: list[str] = []
    cur = origin
    for _ in range(horizon):
        months.append(cur.isoformat())
        cur = cur + relativedelta(months=1)

    def _cols(d: dict) -> dict:
        return {col: [round(float(v), 2) for v in d[col]] for col in _SCHEDULE_COLS}

    result: dict = {
        "origin": origin.isoformat(),
        "months": months,
        "rate_centers": dict(rate_centers),
        "columns": list(_SCHEDULE_COLS),
        "totals": _cols(sched["totals"]),
    }
    n_wells = len(sched["by_well"])
    if n_wells <= _MAX_BY_WELL_AUDIT:
        result["by_well"] = {api: _cols(cols) for api, cols in sched["by_well"].items()}
    else:
        result["by_well_omitted"] = (
            f"{n_wells} wells exceeds the {_MAX_BY_WELL_AUDIT}-well audit cap"
        )
    return result


def _interest_from_record(case_file: dict | None, assumptions: dict) -> dict:
    """Normalized interest inputs, sourced from the authoritative case file.

    Returns ``{interest_type, wi_pct, nri_pct}`` (WI) or ``{interest_type,
    decimal}`` (minerals), plus an optional ``by_api`` map of per-well overrides.
    The case file is the source of truth (validated at the MCP boundary); for
    legacy runs whose case file predates server-sourced interest, falls back to
    the agent's ``assumptions`` for the blanket numbers.
    """
    case_interest = (case_file or {}).get("interest")
    src = case_interest if isinstance(case_interest, dict) else assumptions
    itype = (case_file or {}).get("interest_type") or assumptions.get("interest_type")

    out: dict = {"interest_type": itype}
    if itype == "wi":
        out["wi_pct"] = float(src["wi_pct"])
        out["nri_pct"] = float(src["nri_pct"])
    else:
        out["decimal"] = float(src["decimal"])

    by_api = case_interest.get("by_api") if isinstance(case_interest, dict) else None
    if by_api:
        out["by_api"] = by_api
    return out


def _economics_from_forecasts(*, forecasts: dict, classifications: dict,
                              statuses: dict, econ_overrides: dict) -> dict:
    """Pure economics: monthly schedule → risked-PV cube → NPV. Takes the
    assembled (already calendar-placed) forecasts + classifications + statuses.
    Every economic number is read from econ_overrides (the validated params)."""
    inputs = config.resolve_price_inputs(econ_overrides)
    horizon = inputs["horizon_months"]
    origin = config.first_of_next_month(
        config.resolve_as_of(econ_overrides.get("effective_date"), today=date.today())
    )
    # Base oil/gas price PATHS over the horizon: live NYMEX strip by default
    # (flat is an opt-in override). compute_gross_revenue broadcasts a vector
    # price against the per-month production vector — no formula change.
    price = strip.resolve_price_series(
        econ_overrides, origin=origin, horizon_months=horizon,
        flat_oil=inputs["oil_price"], flat_gas=inputs["gas_price"],
    )
    oil_vec, gas_vec = price["oil"], price["gas"]
    # inputs carries representative display scalars + the mode/trade-date for the
    # econ panel; the schedule/cube use the full vectors above.
    inputs["oil_price"] = price["oil_repr"]
    inputs["gas_price"] = price["gas_repr"]
    inputs["price_mode"] = price["mode"]
    inputs["strip_trade_date"] = price["trade_date"].isoformat() if price["trade_date"] else None

    interest = _interest_from_record({"interest_type": econ_overrides.get("interest_type"),
                                      "interest": econ_overrides.get("interest")}, {})
    interest_type = interest["interest_type"]
    _validate_by_api_membership(interest.get("by_api"), set(forecasts))

    base_schedule_kwargs = dict(
        forecasts=forecasts, classifications=classifications, origin=origin,
        horizon=horizon, oil_diff=inputs["oil_diff"], gas_diff=inputs["gas_diff"],
        gas_btu_factor=inputs["gas_btu_factor"],
        interest_type=interest_type, wi_pct=interest.get("wi_pct"),
        nri_pct=interest.get("nri_pct"), decimal=interest.get("decimal"),
        by_api=interest.get("by_api"), tax_pct=inputs["tax_pct"], gpt_pct=inputs["gpt_pct"],
        capex_per_well=float(econ_overrides.get("capex_per_well_usd", config.ECON.capex_per_well_usd)),
        opex_per_well_month=float(econ_overrides.get("opex_per_well_per_month_usd", config.ECON.opex_per_well_per_month_usd)),
        opex_per_bbl=float(econ_overrides.get("opex_per_bbl_usd", config.ECON.opex_per_bbl_usd)),
    )
    sched = _build_schedule(**base_schedule_kwargs, oil_price=oil_vec, gas_price=gas_vec)
    rate_centers = config.resolve_rate_centers(econ_overrides)
    net_cf = sched["totals"]["net_cashflow"]
    npv_by_status = _compute_npv_by_status(
        base_schedule_kwargs=base_schedule_kwargs, oil_price_vec=oil_vec,
        gas_price_vec=gas_vec, price_mode=price["mode"],
        statuses=statuses, rate_centers=rate_centers,
    )
    deck = config.default_deck_label(price["mode"])
    by_status_center = {
        code: float(npv_by_status[deck][code][_rate_label(config.rate_ladder(center)[1])])
        for code, center in rate_centers.items()
    }
    npv_at_centers = {"by_status": by_status_center, "total": float(sum(by_status_center.values()))}
    return {
        "npv_at_centers": npv_at_centers, "rate_centers": rate_centers,
        "npv_by_status": npv_by_status, "cashflow_total_undiscounted": float(net_cf.sum()),
        "horizon_months": horizon, "inputs": inputs, "interest": interest,
        "schedule": _serialize_schedule(sched, origin=origin, horizon=horizon, rate_centers=rate_centers),
        "price_path": {
            "oil": [round(float(v), 4) for v in oil_vec],
            "gas": [round(float(v), 4) for v in gas_vec],
        },
        "cost_inputs": {
            "capex_per_well": float(base_schedule_kwargs["capex_per_well"]),
            "opex_per_well_month": float(base_schedule_kwargs["opex_per_well_month"]),
            "opex_per_bbl": float(base_schedule_kwargs["opex_per_bbl"]),
        },
    }


def compose_artifact_payload_for_run(run_id: str) -> dict:
    """Read the wells + economics stages and build the slim artifact payload
    `run_valuation` returns for Claude to build a deal-sheet artifact from.
    See `server.valuation.artifact_payload.build_artifact_payload`."""
    from server.valuation.artifact_payload import build_artifact_payload

    store = ValuationRunStore()
    economics = store.read_stage(run_id, stage="economics")
    if not economics:
        raise ValueError(f"run {run_id}: no economics stage (call run_economics first)")
    wells = store.read_stage(run_id, stage="wells") or {}
    return build_artifact_payload(economics=economics, wells=wells)


def _well_meta_payload(apis: list[str], meta_by_api: dict) -> dict:
    """Per-well facts for the deal sheet, keyed by API. Missing wells → all-None."""
    out: dict[str, dict] = {}
    for api in apis:
        m = meta_by_api.get(api)
        out[api] = {
            "status": m.status if m else None,
            "operator": m.operator if m else None,
            "basin": m.basin if m else None,
            "formation": m.formation if m else None,
            "lateral_ft": m.lateral_ft if m else None,
        }
    return out



def _build_type_curve_with_stats(prod: dict, stream: str):
    """Median type curve from analog fits, plus fit stats and b provenance.

    Returns ``(curve, n_fit, n_skipped, b_meta)``. qi/di/terminal are the
    full-cohort parameter-wise medians of free fits (unchanged); the cohort b is
    GATED — median only of analogs with ≥ ``_GATED_B_MIN_POST_PEAK`` post-peak
    months, clamped to ``_B_CLAMP``, falling back to ``_SERVER_DEFAULT_B`` when
    no analog is mature enough to identify b. ``b_meta`` records which path won
    (``{"b": float, "source": str, "n_mature": int}``) and flows to
    ``analogs_used`` so the agent can see when the cohort was too young.

    ``prod`` is a preloaded bulk_load_production result (caller loads once and
    passes to both oil and gas calls — avoids double DB round-trip)."""
    q_col = "oil_bbl" if stream == "oil" else "gas_mcf"
    curves = []
    mature_bs: list[float] = []
    for _api, d in prod.items():
        q = np.asarray(d[q_col], dtype=float)
        try:
            c = fit_curve(np.arange(len(q), dtype=float), q, stream=stream, b_fixed=None)
        except ValueError:
            continue
        curves.append(c)
        if len(q) - 1 - int(np.argmax(q)) >= _GATED_B_MIN_POST_PEAK:
            mature_bs.append(c.b)
    n_fit, n_skipped = len(curves), len(prod) - len(curves)
    if not curves:
        raise CohortError(f"no analog fit for stream={stream} ({len(prod)} tried)")
    cohort = percentile_curves(curves, pct=0.5)
    if mature_bs:
        b = min(max(float(np.median(mature_bs)), _B_CLAMP[0]), _B_CLAMP[1])
        source = f"gated_median(n={len(mature_bs)})"
    else:
        b = _SERVER_DEFAULT_B
        source = "default_no_mature_analogs"
    b_meta = {"b": round(b, 4), "source": source, "n_mature": len(mature_bs)}
    return override_b(cohort, b, note=f"b:{source}"), n_fit, n_skipped, b_meta


def _classify_overall(d: dict) -> WellState:
    """Gas-aware overall state for cohort-need + summary. Gas-only wells (zero oil,
    real gas) classify off gas so they aren't mislabeled HISTORY on a zero stream."""
    q_oil = np.asarray(d.get("oil_bbl", []), dtype=float)
    q_gas = np.asarray(d.get("gas_mcf", []), dtype=float)
    if q_oil.sum() <= 0 and len(q_gas) and q_gas.sum() > 0:
        return classify_well(d.get("months", []), q_gas)
    return classify_well(d.get("months", []), q_oil)


_NEEDS_ANALOG = {WellState.THIN_PEAKED, WellState.CLIMBING, WellState.NO_HISTORY}


def forecast_wells_for_run(*, run_id: str | None, groups: list[dict], user_id: int = 0) -> dict:
    """Classify every subject well, bounce (all-or-nothing) if a group needs
    analogs and has none, fit each group's analogs into a median type curve, blend
    per the routing table, and write ONE dateless `forecast` stage."""
    if not groups:
        raise ValueError("forecast_wells requires a non-empty groups list")

    store = ValuationRunStore()

    # Load all subjects once.
    all_subjects = [a for g in groups for a in (g.get("wells") or [])]
    if not all_subjects:
        raise ValueError("forecast_wells: every group must list at least one well")
    metas = {m.api: m for m in bulk_load_wells(all_subjects)}
    missing = [a for a in all_subjects if a not in metas]
    if missing:
        raise ValueError(f"{len(missing)} well API(s) not found in public.wells: {missing[:5]}")
    subj_prod = bulk_load_production(all_subjects)

    # First pass: classify + detect bounces. No writes until every group passes.
    overall: dict[str, WellState] = {}
    needs_analogs: list[dict] = []
    for g in groups:
        wells = g.get("wells") or []
        analogs = g.get("analogs") or []
        short = []
        for api in wells:
            st = _classify_overall(subj_prod.get(api, {"months": [], "oil_bbl": [], "gas_mcf": []}))
            overall[api] = st
            if st in _NEEDS_ANALOG and not analogs:
                short.append(api)
        if short:
            needs_analogs.append({"area": g.get("area"), "wells": short})
    if needs_analogs:
        raise AnalogsRequired(needs_analogs)

    # Second pass: fit analogs per group, build per-well curves, accumulate.
    # Nothing is minted or written until EVERY well in every group has a curve —
    # a per-stream AnalogRequired here (e.g. an oil-HISTORY well whose gas
    # stream is CLIMBING on rising GOR, in a group with no analogs) becomes a
    # clean AnalogsRequired bounce, exactly like the first-pass check.
    forecasts: dict[str, dict] = {}
    group_meta: list[dict] = []
    return_groups: list[dict] = []
    stream_short: list[dict] = []
    from collections import defaultdict
    oil_by_month: dict[str, float] = defaultdict(float)
    gas_by_month: dict[str, float] = defaultdict(float)

    for g in groups:
        wells = g.get("wells") or []
        analogs = g.get("analogs") or []
        oil_tc = gas_tc = None
        n_fit = n_skipped = 0
        b_meta_oil = None
        if analogs:
            analog_prod = bulk_load_production(analogs)
            oil_tc, n_fit, n_skipped, b_meta_oil = _build_type_curve_with_stats(analog_prod, "oil")
            gas_tc, _, _, _ = _build_type_curve_with_stats(analog_prod, "gas")

        by_status: dict[str, list] = {"PDP": [], "DUC": [], "PUD": []}
        spectrum = {s.value: 0 for s in WellState}
        short: list[str] = []
        for api in wells:
            d = subj_prod.get(api, {"months": [], "oil_bbl": [], "gas_mcf": []})
            q_oil = np.asarray(d["oil_bbl"], dtype=float)
            q_gas = np.asarray(d["gas_mcf"], dtype=float)
            try:
                oil_curve, _st, oil_strat = build_curve(d["months"], q_oil, analog=oil_tc, stream="oil")
                gas_curve, _gst, _gstrat = build_curve(d["months"], q_gas, analog=gas_tc, stream="gas")
            except AnalogRequired:
                short.append(api)
                continue
            st = overall[api]
            spectrum[st.value] += 1
            status = metas[api].status
            anchor = d["months"][-1] if d["months"] else None
            entry = {
                "oil": {"curve": _serialize_curve(oil_curve)},
                "gas": {"curve": _serialize_curve(gas_curve)},
                "classification": st.value,
                "strategy": oil_strat,
                "status": status,
            }
            if anchor:
                entry["anchor_month"] = anchor
                # Per-stream historical peak month so _load_forecast_stage can
                # place the curve at the right offset (project() expects
                # peak_offset = months(peak → anchor)).
                entry["oil"]["peak_month"] = d["months"][int(np.argmax(q_oil))]
                entry["gas"]["peak_month"] = d["months"][int(np.argmax(q_gas))]
            forecasts[api] = entry
            bucket = config.status_code(status)   # "PDP" | "DUC" | "PUD"
            by_status[bucket].append({
                "api": api, "strategy": oil_strat, "status": status,
                "months_producing": len(d["months"]),
            })
            for i, mo in enumerate(d["months"]):
                oil_by_month[mo] += float(d["oil_bbl"][i])
                gas_by_month[mo] += float(d["gas_mcf"][i])

        if short:
            stream_short.append({"area": g.get("area"), "wells": short})
        gm = {"area": g.get("area")}
        if oil_tc is not None:
            gm["type_curve"] = {"oil": _serialize_curve(oil_tc), "gas": _serialize_curve(gas_tc)}
            gm["analog_meta"] = {"analog_apis": list(analogs), "n_fit": n_fit,
                                 "n_skipped": n_skipped, "b_meta": b_meta_oil}
        group_meta.append(gm)
        analogs_used = {"n_requested": len(analogs), "n_fit": n_fit, "n_skipped": n_skipped}
        if b_meta_oil is not None:
            analogs_used["cohort_b"] = b_meta_oil
        return_groups.append({
            "area": g.get("area"), "by_status": by_status, "spectrum": spectrum,
            "analogs_used": analogs_used,
        })

    if stream_short:
        raise AnalogsRequired(stream_short)

    if run_id is None:
        run_id = store.new_run(user_id=user_id, case_file={})

    ordered = sorted(oil_by_month)
    actual_history = {
        "dates": ordered,
        "oil": [round(oil_by_month[m], 1) for m in ordered],
        "gas": [round(gas_by_month[m], 1) for m in ordered],
    }
    store.write_stage(run_id, stage="forecast", payload={
        "forecasts": forecasts, "groups": group_meta, "actual_history": actual_history,
    })
    return {"run_id": run_id, "groups": return_groups}


def _load_forecast_stage(*, forecast: dict, as_of, months_override):
    """Place the single dateless `forecast` stage on the calendar for economics.
    Producing wells (have anchor_month) anchor at their last history month; others
    anchor at the status-derived planned first-prod date (else as_of).

    For producing wells, each stream's stored peak_month is passed as peak_date so
    project() computes the correct peak_offset (months elapsed from historical peak
    to anchor). This makes the decline continue from the anchor rate rather than
    restart at qi_peak. CLIMBING wells' argmax IS the last month (peak==anchor,
    peak_offset==0) so they are already correct and unchanged by this path."""
    def _norm(d: str | None) -> str | None:
        """Normalize a 'YYYY-MM' partial date to 'YYYY-MM-01' for fromisoformat."""
        return d if (d is None or len(d) != 7) else d + "-01"

    forecasts: dict[str, dict] = {}
    classifications: dict[str, str] = {}
    statuses: dict[str, str] = {}
    for api, fc in (forecast.get("forecasts") or {}).items():
        strat = fc.get("strategy", "pure_analog")
        anchor = fc.get("anchor_month")
        if anchor:
            start = _norm(anchor)
            oil_peak = _norm(fc["oil"].get("peak_month")) or start
            gas_peak = _norm(fc["gas"].get("peak_month")) or start
            forecasts[api] = {
                "oil": _place_curve(self_curve=fc["oil"]["curve"], start_date=start,
                                    strategy=strat, peak_date=oil_peak),
                "gas": _place_curve(self_curve=fc["gas"]["curve"], start_date=start,
                                    strategy=strat, peak_date=gas_peak),
            }
        else:
            online = config.planned_first_prod_date(
                fc.get("status"), as_of=as_of, months_override=months_override)
            start = str(online or as_of)
            forecasts[api] = {
                "oil": _place_curve(self_curve=fc["oil"]["curve"], start_date=start, strategy=strat),
                "gas": _place_curve(self_curve=fc["gas"]["curve"], start_date=start, strategy=strat),
            }
        classifications[api] = fc.get("classification", "no_history")
        statuses[api] = fc.get("status") or "PUD"
    return forecasts, classifications, statuses


def run_valuation_for_run(*, run_id: str, params: dict) -> dict:
    """Read the single forecast stage, place wells on the calendar, run economics,
    assemble the deal sheet. params is the validated deal terms (interest +
    economics_overrides + asset_list)."""
    case = parse_run_params(params)        # raises CaseFileError on bad params
    interest_type = case.interest_type
    store = ValuationRunStore()
    forecast = store.read_stage(run_id, stage="forecast")
    if not forecast:
        raise ValueError(f"run {run_id}: no forecast stage — call forecast_wells first")

    econ_overrides = dict(params.get("economics_overrides") or {})
    # Fold interest into econ_overrides so the economics core is self-contained.
    econ_overrides["interest_type"] = interest_type
    econ_overrides["interest"] = params.get("interest")
    as_of = config.resolve_as_of(econ_overrides.get("effective_date"), today=date.today())
    months_override = econ_overrides.get("months_to_first_prod")

    forecasts, classifications, statuses = _load_forecast_stage(
        forecast=forecast, as_of=as_of, months_override=months_override)

    econ = _economics_from_forecasts(
        forecasts=forecasts, classifications=classifications,
        statuses=statuses, econ_overrides=econ_overrides)
    store.write_stage(run_id, stage="economics", payload=econ)

    # Reload meta for the deal-sheet facts/buckets (correct regardless of stages).
    apis = list(forecasts)
    meta_by_api = {m.api: m for m in bulk_load_wells(apis)}
    store.write_stage(run_id, stage="wells", payload={
        "well_meta": _well_meta_payload(apis, meta_by_api),
        "statuses": {a: (meta_by_api[a].status if a in meta_by_api else None) for a in apis},
        "classifications": classifications,
    })

    return {"run_id": run_id, "npv_at_centers": econ["npv_at_centers"]}
```

## File: server/valuation/routing.py
```python
"""Per-well forecast routing — dateless. Classifies a well by its production
shape and returns a DeclineCurve blending its own data with a Claude-supplied
analog type curve. No dates, no calendar placement (run_valuation owns that).

WellState ladder:
    HISTORY       — peaked AND >=9 post-peak months -> own fit, analog lends b;
                    at >=30 post-peak months the well earns its OWN b via a
                    bounded grid fit (strategy "history_own_b") — backtested
                    2026-07: halves holdout MAE vs borrowed b on long histories
    THIN_PEAKED   — peaked AND <9 post-peak months  -> own peak, analog di+b
    CLIMBING      — has production but argmax == last -> max(analog, own_max), analog di+b
    NO_HISTORY    — no production -> analog curve outright

Zero-stream guard (before the ladder): all-zero stream or all-zero-after-peak ->
flat-zero curve (fit_curve would raise; the analog would fabricate volumes).
"""
from enum import Enum
import numpy as np

from server.valuation.forecast import fit_curve, fit_curve_best_b
from server.valuation.types import DeclineCurve, ForecastProvenance


_MIN_POST_PEAK_HISTORY = 9
_SERVER_DEFAULT_B = 0.8
_OWN_B_MIN_POST_PEAK = 30                    # earn your own b above this
B_GRID = tuple(round(0.30 + 0.05 * i, 2) for i in range(21))   # 0.30 … 1.30


class AnalogRequired(Exception):
    """Raised by build_curve when the well's state needs an analog but none given.
    Carries the stream so the orchestrator can bounce with a useful message."""

    def __init__(self, stream: str):
        self.stream = stream
        super().__init__(f"analog required for {stream} stream")


class WellState(str, Enum):
    HISTORY = "history"
    THIN_PEAKED = "thin_peaked"
    CLIMBING = "climbing"
    NO_HISTORY = "no_history"


def classify_well(months: list[str], q: np.ndarray) -> WellState:
    if len(q) == 0:
        return WellState.NO_HISTORY
    peak_idx = int(np.argmax(q))
    if peak_idx == len(q) - 1:
        return WellState.CLIMBING
    if (len(q) - 1 - peak_idx) >= _MIN_POST_PEAK_HISTORY:
        return WellState.HISTORY
    return WellState.THIN_PEAKED


def _zero_curve(stream: str) -> DeclineCurve:
    return DeclineCurve(
        qi_peak=0.0, di=0.0, b=0.0, terminal_di_monthly=0.0,
        switch_month_from_peak=float("inf"), stream=stream,
        provenance=ForecastProvenance(source="rule", strategy="zero_stream"),
    )


def _blend(qi: float, analog: DeclineCurve, stream: str, strategy: str) -> DeclineCurve:
    return DeclineCurve(
        qi_peak=qi, di=analog.di, b=analog.b,
        terminal_di_monthly=analog.terminal_di_monthly,
        switch_month_from_peak=analog.switch_month_from_peak,
        stream=stream,
        provenance=ForecastProvenance(source="blend", strategy=strategy),
    )


def build_curve(months: list[str], q: np.ndarray, *,
                analog: DeclineCurve | None, stream: str) -> tuple[DeclineCurve, WellState, str]:
    """Return (curve, state, strategy). Dateless — caller stores the anchor month
    separately and run_valuation places the curve on the calendar."""
    state = classify_well(months, q)

    if state == WellState.NO_HISTORY:
        if analog is None:
            raise AnalogRequired(stream)
        return analog, state, "pure_analog"

    # Zero-stream guard (producing states only).
    peak_idx = int(np.argmax(q))
    if float(q.sum()) <= 0.0 or (peak_idx < len(q) - 1 and float(q[peak_idx + 1:].sum()) <= 0.0):
        return _zero_curve(stream), state, "zero_stream"

    if state == WellState.HISTORY:
        if (len(q) - 1 - peak_idx) >= _OWN_B_MIN_POST_PEAK:
            curve = fit_curve_best_b(np.arange(len(q), dtype=float), q, stream=stream,
                                     b_grid=B_GRID,
                                     min_post_peak_months=_MIN_POST_PEAK_HISTORY)
            return curve, state, "history_own_b"
        b = analog.b if analog is not None else _SERVER_DEFAULT_B
        curve = fit_curve(np.arange(len(q), dtype=float), q, stream=stream,
                          b_fixed=b, min_post_peak_months=_MIN_POST_PEAK_HISTORY)
        return curve, state, "history"

    if analog is None:
        raise AnalogRequired(stream)

    if state == WellState.THIN_PEAKED:
        return _blend(float(q[peak_idx]), analog, stream, "thin_blend"), state, "thin_blend"

    # CLIMBING
    return _blend(max(analog.qi_peak, float(q.max())), analog, stream, "climbing"), state, "climbing"
```

## File: server/valuation/types.py
```python
"""Engine types. NO lateral_norm_ft, NO lateral_scale — analog selection
(Claude's judgment: comparable laterals in the cohort) is the only place
lateral enters the model; the server never rescales."""
from dataclasses import dataclass, field
from datetime import date


@dataclass(frozen=True)
class ForecastProvenance:
    source: str                                 # "fit" | "percentile" | "blend" | "cohort"
    fit_n_input_months: int = 0
    component_curves: tuple["ForecastProvenance", ...] = field(default_factory=tuple)
    notes: tuple[str, ...] = field(default_factory=tuple)
    strategy: str | None = None                 # "history" | "history_own_b" | "thin_blend" |
                                                # "climbing" | "pure_analog" | "zero_stream"


@dataclass(frozen=True)
class DeclineCurve:
    qi_peak: float
    di: float
    b: float
    terminal_di_monthly: float
    switch_month_from_peak: float            # float("inf") when no terminal switch
    stream: str                                 # "oil" | "gas"
    provenance: ForecastProvenance


@dataclass(frozen=True)
class Forecast:
    curve: DeclineCurve
    peak_date: date
    start_date: date
    provenance: ForecastProvenance


@dataclass(frozen=True)
class WellMeta:
    api: str
    status: str
    basin: str | None
    formation: str | None
    county: str | None
    lateral_ft: float | None
    spud_date: date | None
    completion_date: date | None
    first_prod_date: date | None
    last_prod_date: date | None
    n_history_months: int
    planned_first_prod_date: date | None        # spud_date + offset if first_prod_date is None
    geom_wkt: str | None = None                 # well point as WKT, for centroid math
    operator: str | None = None                 # public.wells.operator (free-text)
```
