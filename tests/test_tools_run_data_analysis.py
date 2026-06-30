import json

import server.mcp_server as srv


def _spec():
    return {
        "kind": "briefing",
        "headline": "Permian gas takeaway tightens",
        "tldr": "Three plants at capacity through Q3.",
        "sections": [{
            "label": "Summary",
            "layout": "full-width",
            "widgets": [{"type": "commentary", "text": "Capacity is binding."}],
        }],
    }


def test_run_data_analysis_happy_path(monkeypatch):
    monkeypatch.setattr(srv, "get_current_identity",
                        lambda: {"user_slug": "acme", "user_id": 7})
    monkeypatch.setattr(srv, "validate_widget_queries", lambda spec: [])
    # hydrate is identity here — the real one re-runs SQL we don't have a DB for.
    monkeypatch.setattr(srv, "hydrate_spec", lambda spec: spec)
    minted = {}
    monkeypatch.setattr(srv._briefing_handles, "mint",
                        lambda *, user_slug, spec: minted.setdefault("tok", "tok-1"))
    saved = {}
    monkeypatch.setattr(srv._agent_results, "save",
                        lambda **kw: saved.update(kw))

    out = json.loads(srv.run_data_analysis(spec=_spec()))

    assert out["surface"] == "briefing"
    assert out["briefing_token"] == "tok-1"
    assert out["headline"] == "Permian gas takeaway tightens"
    assert out["kind"] == "briefing"
    # durable result persisted under a minted run_id
    assert saved["agent_type"] == "data_analyst"
    assert saved["user_id"] == 7


def test_run_data_analysis_shape_error_returns_in_turn(monkeypatch):
    monkeypatch.setattr(srv, "get_current_identity",
                        lambda: {"user_slug": "acme", "user_id": 7})
    bad = _spec()
    del bad["headline"]
    out = json.loads(srv.run_data_analysis(spec=bad))
    assert out["error"] == "invalid spec"
    assert "headline" in out["details"]


def test_run_data_analysis_widget_query_error_returns_in_turn(monkeypatch):
    monkeypatch.setattr(srv, "get_current_identity",
                        lambda: {"user_slug": "acme", "user_id": 7})
    monkeypatch.setattr(srv, "validate_widget_queries",
                        lambda spec: [{"label": "trend", "error": "no such column: prod"}])
    spec = _spec()
    spec["sections"][0]["widgets"] = [
        {"type": "table", "columns": [{"key": "a", "label": "A"}],
         "query": "SELECT 1 AS a"},
    ]
    out = json.loads(srv.run_data_analysis(spec=spec))
    assert out["error"] == "widget query validation failed"
    assert out["widgets"][0]["error"].startswith("no such column")


def test_run_data_analysis_rejects_non_briefing_kind(monkeypatch):
    monkeypatch.setattr(srv, "get_current_identity",
                        lambda: {"user_slug": "acme", "user_id": 7})
    out = json.loads(srv.run_data_analysis(spec={"kind": "error", "reason": "x"}))
    assert out["error"] == "invalid spec"
