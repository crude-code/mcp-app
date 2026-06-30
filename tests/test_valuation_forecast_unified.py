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
    with pytest.raises(AnalogsRequired) as ei:
        forecast_wells_for_run(run_id=None, groups=[{"area": "A", "wells": ["P1"], "analogs": []}])
    assert ei.value.needs_analogs == [{"area": "A", "wells": ["P1"]}]


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
    assert res["briefing_spec_written"] is True
    assert "total" in res["npv_at_centers"]
