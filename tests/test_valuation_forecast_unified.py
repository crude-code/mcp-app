# tests/test_valuation_forecast_unified.py
import numpy as np
import pytest
import server.valuation.orchestrator as orch
from server.valuation.orchestrator import forecast_wells_for_run, AnalogsRequired
from server.valuation.types import WellMeta


class _FakeStore:
    def __init__(self): self.stages = {}
    def new_run(self, *, user_id, case_file): return "run-1"
    def write_stage(self, run_id, *, stage, payload): self.stages[stage] = payload
    def read_stage(self, run_id, *, stage): return self.stages.get(stage)


def _meta(api, status):
    # WellMeta field order/required-ness verified against server/valuation/types.py:
    # api, status, basin, formation, county, lateral_ft, spud_date, completion_date,
    # first_prod_date, last_prod_date, n_history_months, planned_first_prod_date;
    # geom_wkt + operator have defaults. There is NO well_name field.
    return WellMeta(api=api, status=status, basin="PRB", formation="NIOBRARA B",
                    county="CAMPBELL", lateral_ft=12000.0, spud_date=None,
                    completion_date=None, first_prod_date=None, last_prod_date=None,
                    n_history_months=0, planned_first_prod_date=None)


def _patch(monkeypatch, metas, prod):
    monkeypatch.setattr(orch, "ValuationRunStore", lambda: _FakeStore())
    monkeypatch.setattr(orch, "bulk_load_wells", lambda apis: [metas[a] for a in apis if a in metas])
    monkeypatch.setattr(orch, "bulk_load_production", lambda apis: {a: prod.get(a, {"months": [], "oil_bbl": [], "gas_mcf": []}) for a in apis})


def test_bounce_when_group_needs_analogs_and_has_none(monkeypatch):
    metas = {"P1": _meta("P1", "PERMITTED")}
    _patch(monkeypatch, metas, prod={})           # PUD, no production -> needs analogs
    with pytest.raises(AnalogsRequired) as exc_info:
        forecast_wells_for_run(run_id=None, groups=[{"area": "A", "wells": ["P1"], "analogs": []}])
    assert exc_info.value.needs_analogs == [{"area": "A", "wells": ["P1"]}]


def test_history_only_group_does_not_bounce(monkeypatch):
    months = [f"2020-{i:02d}" for i in range(1, 13)]
    q = [5, 80, 70, 60, 50, 44, 40, 36, 33, 30, 28, 26]
    metas = {"H1": _meta("H1", "PRODUCING")}
    _patch(monkeypatch, metas, prod={"H1": {"months": months, "oil_bbl": q, "gas_mcf": q}})
    out = forecast_wells_for_run(run_id=None, groups=[{"area": "A", "wells": ["H1"], "analogs": []}])
    grp = out["groups"][0]
    assert grp["spectrum"]["history"] == 1
    assert grp["by_status"]["PDP"][0]["api"] == "H1"


def test_permitted_with_analogs_forecasts_pure_analog(monkeypatch):
    am = [f"2020-{i:02d}" for i in range(1, 13)]
    aq = [5, 90, 80, 70, 60, 52, 46, 41, 37, 34, 31, 28]
    metas = {"PUD1": _meta("PUD1", "PERMITTED"), "AN1": _meta("AN1", "PRODUCING")}
    _patch(monkeypatch, metas, prod={"AN1": {"months": am, "oil_bbl": aq, "gas_mcf": aq}})
    out = forecast_wells_for_run(run_id=None,
        groups=[{"area": "A", "wells": ["PUD1"], "analogs": ["AN1"]}])
    grp = out["groups"][0]
    assert grp["spectrum"]["no_history"] == 1
    assert grp["by_status"]["PUD"][0]["strategy"] == "pure_analog"
    assert grp["analogs_used"]["n_fit"] == 1


