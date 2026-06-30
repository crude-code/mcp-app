# tests/test_agent_results_store.py
"""AgentResultStore: durable, user-scoped per-run renderable spec.

DB-free — utils.agent_results._query is monkeypatched with a recorder so we
test the store's SQL/param contract and parsing without a live Postgres.
"""
import json

import pytest

from utils import agent_results as ar
from utils.agent_results import AgentResultStore


@pytest.fixture
def calls(monkeypatch):
    """Record every _query(sql, params=...) call; return canned rows."""
    recorded = []
    canned = {"rows": []}

    def fake_query(sql, params=None):
        recorded.append({"sql": sql, "params": params})
        return canned["rows"]

    monkeypatch.setattr(ar, "_query", fake_query)
    return recorded, canned


def test_save_upserts_with_all_columns(calls):
    recorded, _ = calls
    store = AgentResultStore()
    spec = {"kind": "briefing", "headline": "X"}
    store.save(run_id="run-1", agent_type="data_analyst", user_id=9999, spec=spec)

    assert len(recorded) == 1
    sql = recorded[0]["sql"]
    params = recorded[0]["params"]
    assert "agent_results" in sql
    assert "ON CONFLICT" in sql            # re-run overwrites
    assert params[0] == "run-1"
    assert params[1] == 9999
    assert params[2] == "data_analyst"
    assert json.loads(params[3]) == spec   # spec serialized to JSON


def test_get_returns_parsed_spec_scoped_to_user(calls):
    recorded, canned = calls
    canned["rows"] = [{"spec": {"kind": "briefing", "headline": "X"}}]
    store = AgentResultStore()
    out = store.get(run_id="run-1", user_id=9999)

    assert out == {"kind": "briefing", "headline": "X"}
    # user scoping: both run_id and user_id are in the WHERE params
    assert recorded[0]["params"] == ["run-1", 9999]


def test_get_parses_json_string_payload(calls):
    """psycopg sometimes hands back jsonb as text — store must json.loads it."""
    _, canned = calls
    canned["rows"] = [{"spec": json.dumps({"kind": "briefing"})}]
    store = AgentResultStore()
    out = store.get(run_id="run-1", user_id=9999)
    assert out == {"kind": "briefing"}


def test_get_missing_returns_none(calls):
    _, canned = calls
    canned["rows"] = []
    store = AgentResultStore()
    assert store.get(run_id="nope", user_id=9999) is None
