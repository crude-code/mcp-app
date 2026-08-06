"""Consequence math for the forecast echo. Pure — no DB, no persistence.

``forecast_wells`` speaks back to Claude entirely in future volumes — never in
fit quality (there is no fit). The functions here turn an asserted curve into
the numbers the sanity loop interrogates: implied next-12/next-24 cum against
trailing actuals, effective annual decline at years 1 and 5, EUR (cum-to-date
plus forecast remainder), EUR/ft, and where the terminal switch lands.

Conventions (shared with the econ schedule):

- t is months since the anchor; q(0) == qi, the anchor-month rate.
- For a producing well the anchor month itself is history: forecast volumes
  are t = 1..N, so next-12 means Σ q(1..12).
- For a not-yet-producing well the anchor IS the asserted online month: the
  online month produces q(0), volumes are t = 0..N−1 — matching where the
  econ schedule places it.
- EUR = recorded cum through the anchor + the forecast remainder over the
  horizon. When Claude anchors before the last reported month (contaminated
  recent data), actuals after the anchor are REPLACED by the forecast, never
  double-counted.
- The echo runs on calendar months from the anchor; the econ schedule starts
  at the valuation origin. When an anchor trails the origin the two views
  differ by construction — the echo answers "what does this curve say from
  where it starts", not "what lands in this deal's month 1". A DUC anchored
  +36 months also sees its econ contribution truncated at the deal horizon
  while the echo EUR is curve-life; that asymmetry is intentional.
"""
from datetime import date

import numpy as np
from dateutil.relativedelta import relativedelta

from server.valuation.forecast import curve_rate
from server.valuation.types import DeclineCurve


def _norm_month(m: "str | date") -> date:
    if isinstance(m, date):
        return m.replace(day=1)
    return date.fromisoformat(str(m)[:10]).replace(day=1)


def effective_annual_decline(curve: DeclineCurve, *, year: int) -> float | None:
    """Effective (not nominal) annual decline over forecast year ``year``:
    ``(q_start − q_end) / q_start`` across that year's 12 months. ``None``
    when the starting rate is zero (a zero curve has no decline)."""
    if year < 1:
        raise ValueError(f"year must be >= 1; got {year}")
    q_start = curve_rate(curve, float(12 * (year - 1)))
    q_end = curve_rate(curve, float(12 * year))
    if q_start <= 0.0:
        return None
    return (q_start - q_end) / q_start


def trailing_window_cum(months: list, q, *, anchor: date) -> float:
    """Actual cum over the 12 calendar months ending at ``anchor`` inclusive."""
    anchor = anchor.replace(day=1)
    lo = anchor - relativedelta(months=11)
    total = 0.0
    for m, v in zip(months, np.asarray(q, dtype=float)):
        d = _norm_month(m)
        if lo <= d <= anchor and np.isfinite(v):
            total += float(v)
    return total


def cum_through(months: list, q, *, anchor: date) -> float:
    """Actual cum from first record through ``anchor`` inclusive."""
    anchor = anchor.replace(day=1)
    total = 0.0
    for m, v in zip(months, np.asarray(q, dtype=float)):
        if _norm_month(m) <= anchor and np.isfinite(v):
            total += float(v)
    return total


def allocation_shares(trailing_by_api: dict[str, float]) -> dict[str, float]:
    """Pro-rata cohort shares from trailing-12 cums. Validation upstream
    guarantees every member is positive; this raises rather than silently
    producing a degenerate split if that guarantee is ever broken."""
    total = sum(trailing_by_api.values())
    bad = [api for api, v in trailing_by_api.items() if v <= 0.0]
    if bad or total <= 0.0:
        raise ValueError(f"allocation_shares: nonpositive trailing-12 for {bad or 'all members'}")
    return {api: v / total for api, v in trailing_by_api.items()}


def stream_consequences(
    curve: DeclineCurve,
    *,
    anchor: date,
    horizon_months: int,
    trailing_12_actual: float | None,
    cum_to_date: float,
    lateral_ft: float | None,
    anchor_is_future: bool = False,
) -> dict:
    """The echo for one committed stream, per the module conventions.

    ``anchor_is_future`` marks a not-yet-producing well: its forecast window
    starts at t=0 (the online month) instead of t=1, and there are no trailing
    actuals to compare against.
    """
    if horizon_months <= 0:
        raise ValueError(f"horizon_months must be positive; got {horizon_months}")
    anchor = anchor.replace(day=1)
    t0 = 0 if anchor_is_future else 1
    t = np.arange(t0, t0 + horizon_months, dtype=float)
    rates = np.asarray(curve_rate(curve, t), dtype=float)

    next_12 = float(rates[:12].sum()) if horizon_months >= 12 else None
    next_24 = float(rates[:24].sum()) if horizon_months >= 24 else None
    remaining = float(rates.sum())
    eur = cum_to_date + remaining

    ratio = None
    if next_12 is not None and trailing_12_actual is not None and trailing_12_actual > 0.0:
        ratio = next_12 / trailing_12_actual

    yr1 = effective_annual_decline(curve, year=1)
    yr5 = effective_annual_decline(curve, year=5)

    switch = curve.switch_month_from_peak
    if np.isfinite(switch):
        switch_date = anchor + relativedelta(months=int(round(switch)))
        terminal = {"months_from_anchor": round(float(switch), 1),
                    "date": switch_date.strftime("%Y-%m")}
    else:
        terminal = {"months_from_anchor": None, "date": None}

    return {
        "next_12_cum": None if next_12 is None else round(next_12, 1),
        "next_24_cum": None if next_24 is None else round(next_24, 1),
        "trailing_12_actual": None if trailing_12_actual is None else round(trailing_12_actual, 1),
        "next12_over_trailing12": None if ratio is None else round(ratio, 3),
        "eff_annual_decline_yr1": None if yr1 is None else round(yr1, 4),
        "eff_annual_decline_yr5": None if yr5 is None else round(yr5, 4),
        "eur": round(eur, 1),
        "cum_to_date": round(cum_to_date, 1),
        "eur_remaining": round(remaining, 1),
        "eur_per_ft": None if not lateral_ft else round(eur / float(lateral_ft), 2),
        "terminal_switch": terminal,
    }
