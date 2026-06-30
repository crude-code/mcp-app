"""Front-month futures callout helpers.

Used by Portal hydration to fill `callout` widgets carrying a futures
front-month `code` (e.g. ``WTI_FRONT_MONTH``). Pulls from
``market.futures`` rather than EIA Cushing spot, so the value tracks
intraday-traded prompt-month closes instead of the lagged daily spot.

Front-month per trade_date is the contract whose ``contract_month`` is
the smallest value ``>= trade_date``. The contract rolls naturally
(usually ~20th of prior month for WTI), so a 30-day sparkline can
include a roll point — that's expected, not a bug.

Returns the same shape as ``utils.spot_callouts``: value, delta,
delta_direction, sparkline. Adds ``footnote`` carrying the latest
contract month + as-of trade date so the renderer can show the user
exactly which contract is being quoted and when it last traded.
"""
import math
import time

from utils.db import query as ei_query


# Callout `code` → market.futures price column.
FUTURES_CODES = {
    "WTI_FRONT_MONTH": "oil_price",
    "GAS_FRONT_MONTH": "gas_price",
}

_CACHE_TTL = 300.0
_SPARKLINE_POINTS = 30
_cache: dict = {"t": 0.0, "rows": None}


def fetch_front_month_rows() -> list[dict]:
    """Return the last N trading days of front-month rows.

    Each row: {trade_date, contract_month, oil_price, gas_price}, newest first.
    """
    now = time.monotonic()
    if _cache["rows"] is not None and (now - _cache["t"]) < _CACHE_TTL:
        return _cache["rows"]
    rows = ei_query(
        """WITH ranked AS (
              SELECT trade_date, contract_month, oil_price, gas_price,
                     ROW_NUMBER() OVER (
                       PARTITION BY trade_date
                       ORDER BY contract_month ASC
                     ) AS rn
              FROM futures
              WHERE oil_price IS NOT NULL
                AND contract_month >= trade_date
           )
           SELECT trade_date, contract_month, oil_price, gas_price
           FROM ranked WHERE rn = 1
           ORDER BY trade_date DESC LIMIT %s""",
        [_SPARKLINE_POINTS],
        schema="market",
    )
    _cache["rows"] = rows
    _cache["t"] = now
    return rows


def _fmt_contract(d) -> str:
    return d.strftime("%b %y") if hasattr(d, "strftime") else str(d)


def _fmt_date(d) -> str:
    return d.strftime("%b %d") if hasattr(d, "strftime") else str(d)


def build_futures_callout_fields(rows: list[dict], col: str) -> dict | None:
    """Build callout display fields from front-month rows.

    Rows are ordered newest-first. Uses the two most recent values for
    last + day-delta, and the full series (oldest → newest) for a sparkline.
    Returns None when there are no non-null values for this column.
    """
    pairs = []
    for r in rows:
        v = r.get(col)
        if v is None:
            continue
        try:
            v = float(v)
        except (TypeError, ValueError):
            continue
        # Skip NaN/Inf — JSON.parse rejects them client-side.
        if not math.isfinite(v):
            continue
        # Treat zero prices as missing — synthetic data quirk.
        if v == 0:
            continue
        pairs.append((r["trade_date"], r["contract_month"], v))
    if not pairs:
        return None
    latest_date, latest_contract, latest_price = pairs[0]
    prior_price = pairs[1][2] if len(pairs) >= 2 else latest_price
    change = round(latest_price - prior_price, 2)
    pct = (change / prior_price * 100.0) if prior_price else 0.0
    direction = "up" if change > 0 else "down" if change < 0 else "flat"

    series = sorted(pairs, key=lambda p: p[0])
    sparkline = [{"x": _fmt_date(d), "y": round(y, 2)} for d, _, y in series]

    return {
        "value": f"${latest_price:,.2f}",
        "delta": f"{change:+.2f} ({pct:+.1f}%)",
        "delta_direction": direction,
        "sparkline": sparkline,
        "footnote": f"{_fmt_contract(latest_contract)} · as of {_fmt_date(latest_date)}",
    }
