"""server/docs.py + the get_doc tool — connector-served CrudeDocs."""

import json

import pytest

import server.mcp_server as srv
from server import docs


_CATALOG = [
    {"slug": "crude-code-intro", "title": "Intro to CrudeCode", "description": "The product."},
    {"slug": "release-notes", "title": "What's new in CrudeCode", "description": "State of the product."},
]

_DOC = {
    "slug": "release-notes",
    "title": "What's new in CrudeCode",
    "description": "State of the product.",
    "type": "release",
    "rev": 3,
    "body_md": "# CrudeDoc: What's new\n\nRun the session.",
}


class FakeDB:
    """Scripted _query: catalog SELECTs return the index, slug SELECTs the doc."""

    def __init__(self, known_slugs=("release-notes",)):
        self.calls = []
        self.known_slugs = known_slugs

    def __call__(self, sql, params=None):
        self.calls.append((sql, params))
        s = sql.strip().upper()
        assert s.startswith("SELECT"), f"get_doc must only ever read: {sql}"
        if params is None:
            return [dict(r) for r in _CATALOG]
        return [dict(_DOC)] if params[0] in self.known_slugs else []


@pytest.fixture
def db(monkeypatch):
    fake = FakeDB()
    monkeypatch.setattr(docs._platform, "_query", fake)
    return fake


def test_list_docs_is_live_only_in_index_order(db):
    assert docs.list_docs() == _CATALOG
    sql = db.calls[0][0]
    assert "status = 'live'" in sql
    assert "ORDER BY sort_order" in sql


def test_load_doc_returns_row_with_body(db):
    doc = docs.load_doc("release-notes")
    assert doc == _DOC
    sql, params = db.calls[0]
    # Unlisted loads too — the live-test lane, mirroring /docs/<slug>.
    assert "IN ('live', 'unlisted')" in sql
    assert params == ["release-notes"]


def test_load_doc_unknown_slug_is_none(db):
    assert docs.load_doc("nope") is None


def test_tool_returns_doc_json(db):
    out = json.loads(srv.get_doc("release-notes"))
    assert out["slug"] == "release-notes"
    assert out["body_md"].startswith("# CrudeDoc")


def test_tool_no_slug_returns_catalog(db):
    out = json.loads(srv.get_doc())
    assert out == {"available_docs": _CATALOG}


def test_tool_unknown_slug_returns_error_plus_catalog(db):
    out = json.loads(srv.get_doc("nope"))
    assert "no doc named 'nope'" in out["error"]
    assert out["available_docs"] == _CATALOG


def test_tool_db_failure_is_a_typed_error(monkeypatch):
    def boom(sql, params=None):
        raise RuntimeError("db down")

    monkeypatch.setattr(docs._platform, "_query", boom)
    out = json.loads(srv.get_doc("release-notes"))
    assert out == {"error": "db down"}