def test_producing_well_continues_decline_not_restart_at_peak(monkeypatch):
    """A HISTORY producer with a past peak must continue its decline from the
    anchor month, not restart at qi_peak. Bug: peak_offset==0 causes the first
    forecast month to be ~qi_peak (~900) instead of ~last-history rate (~494)."""
    months = [f"2024-{m:02d}" for m in range(1, 13)]
    # Peak ~900 at index 1, declining exponentially to ~494 by the last month.
    oil = [300.0] + list(900.0 * np.exp(-0.06 * np.arange(11)))
    metas = {"H": _meta("H", "PRODUCING")}
    store = _FakeStore()
    monkeypatch.setattr(orch, "ValuationRunStore", lambda: store)
    monkeypatch.setattr(orch, "bulk_load_wells", lambda apis: [metas[a] for a in apis if a in metas])
    monkeypatch.setattr(orch, "bulk_load_production", lambda apis: {
        a: {"months": months, "oil_bbl": oil, "gas_mcf": oil} for a in apis if a in {"H"}
    } | {a: {"months": [], "oil_bbl": [], "gas_mcf": []} for a in apis if a not in {"H"}})

    out = forecast_wells_for_run(run_id=None, groups=[{"area": "A", "wells": ["H"], "analogs": []}])
    from datetime import date
    fcs, _cls, _st = orch._load_forecast_stage(
        forecast=store.read_stage(out["run_id"], stage="forecast"),
        as_of=date(2026, 7, 1), months_override=None)
    fc = orch._deserialize_forecast(fcs["H"]["oil"])
    from server.valuation.forecast import project
    _mo, rates = project(fc, horizon_months=3)
    # First forecast month must continue the decline (~last history rate ~494),
    # NOT jump back to qi_peak (~900). Threshold 600 is safely between both.
    assert rates[0] < 600, f"forecast restarted near peak: rates[0]={rates[0]:.1f} (expected < 600)"


def test_per_stream_analog_need_bounces_cleanly(monkeypatch):
    """An oil-HISTORY well whose GAS stream is CLIMBING (rising GOR — gas max in
    the last month) must produce the clean analogs_required bounce when the
    group has no analogs, not a raw AnalogRequired escaping as {"error":"gas"}."""
    months = [f"2020-{i:02d}" for i in range(1, 13)]
    oil = [5, 80, 70, 60, 50, 44, 40, 36, 33, 30, 28, 26]        # HISTORY
    gas = [10, 20, 30, 40, 50, 60, 70, 80, 90, 100, 110, 120]    # CLIMBING
    metas = {"H1": _meta("H1", "PRODUCING")}
    _patch(monkeypatch, metas, prod={"H1": {"months": months, "oil_bbl": oil, "gas_mcf": gas}})
    with pytest.raises(AnalogsRequired) as exc_info:
        forecast_wells_for_run(run_id=None, groups=[{"area": "A", "wells": ["H1"], "analogs": []}])
    assert exc_info.value.needs_analogs == [{"area": "A", "wells": ["H1"]}]


def test_per_stream_need_satisfied_by_analogs(monkeypatch):
    """Same rising-GOR well forecasts fine once the group carries analogs."""
    months = [f"2020-{i:02d}" for i in range(1, 13)]
    oil = [5, 80, 70, 60, 50, 44, 40, 36, 33, 30, 28, 26]
    gas = [10, 20, 30, 40, 50, 60, 70, 80, 90, 100, 110, 120]
    am = [f"2019-{i:02d}" for i in range(1, 13)]
    aq = [5, 90, 80, 70, 60, 52, 46, 41, 37, 34, 31, 28]
    metas = {"H1": _meta("H1", "PRODUCING"), "AN1": _meta("AN1", "PRODUCING")}
    _patch(monkeypatch, metas, prod={
        "H1": {"months": months, "oil_bbl": oil, "gas_mcf": gas},
        "AN1": {"months": am, "oil_bbl": aq, "gas_mcf": aq},
    })
    out = forecast_wells_for_run(run_id=None,
        groups=[{"area": "A", "wells": ["H1"], "analogs": ["AN1"]}])
    grp = out["groups"][0]
    assert grp["by_status"]["PDP"][0]["api"] == "H1"
    assert "cohort_b" in grp["analogs_used"]


