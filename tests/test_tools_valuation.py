import json
import pytest
import server.mcp_server as srv


# ---------------------------------------------------------------------------
# Identity-guard rejection tests — all three tools must return the canonical
# "Could not identify user" error when get_current_identity() returns None.
# ---------------------------------------------------------------------------

_ENTRY = {"wells": ["x"], "oil": {"qi": 100.0, "di": 0.05, "b": 0.9},
          "anchor_month": "2026-05", "rationale": "test"}


@pytest.mark.parametrize("call", [
    lambda: srv.forecast_wells(forecasts=[_ENTRY]),
    lambda: srv.run_valuation(run_id="r", params={}),
])
def test_tool_rejects_none_identity(monkeypatch, call):
    monkeypatch.setattr(srv, "get_current_identity", lambda: None)
    out = json.loads(call())
    assert out == {"error": "Could not identify user"}


def test_forecast_wells_tool_returns_echo(monkeypatch):
    monkeypatch.setattr(srv, "get_current_identity", lambda: {"user_slug": "acme", "user_id": 7})
    monkeypatch.setattr(srv, "forecast_wells_for_run",
                        lambda **kw: {"run_id": "run-9", "committed": [{"wells": ["x"]}],
                                      "wells_committed": 1, "wells_in_run": 1,
                                      "by_status": {"PDP": 1, "DUC": 0, "PUD": 0}})
    out = json.loads(srv.forecast_wells(forecasts=[_ENTRY]))
    assert out["run_id"] == "run-9"
    assert out["by_status"]["PDP"] == 1


def test_forecast_wells_tool_surfaces_validation_failure(monkeypatch):
    """A bounce lists every violation and says nothing was saved."""
    monkeypatch.setattr(srv, "get_current_identity", lambda: {"user_slug": "acme", "user_id": 7})
    def _boom(**kw):
        raise srv.ForecastValidationError([{"entry": 0, "field": "oil.b",
                                            "message": "b must be in [0.0, 2.0]; got 5.0"}])
    monkeypatch.setattr(srv, "forecast_wells_for_run", _boom)
    out = json.loads(srv.forecast_wells(forecasts=[_ENTRY]))
    assert out["error"] == "validation_failed"
    assert out["violations"][0]["field"] == "oil.b"
    assert "Nothing was saved" in out["message"]


def test_run_valuation_tool_returns_artifact_payload(monkeypatch):
    monkeypatch.setattr(srv, "get_current_identity",
                        lambda: {"user_slug": "acme", "user_id": 7})
    monkeypatch.setattr(srv, "run_valuation_for_run",
                        lambda **kw: {"run_id": "run-9",
                                      "npv_at_centers": {"total": 1234.0, "by_status": {}}})
    monkeypatch.setattr(srv, "compose_artifact_payload_for_run",
                        lambda run_id: {"facts": {"deal_type": "Minerals / Royalty"},
                                        "production": None,
                                        "economics": {"npv_at_centers": {"total": 1234.0, "by_status": {}}}})
    out = json.loads(srv.run_valuation(run_id="run-9", params={
        "interest_type": "minerals", "interest": {"decimal": 0.05},
        "asset_list": {"well_apis": ["42-000-1"]}, "economics_overrides": {}}))
    assert out["surface"] == "deal_sheet_artifact"
    assert out["run_id"] == "run-9"
    assert out["data"]["facts"]["deal_type"] == "Minerals / Royalty"
    assert out["data"]["economics"]["npv_at_centers"]["total"] == 1234.0
    # The frozen artifact template ships with every response.
    assert "export default function App" in out["viewer"]


def test_deal_sheet_viewer_is_artifact_safe():
    """The template must run in the claude.ai artifact sandbox: react/recharts
    only, no host APIs, no renderer CSS vars."""
    from server.valuation.artifact_payload import load_viewer
    jsx = load_viewer()
    assert "export default function App" in jsx
    assert "callServerTool" not in jsx     # no host-API leakage
    assert "var(--" not in jsx             # no CSS-var leakage


