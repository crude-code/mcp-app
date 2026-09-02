
import pytest

from server.valuation.wells import bulk_load_wells, bulk_load_production


@pytest.mark.db
def test_bulk_load_wells_returns_meta_per_api():
    apis = ["05-123-23770", "05-123-24133"]                      # from simple_weld fixture
    metas = bulk_load_wells(apis)
    assert len(metas) == 2
    assert all(m.api in apis for m in metas)
    assert all(m.basin is not None for m in metas)


@pytest.mark.db
def test_bulk_load_production_returns_per_api_series():
    apis = ["05-123-23770", "05-123-24133"]
    prod = bulk_load_production(apis)
    assert set(prod.keys()) == set(apis)
    for api in apis:
        assert "months" in prod[api]
        assert "oil_bbl" in prod[api]
        assert "gas_mcf" in prod[api]
        assert len(prod[api]["months"]) > 12       # has real history


def test_bulk_load_production_calls_query_exactly_once(monkeypatch):
    """Verify one SQL call regardless of N APIs."""
    call_count = 0
    captured_sql = []

    def fake_query(sql, params=None, schema=None, statement_timeout_ms=None):
        nonlocal call_count
        call_count += 1
        captured_sql.append(sql)
        return []  # no rows

    monkeypatch.setattr("server.valuation.wells._query", fake_query)
    bulk_load_production([f"42-000-{i:05d}" for i in range(100)])
    assert call_count == 1
    assert "IN (" in captured_sql[0]


def test_bulk_load_production_rejects_empty_api():
    with pytest.raises(ValueError, match="empty"):
        bulk_load_production(["", "42-000-00001"])


def test_bulk_load_production_rejects_null_byte():
    with pytest.raises(ValueError, match="null bytes"):
        bulk_load_production(["42\x00-000"])


def test_bulk_load_wells_empty_returns_empty_list():
    """Empty input must not hit the DB."""
    assert bulk_load_wells([]) == []


def test_bulk_load_production_empty_returns_empty_dict():
    assert bulk_load_production([]) == {}
