import json
import pytest

from server import mcp_server


@pytest.fixture
def patched_identity(monkeypatch):
    monkeypatch.setattr(
        mcp_server,
        "get_current_identity",
        lambda: {"user_slug": "test-slug", "user_id": "test-user"},
    )


@pytest.fixture
def no_identity(monkeypatch):
    monkeypatch.setattr(mcp_server, "get_current_identity", lambda: None)


def test_run_sql_rejects_without_identity(no_identity):
    out = json.loads(mcp_server.run_sql(sql="SELECT 1"))
    assert "error" in out
    assert "ident" in out["error"].lower()


def test_run_sql_rejects_empty_sql(patched_identity):
    out = json.loads(mcp_server.run_sql(sql=""))
    assert "error" in out
    assert "sql is required" in out["error"]


def test_run_sql_rejects_ddl(patched_identity, monkeypatch):
    # run_guarded should reject before hitting the DB.
    out = json.loads(mcp_server.run_sql(sql="DROP TABLE wells"))
    assert "error" in out


def test_run_sql_rejects_blocked_schema(patched_identity, monkeypatch):
    out = json.loads(
        mcp_server.run_sql(sql="SELECT * FROM pg_catalog.pg_class LIMIT 1")
    )
    assert "error" in out


def test_run_sql_returns_rows_on_happy_path(patched_identity, monkeypatch):
    fake_result = {"rows": [{"n": 1}], "count": 1}
    monkeypatch.setattr(mcp_server, "run_guarded", lambda *a, **kw: fake_result)
    out = json.loads(mcp_server.run_sql(sql="SELECT 1 AS n"))
    assert out == {"rows": [{"n": 1}], "count": 1}


def test_run_sql_passes_50_row_cap(patched_identity, monkeypatch):
    captured = {}

    def fake_run_guarded(sql, **kwargs):
        captured.update(kwargs)
        return {"rows": [], "count": 0}

    monkeypatch.setattr(mcp_server, "run_guarded", fake_run_guarded)
    mcp_server.run_sql(sql="SELECT 1")
    assert captured["row_cap"] == 50
    assert captured["size_cap_bytes"] == 50_000
    # Schema scope = exploration (wider than widget hydration).
    from utils.schemas import EXPLORATION_SCHEMAS
    assert captured["allowed_schemas"] == EXPLORATION_SCHEMAS


def test_run_sql_default_schema_is_public(patched_identity, monkeypatch):
    captured = {}

    def fake_run_guarded(sql, schema=None, **kwargs):
        captured["schema"] = schema
        return {"rows": [], "count": 0}

    monkeypatch.setattr(mcp_server, "run_guarded", fake_run_guarded)
    mcp_server.run_sql(sql="SELECT 1")
    assert captured["schema"] == "public"


def test_run_sql_schema_param_threads_through(patched_identity, monkeypatch):
    captured = {}

    def fake_run_guarded(sql, schema=None, **kwargs):
        captured["schema"] = schema
        return {"rows": [], "count": 0}

    monkeypatch.setattr(mcp_server, "run_guarded", fake_run_guarded)
    mcp_server.run_sql(sql="SELECT 1", schema="financials")
    assert captured["schema"] == "financials"
