"""Backtest harness: pure logic tests + a db-marked smoke test.

The synthetic-series tests generate production from known DeclineCurves and
assert the harness recovers what it should — placement (a perfect curve scores
~zero error), b-grid recovery, gated/late-window sourcing, and determinism.
"""
import math

import numpy as np
import pytest

from server.valuation import backtest as bt
from server.valuation.forecast import curve_rate
from server.valuation.types import DeclineCurve, ForecastProvenance


def _curve(qi=15000.0, di=0.06, b=0.9, stream="oil") -> DeclineCurve:
    return DeclineCurve(
        qi_peak=qi, di=di, b=b, terminal_di_monthly=0.05 / 12.0,
        switch_month_from_peak=float("inf"), stream=stream,
        provenance=ForecastProvenance(source="fit"),
    )


def _series(curve: DeclineCurve, n: int) -> list[float]:
    """Monthly volumes from a curve, peak at month 0 (monotone decline)."""
    return [float(v) for v in np.asarray(curve_rate(curve, np.arange(n, dtype=float)))]


def _months(n: int, start_year=2020) -> list[str]:
    out = []
    y, m = start_year, 1
    for _ in range(n):
        out.append(f"{y:04d}-{m:02d}-01")
        m += 1
        if m > 12:
            y, m = y + 1, 1
    return out


def _prod(curve: DeclineCurve, n: int) -> dict:
    oil = _series(curve, n)
    return {"months": _months(n), "oil_bbl": oil,
            "gas_mcf": [v * 2.0 for v in oil]}


# ── slicing / helpers ────────────────────────────────────────────────────────

def test_truncate_at_is_point_in_time():
    prod = _prod(_curve(), 40)
    cutoff = prod["months"][23]
    t = bt._truncate_at(prod, cutoff)
    assert len(t["months"]) == 24
    assert t["months"][-1] == cutoff
    assert t["oil_bbl"] == prod["oil_bbl"][:24]


def test_post_peak_months():
    q = np.array([1.0, 5.0, 3.0, 2.0])
    assert bt._post_peak_months(q) == 2
    assert bt._post_peak_months(np.array([])) == 0


def test_sample_subjects_deterministic_and_capped():
    eligible = [{"well_api": f"API{i:03d}", "formation": "F1"} for i in range(50)]
    a = bt.sample_subjects(eligible, 10)
    b = bt.sample_subjects(list(reversed(eligible)), 10)
    assert [w["well_api"] for w in a] == [w["well_api"] for w in b]
    assert len(a) == 10


# ── b sourcing ───────────────────────────────────────────────────────────────

def test_late_segment_b_recovers_true_b_and_guards_short():
    true = _curve(b=0.8)
    q = np.asarray(_series(true, 48))
    b = bt._late_segment_b(q, "oil")
    assert b is not None and abs(b - 0.8) <= 0.051
    assert bt._late_segment_b(np.asarray(_series(true, 20)), "oil") is None


def test_production_variant_matches_engine_function():
    analogs = {f"A{i}": _prod(_curve(b=0.7 + 0.1 * i), 36) for i in range(3)}
    tcs = bt.build_type_curves(analogs, "production")
    from server.valuation.orchestrator import _build_type_curve_with_stats
    oil_tc, n_fit, _, b_meta = _build_type_curve_with_stats(analogs, "oil")
    assert tcs["oil"].b == oil_tc.b and tcs["oil"].qi_peak == oil_tc.qi_peak
    assert tcs["b_meta"]["n_fit_oil"] == n_fit == 3
    assert tcs["b_meta"]["source"] == b_meta["source"]


def test_legacy_variant_is_ungated_and_always_borrows():
    """legacy = pre-2026-07 behavior: cohort b is the ungated free median, and a
    long-history subject still borrows it instead of fitting its own."""
    young = {f"Y{i}": _prod(_curve(b=1.8, qi=15000), 10) for i in range(3)}
    legacy = bt.build_type_curves(young, "legacy")
    prod_v = bt.build_type_curves(young, "production")
    assert legacy["b_meta"]["source"].startswith("legacy_ungated_median")
    assert prod_v["b_meta"]["source"] == "default_no_mature_analogs"
    assert prod_v["oil"].b == 0.8                   # gated fallback
    assert legacy["oil"].b != prod_v["oil"].b       # ungated median ≠ default

    subject = _prod(_curve(b=0.9), 40)              # ≥30 post-peak
    months, q = subject["months"], np.asarray(subject["oil_bbl"])
    gas = np.asarray(subject["gas_mcf"])
    c_prod, _, strat_prod = bt.forecast_oil_curve(months, q, gas, prod_v, "production")
    c_leg, _, strat_leg = bt.forecast_oil_curve(months, q, gas, legacy, "legacy")
    assert strat_prod == "history_own_b" and abs(c_prod.b - 0.9) <= 0.051
    assert strat_leg == "history" and c_leg.b == legacy["oil"].b


