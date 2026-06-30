"""get_briefing_full: renderer-only synchronous fetch that returns the FULL spec.

Plan-3: no async, no event buffer, no blocking wait. The handle store is
always populated by the time the token reaches Claude (run_data_analysis /
run_valuation mint and populate the token before returning).
"""
import json

import pytest

from server import mcp_server
from server.mcp_server import get_briefing_full


@pytest.fixture(autouse=True)
def reset_stores():
    mcp_server._briefing_handles = type(mcp_server._briefing_handles)(ttl_seconds=600.0)


@pytest.fixture
def fake_id(monkeypatch, fake_identity):
    monkeypatch.setattr(mcp_server, "get_current_identity", lambda: fake_identity)
    return fake_identity


def test_get_briefing_full_returns_full_spec(fake_id):
    """Unlike get_briefing (which strips widget payloads), get_briefing_full
    returns the spec verbatim so the renderer can render charts."""
    spec = {
        "kind": "briefing",
        "headline": "X",
        "sections": [{
            "label": "a", "layout": "full-width",
            "widgets": [{"type": "table", "rows": [{"a": 1}, {"a": 2}]}],
        }],
    }
    token = mcp_server._briefing_handles.mint(user_slug=fake_id["user_slug"], spec=spec)

    raw = get_briefing_full(token=token)
    parsed = json.loads(raw)
    # Full spec returned under `spec` key (NOT the flattened summary shape).
    assert parsed["spec"]["headline"] == "X"
    # Bulky payload (rows) is PRESERVED — that's the whole point.
    assert parsed["spec"]["sections"][0]["widgets"][0]["rows"] == [{"a": 1}, {"a": 2}]


def test_get_briefing_full_unknown_token_errors(fake_id):
    raw = get_briefing_full(token="nope")
    parsed = json.loads(raw)
    assert "error" in parsed


def test_get_briefing_full_wrong_user_errors(fake_id):
    """Slug binding still applies — renderer is per-user."""
    spec = {"kind": "briefing"}
    token = mcp_server._briefing_handles.mint(user_slug="someone-else", spec=spec)

    raw = get_briefing_full(token=token)
    parsed = json.loads(raw)
    assert "error" in parsed


def test_get_briefing_full_no_identity(monkeypatch):
    monkeypatch.setattr(mcp_server, "get_current_identity", lambda: None)
    raw = get_briefing_full(token="anything")
    parsed = json.loads(raw)
    assert "error" in parsed
