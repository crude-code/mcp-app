import json
import pytest
import server.mcp_server as srv


# ---------------------------------------------------------------------------
# Identity-guard rejection tests — all three tools must return the canonical
# "Could not identify user" error when get_current_identity() returns None.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("call", [
    lambda: srv.forecast_wells(groups=[{"area": "A", "wells": ["x"], "analogs": []}]),
    lambda: srv.run_valuation(run_id="r", params={}),
])
def test_tool_rejects_none_identity(monkeypatch, call):
    monkeypatch.setattr(srv, "get_current_identity", lambda: None)
    out = json.loads(call())
    assert out == {"error": "Could not identify user"}


def test_forecast_wells_tool_returns_groups(monkeypatch):
    monkeypatch.setattr(srv, "get_current_identity", lambda: {"user_slug": "acme", "user_id": 7})
    monkeypatch.setattr(srv, "forecast_wells_for_run",
                        lambda **kw: {"run_id": "run-9", "groups": [{"area": "A"}]})
    out = json.loads(srv.forecast_wells(groups=[{"area": "A", "wells": ["x"], "analogs": []}]))
    assert out["run_id"] == "run-9"


def test_forecast_wells_tool_surfaces_bounce(monkeypatch):
    monkeypatch.setattr(srv, "get_current_identity", lambda: {"user_slug": "acme", "user_id": 7})
    def _boom(**kw):
        raise srv.AnalogsRequired([{"area": "A", "wells": ["x"]}])
    monkeypatch.setattr(srv, "forecast_wells_for_run", _boom)
    out = json.loads(srv.forecast_wells(groups=[{"area": "A", "wells": ["x"], "analogs": []}]))
    assert out["error"] == "analogs_required"
    assert out["needs_analogs"] == [{"area": "A", "wells": ["x"]}]


def test_run_valuation_tool_mints_token(monkeypatch):
    monkeypatch.setattr(srv, "get_current_identity",
                        lambda: {"user_slug": "acme", "user_id": 7})
    monkeypatch.setattr(srv, "run_valuation_for_run",
                        lambda **kw: {"run_id": "run-9",
                                      "npv_at_centers": {"total": 1234.0, "by_status": {}}})
    monkeypatch.setattr(srv._valuation_store, "read_stage",
                        lambda run_id, *, stage: {"layout": "deal_sheet"})
    monkeypatch.setattr(srv._briefing_handles, "mint",
                        lambda *, user_slug, spec: "tok-1")
    out = json.loads(srv.run_valuation(run_id="run-9", params={
        "interest_type": "minerals", "interest": {"decimal": 0.05},
        "asset_list": {"well_apis": ["42-000-1"]}, "economics_overrides": {}}))
    assert out["surface"] == "deal_sheet"
    assert out["briefing_token"] == "tok-1"
    assert out["npv_at_centers"]["total"] == 1234.0