def test_pick_analogs_skips_partial_coverage_series():
    """An analog whose loaded series starts long after its first_prod_date is a
    mid-life fragment and must not enter the cohort."""
    good = _prod(_curve(), 36)
    partial = _prod(_curve(), 36)                      # months start 2020-01
    candidates = [
        {"well_api": "GOOD", "lateral_length_ft": 10000, "first_prod_date": "2020-01-15"},
        {"well_api": "PARTIAL", "lateral_length_ft": 10000, "first_prod_date": "2015-01-15"},
    ]
    picked = bt.pick_analogs(candidates, {"GOOD": good, "PARTIAL": partial},
                             10000, good["months"][-1])
    assert "GOOD" in picked and "PARTIAL" not in picked


# ── placement / scoring ──────────────────────────────────────────────────────

def test_perfect_curve_scores_zero_error():
    """A subject whose future exactly follows its curve must score ~0 on every
    metric — this pins the anchor month, peak offset, and off-by-one handling."""
    curve = _curve(b=0.9)
    n_total, t_m = 48, 24
    oil_full = _series(curve, n_total)
    months_t = _months(n_total)[:t_m]
    scores = bt.score_forecast(curve, months_t, oil_full, t_m, holdout=24)
    assert scores is not None
    assert abs(scores["cum12_err"]) < 1e-9
    assert abs(scores["cum24_err"]) < 1e-9
    assert abs(scores["pv10_err"]) < 1e-9
    assert scores["holdout_n"] == 24


def test_score_respects_available_holdout_and_zero_actuals():
    curve = _curve()
    oil_full = _series(curve, 30)
    months_t = _months(30)[:24]
    scores = bt.score_forecast(curve, months_t, oil_full, 24, holdout=24)
    assert scores is None or scores["holdout_n"] == 6  # <12 holdout → None
    assert bt.score_forecast(curve, months_t, oil_full[:24] + [0.0] * 24, 24, 24)["cum12_err"] is None


def test_summarize_groups_and_aggregates():
    rows = [
        {"t_months": 12, "variant": "baseline", "classification": "history",
         "cum12_err": 0.10, "cum24_err": 0.20, "pv10_err": 0.15},
        {"t_months": 12, "variant": "baseline", "classification": "history",
         "cum12_err": -0.10, "cum24_err": None, "pv10_err": 0.05},
    ]
    s = bt.summarize(rows)
    grp = s["12 | baseline"]
    assert grp["cum12_err"]["n"] == 2
    assert grp["cum12_err"]["median"] == 0.0
    assert grp["cum12_err"]["mae"] == 0.1
    assert grp["cum24_err"]["n"] == 1
    txt = bt.format_table(s, "t")
    assert "12 | baseline" in txt


# ── db smoke test ────────────────────────────────────────────────────────────

@pytest.mark.db
def test_backtest_end_to_end_one_subject():
    """Full path on one real well: picker → type curves → routing → scoring.
    Tolerant of data quirks — asserts the machinery, not the data."""
    from utils.db import query
    from server.valuation.wells import bulk_load_production

    # Anchor on actual production presence (an early prod row), not
    # wells.first_prod_date — some wells have partial loaded coverage.
    subjects = query(
        """
        SELECT w.well_api, w.formation, w.basin, w.county, w.lateral_length_ft
        FROM public.production p
        JOIN public.wells w ON w.well_api = p.well_api
        WHERE p.prod_date = DATE '2020-06-01'
          AND w.well_status = 'PRODUCING' AND w.formation = 'MIDDLE BAKKEN'
          AND w.lateral_length_ft IS NOT NULL
          AND w.first_prod_date >= DATE '2020-01-01'
        ORDER BY w.well_api
        LIMIT 5
        """,
        statement_timeout_ms=60_000,
    )
    assert subjects, "no candidate subjects in DB"
    for subj in subjects:
        api = subj["well_api"]
        prod = bulk_load_production([api])[api]
        if len(prod["months"]) < 36:
            continue
        t_m = 24
        months_t = prod["months"][:t_m]
        q_oil = np.asarray(prod["oil_bbl"][:t_m], dtype=float)
        if q_oil.sum() <= 0:
            continue
        candidates = bt.candidate_analogs(subj)
        cand_prod = bulk_load_production([c["well_api"] for c in candidates])
        analogs = bt.pick_analogs(candidates, cand_prod,
                                  subj.get("lateral_length_ft"), months_t[-1])
        tcs = bt.build_type_curves(analogs, "production")
        curve, _state, strategy = bt.forecast_oil_curve(
            months_t, q_oil, np.asarray(prod["gas_mcf"][:t_m]), tcs, "production")
        scores = bt.score_forecast(curve, months_t,
                                   [float(v) for v in prod["oil_bbl"]], t_m, 24)
        if scores is not None:
            assert all(v is None or math.isfinite(v)
                       for k, v in scores.items() if k.endswith("_err"))
            return  # one fully-scored subject is enough
    pytest.skip("no scorable subject among the first 5 candidates")
