"""Shared spot-price callout helpers.

Used by briefing hydration (`utils.hydrate.hydrate_briefing`) to fill `callout`
widgets that carry a commodity `code` from `market.spot_prices`.

Pulls the last 30 trading days once, caches for 5 minutes, and shapes
each callout with `value`, `delta`, `delta_direction`, and a sparkline
series. Callouts that carry a free-form `query` instead of a `code` are
hydrated separately by the briefing path — those don't go through here.
"""
import time

from utils.db import query as ei_query


CODE_COLUMNS = {
    "WTI_USD": "wti",
    "BRENT_CRUDE_USD": "brent",
    "NATURAL_GAS_USD": "henry_hub",
}

_SPOT_CACHE_TTL = 300.0
_SPARKLINE_POINTS = 30
_spot_cache: dict = {"t": 0.0, "rows": None}


def fetch_spot_rows() -> list[dict]:
    now = time.monotonic()
    if _spot_cache["rows"] is not None and (now - _spot_cache["t"]) < _SPOT_CACHE_TTL:
        return _spot_cache["rows"]
    cols_sql = ", ".join(["price_date"] + list(CODE_COLUMNS.values()))
    rows = ei_query(
        f"SELECT {cols_sql} FROM spot_prices ORDER BY price_date DESC LIMIT %s",
        [_SPARKLINE_POINTS],
        schema="market",
    )
    _spot_cache["rows"] = rows
    _spot_cache["t"] = now
    return rows


def build_callout_fields(rows: list[dict], col: str) -> dict | None:
    """Build callout display fields (value/delta/sparkline) from spot_prices rows.

    Rows are ordered newest-first. Uses the two most recent non-null values
    for last + day-delta, and the full series (oldest → newest) for a sparkline.
    Returns None when there are no non-null values for this column.
    """
    pairs = [(r["price_date"], float(r[col])) for r in rows if r.get(col) is not None]
    if not pairs:
        return None
    latest = pairs[0][1]
    prior = pairs[1][1] if len(pairs) >= 2 else latest
    change = round(latest - prior, 2)
    pct = (change / prior * 100.0) if prior else 0.0
    direction = "up" if change > 0 else "down" if change < 0 else "flat"

    series = sorted(pairs, key=lambda p: p[0])
    sparkline = [
        {"x": d.strftime("%b %d") if hasattr(d, "strftime") else str(d), "y": round(y, 2)}
        for d, y in series
    ]

    return {
        "value": f"${latest:,.2f}",
        "delta": f"{change:+.2f} ({pct:+.1f}%)",
        "delta_direction": direction,
        "sparkline": sparkline,
    }
