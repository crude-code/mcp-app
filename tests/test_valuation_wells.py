
import pytest

from server.valuation.types import WellMeta
from server.valuation.wells import apply_well_facts, bulk_load_wells, bulk_load_production


def _wf_meta(api, lateral_ft):
    return WellMeta(
        api=api, status="PERMITTED", basin="DJ", formation="NIOBRARA A",
        county="WELD", lateral_ft=lateral_ft, spud_date=None,
        completion_date=None, first_prod_date=None, last_prod_date=None,
        n_history_months=0, planned_first_prod_date=None,
        geom_wkt="POINT(-104.5 40.3)", operator="CHEVRON",
    )


def test_apply_well_facts_fills_when_db_null():
    metas = [_wf_meta("33-053-10751", None)]
    out = apply_well_facts(metas, {"33-053-10751": {"lateral_ft": 15398}})
    assert out[0].lateral_ft == 15398.0


def test_apply_well_facts_db_wins_when_present():
    metas = [_wf_meta("33-053-10751", 9800.0)]
    out = apply_well_facts(metas, {"33-053-10751": {"lateral_ft": 15398}})
    assert out[0].lateral_ft == 9800.0


def test_apply_well_facts_passes_through_unlisted_wells():
    metas = [_wf_meta("33-053-10751", None)]
    out = apply_well_facts(metas, {"99-999-99999": {"lateral_ft": 12000}})
    assert out[0].lateral_ft is None


def test_apply_well_facts_empty_map_is_noop():
    metas = [_wf_meta("33-053-10751", None), _wf_meta("33-053-99999", 9800.0)]
    out = apply_well_facts(metas, {})
    assert [m.lateral_ft for m in out] == [None, 9800.0]


def test_apply_well_facts_entry_without_lateral_is_noop():
    metas = [_wf_meta("33-053-10751", None)]
    out = apply_well_facts(metas, {"33-053-10751": {}})
    assert out[0].lateral_ft is None


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