# ── gated cohort b (_build_type_curve_with_stats) ────────────────────────────

def _hyp_series(b, n, qi=900.0, di=0.08):
    t = np.arange(n, dtype=float)
    q = qi / np.power(1.0 + b * di * t, 1.0 / b)
    return {"months": [f"m{i}" for i in range(n)],
            "oil_bbl": list(q), "gas_mcf": list(q)}


def test_type_curve_b_gated_to_mature_analogs():
    from server.valuation.orchestrator import _build_type_curve_with_stats
    prod = {"M1": _hyp_series(0.9, 40), "M2": _hyp_series(0.9, 40),
            "Y1": _hyp_series(1.8, 10), "Y2": _hyp_series(1.8, 10)}
    curve, n_fit, n_skipped, b_meta = _build_type_curve_with_stats(prod, "oil")
    assert n_fit == 4 and n_skipped == 0
    assert b_meta["n_mature"] == 2
    assert b_meta["source"] == "gated_median(n=2)"
    assert abs(curve.b - 0.9) <= 0.05          # young 1.8s excluded from b


def test_type_curve_b_falls_back_when_cohort_all_young():
    from server.valuation.orchestrator import _build_type_curve_with_stats
    prod = {"Y1": _hyp_series(1.8, 10), "Y2": _hyp_series(1.6, 10)}
    curve, n_fit, _, b_meta = _build_type_curve_with_stats(prod, "oil")
    assert n_fit == 2
    assert b_meta["source"] == "default_no_mature_analogs"
    assert curve.b == 0.8


def test_type_curve_b_clamped():
    from server.valuation.orchestrator import _build_type_curve_with_stats
    prod = {"M1": _hyp_series(1.8, 40), "M2": _hyp_series(1.8, 40)}
    curve, _, _, b_meta = _build_type_curve_with_stats(prod, "oil")
    assert curve.b == 1.3                      # gated median ~1.8 → clamp ceiling
    assert b_meta["b"] == 1.3


@pytest.mark.db  # run_valuation_for_run loads the strip curve from the DB
def test_forecast_then_run_valuation_round_trip(monkeypatch):
    months = [f"2020-{i:02d}" for i in range(1, 13)]
    q = [5, 80, 70, 60, 50, 44, 40, 36, 33, 30, 28, 26]
    metas = {"H1": _meta("H1", "PRODUCING"), "PUD1": _meta("PUD1", "PUD"), "AN1": _meta("AN1", "PRODUCING")}
    prod = {"H1": {"months": months, "oil_bbl": q, "gas_mcf": q},
            "AN1": {"months": months, "oil_bbl": q, "gas_mcf": q}}
    store = _FakeStore()
    monkeypatch.setattr(orch, "ValuationRunStore", lambda: store)
    monkeypatch.setattr(orch, "bulk_load_wells", lambda apis: [metas[a] for a in apis if a in metas])
    monkeypatch.setattr(orch, "bulk_load_production", lambda apis: {a: prod.get(a, {"months": [], "oil_bbl": [], "gas_mcf": []}) for a in apis})

    out = forecast_wells_for_run(run_id=None,
        groups=[{"area": "A", "wells": ["H1", "PUD1"], "analogs": ["AN1"]}])
    res = orch.run_valuation_for_run(run_id=out["run_id"], params={
        "interest_type": "minerals", "interest": {"decimal": 0.05},
        "asset_list": {"well_apis": ["H1", "PUD1"]}, "economics_overrides": {}})
    assert "total" in res["npv_at_centers"]
