"""NYMEX strip price decks from market.futures.

Builds calendar-aligned oil & gas price vectors from the most recent forward
curve. Pure alignment is separated from the DB read so the math is unit-tested
without a database. A snapshot of one trade_date already carries prices for all
future contract months, so a future cashflow origin is read straight off it.
"""
from datetime import date

import numpy as np
from dateutil.relativedelta import relativedelta


def _month_key(d: date) -> date:
    """Normalize any date to the first of its month (the futures contract key)."""
    return d.replace(day=1)


def align_series(month_price: dict, *, origin: date, horizon_months: int) -> np.ndarray:
    """Calendar-align a {month(first-of-month date): price} map to a vector.

    Element ``i`` is the price for ``origin + i months``. Months before the
    first key take the first price; months after the last key hold the last
    price (flat extrapolation); internal gaps forward-fill from the prior month.
    """
    if not month_price:
        raise ValueError("align_series: empty price map")
    keys = sorted(month_price)
    first, last = keys[0], keys[-1]
    out = np.empty(horizon_months, dtype=float)
    prev = month_price[first]
    cur = _month_key(origin)
    for i in range(horizon_months):
        if cur < first:
            out[i] = month_price[first]
        elif cur > last:
            out[i] = month_price[last]
        else:
            prev = month_price.get(cur, prev)   # forward-fill internal gaps
            out[i] = prev
        cur = cur + relativedelta(months=1)
    return out


def build_strip_vectors(rows, *, origin: date, horizon_months: int) -> dict:
    """One trade_date's curve → aligned oil/gas vectors.

    ``rows``: ``[{"contract_month": date, "oil_price": float, "gas_price": float}]``.
    Non-positive prints (expired/rolled front months) are skipped per stream.
    Returns ``{"oil": ndarray, "gas": ndarray, "last_contract": date}``.
    """
    oil_map: dict[date, float] = {}
    gas_map: dict[date, float] = {}
    for r in rows:
        cm = _month_key(r["contract_month"])
        oil_price = r.get("oil_price")
        if oil_price is not None and oil_price > 0:
            oil_map[cm] = float(oil_price)
        gas_price = r.get("gas_price")
        if gas_price is not None and gas_price > 0:
            gas_map[cm] = float(gas_price)
    oil = align_series(oil_map, origin=origin, horizon_months=horizon_months)
    gas = align_series(gas_map, origin=origin, horizon_months=horizon_months)
    # Last contract month covered by BOTH streams (the safe horizon for either).
    last_contract = min(max(oil_map), max(gas_map))
    return {"oil": oil, "gas": gas, "last_contract": last_contract}


_CURVE_SQL = (
    "SELECT contract_month, oil_price, gas_price FROM market.futures "
    "WHERE trade_date = (SELECT max(trade_date) FROM market.futures) "
    "ORDER BY contract_month"
)
_TRADE_SQL = "SELECT max(trade_date) AS td FROM market.futures"


def load_strip_curve(*, origin: date, horizon_months: int, db_query=None) -> dict:
    """Most recent strip from market.futures, calendar-aligned to ``origin``.

    ``db_query`` is a ``utils.db.query``-shaped callable (injectable for tests).
    Returns ``{"oil", "gas", "trade_date", "last_contract"}``.
    """
    if db_query is None:
        from utils.db import query as db_query
    rows = db_query(_CURVE_SQL)
    if not rows:
        raise ValueError("market.futures returned no rows for the latest trade date")
    trade_date = db_query(_TRADE_SQL)[0]["td"]
    vecs = build_strip_vectors(rows, origin=origin, horizon_months=horizon_months)
    return {**vecs, "trade_date": trade_date}


def resolve_price_series(econ_overrides, *, origin: date, horizon_months: int,
                         flat_oil: float, flat_gas: float, db_query=None) -> dict:
    """Resolve the deal's price path: strip (default) vs flat override.

    ``price_deck.type`` defaults to ``"strip"`` (live NYMEX curve from
    market.futures); ``"flat"`` builds constant vectors at ``flat_oil``/
    ``flat_gas`` (already resolved from the case file / house defaults upstream).
    ``oil_repr``/``gas_repr`` are representative display scalars: the first-12-
    month average for strip, the flat value for flat.
    """
    deck = (econ_overrides or {}).get("price_deck") or {}
    mode = deck.get("type", "strip")
    if mode == "flat":
        return {
            "oil": np.full(horizon_months, float(flat_oil)),
            "gas": np.full(horizon_months, float(flat_gas)),
            "mode": "flat", "trade_date": None,
            "oil_repr": float(flat_oil), "gas_repr": float(flat_gas),
        }
    curve = load_strip_curve(origin=origin, horizon_months=horizon_months, db_query=db_query)
    y1 = min(12, horizon_months)
    return {
        "oil": curve["oil"], "gas": curve["gas"],
        "mode": "strip", "trade_date": curve["trade_date"],
        "oil_repr": round(float(curve["oil"][:y1].mean()), 2),
        "gas_repr": round(float(curve["gas"][:y1].mean()), 2),
    }
