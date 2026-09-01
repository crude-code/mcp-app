"""server/cuts.py + the get_cut tool — connector-served Crude Cuts."""

import json

import pytest

import server.mcp_server as srv
from server import cuts


_CATALOG = [
    {"cut_no": 2, "slug": "horseshoe-premium", "tag": "analysis",
     "title": "The Horseshoe Premium", "dek": "U-turns vs straight offsets.", "as_of": "AUG 2026"},
    {"cut_no": 1, "slug": "greenlake-scraps", "tag": "analysis",
     "title": "The Scrap Drillers", "dek": "Three acts of scrap acreage.", "as_of": "JUL 2026"},
]

_CUT = {
    "cut_no": 1,
    "slug": "greenlake-scraps",
    "tag": "analysis",
    "title": "The Scrap Drillers",
    "dek": "Three acts of scrap acreage.",
    "as_of": "JUL 2026",
    "rev": 4,
    "recipe_md": "# Rebuild: The Scrap Drillers\n\nRun the steps.",
}


class FakeDB:
    """Scripted _query: catalog SELECTs return the index, ref SELECTs the cut."""

    def __init__(self, known=("greenlake-scraps", 1)):
        self.calls = []
        self.known = known

    def __call__(self, sql, params=None):
        self.calls.append((sql, params))
        s = sql.strip().upper()
        assert s.startswith("SELECT"), f"get_cut must only ever read: {sql}"
        if params is None:
            return [dict(r) for r in _CATALOG]
        return [dict(_CUT)] if params[0] in self.known else []


@pytest.fixture
def db(monkeypatch):
    fake = FakeDB()
    monkeypatch.setattr(cuts._platform, "_query", fake)
    return fake


def test_list_cuts_is_live_only_newest_first(db):
    assert cuts.list_cuts() == _CATALOG
    sql = db.calls[0][0]
    assert "status = 'live'" in sql
    assert "ORDER BY cut_no DESC" in sql


def test_load_cut_by_slug_returns_recipe_row(db):
    cut = cuts.load_cut("greenlake-scraps")
    assert cut == _CUT
    sql, params = db.calls[0]
    # Unlisted loads too — the eyeball lane, mirroring /cuts/<slug>.
    assert "IN ('live', 'unlisted')" in sql
    assert "slug = %s" in sql
    assert params == ["greenlake-scraps"]


@pytest.mark.parametrize("ref", ["1", "001", "№ 001", "#1", "  1  "])
def test_load_cut_by_number_in_any_dress(db, ref):
    cut = cuts.load_cut(ref)
    assert cut == _CUT
    sql, params = db.calls[0]
    assert "cut_no = %s" in sql
    assert params == [1]


def test_load_cut_unknown_ref_is_none(db):
    assert cuts.load_cut("nope") is None


def test_tool_returns_cut_json_with_url(db):
    out = json.loads(srv.get_cut("greenlake-scraps"))
    assert out["slug"] == "greenlake-scraps"
    assert out["recipe_md"].startswith("# Rebuild")
    assert out["url"] == "https://crudecode.dev/cuts/greenlake-scraps"


def test_tool_no_ref_returns_catalog(db):
    out = json.loads(srv.get_cut())
    assert out == {"available_cuts": _CATALOG}


def test_tool_unknown_ref_returns_error_plus_catalog(db):
    out = json.loads(srv.get_cut("nope"))
    assert "no cut 'nope'" in out["error"]
    assert out["available_cuts"] == _CATALOG


def test_tool_db_failure_is_a_typed_error(monkeypatch):
    def boom(sql, params=None):
        raise RuntimeError("db down")

    monkeypatch.setattr(cuts._platform, "_query", boom)
    out = json.loads(srv.get_cut("greenlake-scraps"))
    assert out == {"error": "db down"}


@pytest.mark.db
def test_live_table_serves_the_pilot_cut():
    """Against the real DB: № 001 exists, is addressable both ways, and
    carries a recipe (stored at publish time for exactly this tool)."""
    catalog = cuts.list_cuts()
    assert any(c["slug"] == "greenlake-scraps" for c in catalog)
    by_slug = cuts.load_cut("greenlake-scraps")
    by_no = cuts.load_cut("001")
    assert by_slug is not None and by_no is not None
    assert by_slug["cut_no"] == by_no["cut_no"] == 1
    assert (by_slug["recipe_md"] or "").strip()
