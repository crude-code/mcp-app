"""Advanced block is rebuilt from the single `forecast` stage."""
import numpy as np
import server.valuation.orchestrator as orch
from server.valuation.orchestrator import forecast_wells_for_run


class _Store:
    def __init__(self): self.stages = {}
    def new_run(self, **kw): return "run-adv"
    def write_stage(self, run_id, *, stage, payload): self.stages[stage] = payload
    def read_stage(self, run_id, *, stage): return self.stages.get(stage)


def _meta(api, status):
    return orch.WellMeta(api=api, status=status, basin="DELAWARE", formation="WC",
                         county="LOVING", lateral_ft=9500, n_history_months=24,
                         operator="ACME",
                         spud_date=None, completion_date=None, first_prod_date=None,
                         last_prod_date=None, planned_first_prod_date=None)


def _decline(n, qi=600.0):
    return list(qi * np.exp(-0.05 * np.arange(n)))


def test_forecast_stage_persists_actual_history(monkeypatch):
    store = _Store()
    monkeypatch.setattr(orch, "ValuationRunStore", lambda: store)
    monkeypatch.setattr(orch, "bulk_load_wells", lambda apis: [_meta(a, "PRODUCING") for a in apis])
    months = [f"2024-{m:02d}" for m in range(1, 13)]
    monkeypatch.setattr(orch, "bulk_load_production", lambda apis: {
        a: {"months": months, "oil_bbl": _decline(12, qi=900.0), "gas_mcf": _decline(12, qi=1800.0)}
        for a in apis})
    forecast_wells_for_run(run_id="run-adv",
                           groups=[{"area": "A", "wells": ["42-1"], "analogs": []}])
    ah = store.stages["forecast"]["actual_history"]
    assert ah["dates"] == months
    assert len(ah["oil"]) == 12 and len(ah["gas"]) == 12


def test_forecast_stage_persists_type_curve_and_analog_meta(monkeypatch):
    store = _Store()
    monkeypatch.setattr(orch, "ValuationRunStore", lambda: store)
    monkeypatch.setattr(orch, "bulk_load_wells", lambda apis: [_meta(a, "PERMITTED") for a in apis])
    analog_prod = {"months": list(range(24)),
                   "oil_bbl": list(np.linspace(1000, 200, 24)),
                   "gas_mcf": list(np.linspace(2000, 400, 24))}
    monkeypatch.setattr(orch, "bulk_load_production", lambda apis: {
        a: (analog_prod if a in ("42-A", "42-B") else {"months": [], "oil_bbl": [], "gas_mcf": []})
        for a in apis})
    forecast_wells_for_run(run_id="run-adv",
        groups=[{"area": "A", "wells": ["42-9"], "analogs": ["42-A", "42-B"]}])
    grp = store.stages["forecast"]["groups"][0]
    assert "type_curve" in grp and "oil" in grp["type_curve"] and "gas" in grp["type_curve"]
    assert grp["analog_meta"]["analog_apis"] == ["42-A", "42-B"]
    assert grp["analog_meta"]["n_fit"] == 2


def test_advanced_from_stages_builds_block(monkeypatch):
    store = _Store()
    monkeypatch.setattr(orch, "ValuationRunStore", lambda: store)
    monkeypatch.setattr(orch, "bulk_load_wells", lambda apis: [_meta(a, "PRODUCING") for a in apis])
    months = [f"2024-{m:02d}" for m in range(1, 13)]
    monkeypatch.setattr(orch, "bulk_load_production", lambda apis: {
        a: {"months": months, "oil_bbl": _decline(12, qi=900.0), "gas_mcf": _decline(12, qi=1800.0)}
        for a in apis})
    forecast_wells_for_run(run_id="run-adv",
                           groups=[{"area": "A", "wells": ["42-1"], "analogs": []}])
    well_meta = {"42-1": {"status": "PRODUCING", "operator": "ACME", "basin": "DELAWARE",
                          "formation": "WC", "lateral_ft": 9500}}
    adv = orch._advanced_from_stages(
        run_id="run-adv", store=store, well_meta=well_meta,
        inputs={"oil_price": 70.0, "gas_price": 3.0, "oil_diff": 0.0, "gas_diff": 0.0,
                "tax_pct": 0.0, "gpt_pct": 0.0, "horizon_months": 360},
        interest={"interest_type": "minerals", "decimal": 0.05},
        origin="2026-07-01")
    assert adv is not None
    assert "asset" in adv and "production" in adv and "econ" in adv
    pdp_est = next(e for e in adv["production"]["estimates"] if e["key"] == "pdp")
    assert any(p["actual"] for p in pdp_est["series"])  # real history present
