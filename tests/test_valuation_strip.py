from datetime import date

import pytest

from server.valuation import strip


def test_align_series_reads_each_month_in_order():
    m = {date(2026, 7, 1): 70.0, date(2026, 8, 1): 71.0, date(2026, 9, 1): 72.0}
    out = strip.align_series(m, origin=date(2026, 7, 1), horizon_months=3)
    assert list(out) == [70.0, 71.0, 72.0]


def test_align_series_flat_extrapolates_past_last_contract():
    m = {date(2026, 7, 1): 70.0, date(2026, 8, 1): 71.0}
    out = strip.align_series(m, origin=date(2026, 7, 1), horizon_months=5)
    # months 3,4,5 hold the last quoted contract (71.0) flat
    assert list(out) == [70.0, 71.0, 71.0, 71.0, 71.0]


def test_align_series_backfills_before_first_contract():
    # origin precedes the first available contract → take the first price
    m = {date(2026, 8, 1): 73.0, date(2026, 9, 1): 72.0}
    out = strip.align_series(m, origin=date(2026, 7, 1), horizon_months=3)
    assert list(out) == [73.0, 73.0, 72.0]


def test_align_series_forward_fills_internal_gap():
    m = {date(2026, 7, 1): 70.0, date(2026, 9, 1): 72.0}  # Aug missing
    out = strip.align_series(m, origin=date(2026, 7, 1), horizon_months=3)
    assert list(out) == [70.0, 70.0, 72.0]


def test_align_series_empty_raises():
    with pytest.raises(ValueError):
        strip.align_series({}, origin=date(2026, 7, 1), horizon_months=3)


def test_build_strip_vectors_skips_nonpositive_per_stream():
    rows = [
        {"contract_month": date(2026, 7, 1), "oil_price": 0.0, "gas_price": 3.1},   # oil rolled
        {"contract_month": date(2026, 8, 1), "oil_price": 73.0, "gas_price": 3.2},
        {"contract_month": date(2026, 9, 1), "oil_price": 72.0, "gas_price": 3.3},
    ]
    out = strip.build_strip_vectors(rows, origin=date(2026, 7, 1), horizon_months=3)
    # oil July is skipped → backfilled from Aug (73.0); gas July is valid (3.1)
    assert list(out["oil"]) == [73.0, 73.0, 72.0]
    assert list(out["gas"]) == [3.1, 3.2, 3.3]
    assert out["last_contract"] == date(2026, 9, 1)


def test_build_strip_vectors_skips_negative_price():
    rows = [
        {"contract_month": date(2026, 7, 1), "oil_price": -5.0, "gas_price": 3.1},  # bad print
        {"contract_month": date(2026, 8, 1), "oil_price": 73.0, "gas_price": 3.2},
    ]
    out = strip.build_strip_vectors(rows, origin=date(2026, 7, 1), horizon_months=2)
    assert list(out["oil"]) == [73.0, 73.0]   # negative July skipped → backfilled from Aug
    assert list(out["gas"]) == [3.1, 3.2]


def test_build_strip_vectors_empty_stream_raises():
    # every oil print is non-positive → empty oil map → align_series raises
    rows = [{"contract_month": date(2026, 7, 1), "oil_price": 0.0, "gas_price": 3.1}]
    with pytest.raises(ValueError):
        strip.build_strip_vectors(rows, origin=date(2026, 7, 1), horizon_months=1)


def test_load_strip_curve_uses_latest_trade_date_via_injected_db():
    calls = []

    def fake_query(sql, *args, **kwargs):
        calls.append(sql)
        if "max(trade_date) AS td" in sql:
            return [{"td": date(2026, 6, 23)}]
        # the curve query
        return [
            {"contract_month": date(2026, 7, 1), "oil_price": 0.0, "gas_price": 3.1},
            {"contract_month": date(2026, 8, 1), "oil_price": 73.0, "gas_price": 3.2},
        ]

    out = strip.load_strip_curve(origin=date(2026, 7, 1), horizon_months=2, db_query=fake_query)
    assert out["trade_date"] == date(2026, 6, 23)
    assert list(out["oil"]) == [73.0, 73.0]   # July oil rolled → backfilled
    assert list(out["gas"]) == [3.1, 3.2]
    # the curve query must pin to the latest trade_date
    assert any("trade_date = (SELECT max(trade_date)" in c for c in calls)


@pytest.mark.db
def test_load_strip_curve_hits_real_futures():
    out = strip.load_strip_curve(origin=date(2026, 7, 1), horizon_months=360)
    assert out["oil"].shape == (360,)
    assert out["gas"].shape == (360,)
    assert (out["oil"] > 0).all()      # no zeros leak through after skip+fill
    assert (out["gas"] > 0).all()
    assert out["trade_date"] is not None


def _fake_curve_db():
    def fake_query(sql, *a, **k):
        if "max(trade_date) AS td" in sql:
            return [{"td": date(2026, 6, 23)}]
        return [
            {"contract_month": date(2026, 7, 1), "oil_price": 80.0, "gas_price": 4.0},
            {"contract_month": date(2026, 8, 1), "oil_price": 60.0, "gas_price": 2.0},
        ]
    return fake_query


def test_resolve_price_series_defaults_to_strip():
    out = strip.resolve_price_series(
        {}, origin=date(2026, 7, 1), horizon_months=2,
        flat_oil=70.0, flat_gas=3.5, db_query=_fake_curve_db())
    assert out["mode"] == "strip"
    assert out["trade_date"] == date(2026, 6, 23)
    assert list(out["oil"]) == [80.0, 60.0]
    assert out["oil_repr"] == 70.0       # mean(80, 60) over the 2-month window
    assert out["gas_repr"] == 3.0


def test_resolve_price_series_flat_override_builds_constant_vectors():
    out = strip.resolve_price_series(
        {"price_deck": {"type": "flat", "oil_usd_bbl": 65.0, "gas_usd_mmbtu": 3.0}},
        origin=date(2026, 7, 1), horizon_months=3,
        flat_oil=65.0, flat_gas=3.0, db_query=_fake_curve_db())
    assert out["mode"] == "flat"
    assert out["trade_date"] is None
    assert list(out["oil"]) == [65.0, 65.0, 65.0]
    assert list(out["gas"]) == [3.0, 3.0, 3.0]
    assert out["oil_repr"] == 65.0
