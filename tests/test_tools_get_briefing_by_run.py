# tests/test_tools_get_briefing_by_run.py
"""get_briefing_by_run: app-only, NON-blocking durable read by run_id.

Twin of get_briefing_full, but sources the spec from platform.agent_results
(durable, survives restart) instead of the in-memory handle keyed by token.
DB-free — the store's .get is monkeypatched.
"""
import json

import pytest

from server import mcp_server
from server.mcp_server import get_briefing_by_run


@pytest.fixture
def fake_id(monkeypatch, fake_identity):
    monkeypatch.setattr(mcp_server, "get_current_identity", lambda: fake_identity)
    return fake_identity


def test_returns_durable_spec(fake_id, monkeypatch):
    spec = {"kind": "briefing", "headline": "durable"}

    def fake_get(*, run_id, user_id):
        assert run_id == "run-1"
        assert user_id == fake_id["user_id"]
        return spec

    monkeypatch.setattr(mcp_server._agent_results, "get", fake_get)

    parsed = json.loads(get_briefing_by_run(run_id="run-1"))
    assert parsed["spec"]["headline"] == "durable"


def test_not_found_errors(fake_id, monkeypatch):
    monkeypatch.setattr(mcp_server._agent_results, "get", lambda **kw: None)
    parsed = json.loads(get_briefing_by_run(run_id="missing"))
    assert "error" in parsed


def test_no_identity_errors(monkeypatch):
    monkeypatch.setattr(mcp_server, "get_current_identity", lambda: None)
    parsed = json.loads(get_briefing_by_run(run_id="run-1"))
    assert "error" in parsed


def test_wrong_user_gets_nothing(fake_id, monkeypatch):
    """Store scopes by user_id; a foreign run_id resolves to None -> error."""
    seen = {}

    def fake_get(*, run_id, user_id):
        seen["user_id"] = user_id
        return None                       # store found nothing for this user

    monkeypatch.setattr(mcp_server._agent_results, "get", fake_get)
    parsed = json.loads(get_briefing_by_run(run_id="someone-elses-run"))
    assert "error" in parsed
    assert seen["user_id"] == fake_id["user_id"]


def test_store_exception_returns_lookup_failed(fake_id, monkeypatch):
    """A store-level failure (e.g. DB down) is caught, logged, and surfaced as
    a generic error rather than crashing the renderer."""
    def fake_get_raises(*, run_id, user_id):
        raise RuntimeError("simulated DB error")

    monkeypatch.setattr(mcp_server._agent_results, "get", fake_get_raises)
    parsed = json.loads(get_briefing_by_run(run_id="run-1"))
    assert parsed["error"] == "lookup failed"
