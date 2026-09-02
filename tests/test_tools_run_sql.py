import json

from server import mcp_server


def test_run_sql_rejects_without_identity(no_identity):
    out = json.loads(mcp_server.run_sql(sql="SELECT 1"))
    assert "error" in out
    assert "ident" in out["error"].lower()


def test_run_sql_rejects_empty_sql(identity):
    out = json.loads(mcp_server.run_sql(sql=""))
    assert "error" in out
    assert "sql is required" in out["error"]


def test_run_sql_rejects_ddl(identity, monkeypatch):
    # run_guarded should reject before hitting the DB.
    out = json.loads(mcp_server.run_sql(sql="DROP TABLE wells"))
    assert "error" in out


def test_run_sql_rejects_blocked_schema(identity, monkeypatch):
    out = json.loads(
        mcp_server.run_sql(sql="SELECT * FROM pg_catalog.pg_class LIMIT 1")
    )
    assert "error" in out


def test_run_sql_returns_rows_on_happy_path(identity, monkeypatch):
    fake_result = {"rows": [{"n": 1}], "count": 1}
    monkeypatch.setattr(mcp_server, "run_guarded", lambda *a, **kw: fake_result)
    out = json.loads(mcp_server.run_sql(sql="SELECT 1 AS n"))
    assert out == {"rows": [{"n": 1}], "count": 1}


def test_run_sql_passes_200_row_cap(identity, monkeypatch):
    captured = {}

    def fake_run_guarded(sql, **kwargs):
        captured.update(kwargs)
        return {"rows": [], "count": 0}

    monkeypatch.setattr(mcp_server, "run_guarded", fake_run_guarded)
    mcp_server.run_sql(sql="SELECT 1")
    assert captured["row_cap"] == 200
    assert captured["size_cap_bytes"] == 100_000
    # Schema scope = exploration (wider than map-layer hydration).
    from utils.schemas import EXPLORATION_SCHEMAS
    assert captured["allowed_schemas"] == EXPLORATION_SCHEMAS


def test_run_sql_default_schema_is_public(identity, monkeypatch):
    captured = {}

    def fake_run_guarded(sql, schema=None, **kwargs):
        captured["schema"] = schema
        return {"rows": [], "count": 0}

    monkeypatch.setattr(mcp_server, "run_guarded", fake_run_guarded)
    mcp_server.run_sql(sql="SELECT 1")
    assert captured["schema"] == "public"


def test_run_sql_schema_param_threads_through(identity, monkeypatch):
    captured = {}

    def fake_run_guarded(sql, schema=None, **kwargs):
        captured["schema"] = schema
        return {"rows": [], "count": 0}

    monkeypatch.setattr(mcp_server, "run_guarded", fake_run_guarded)
    mcp_server.run_sql(sql="SELECT 1", schema="financials")
    assert captured["schema"] == "financials"
