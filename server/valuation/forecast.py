"""Hyperbolic evaluation and projection. Pure math — the calculator.

There is no fitting and no parameter selection anywhere in this module (or this
server): decline parameters are asserted upstream by Claude via
``forecast_wells`` and arrive here as literals. The calculator owns exactly one
number of its own — the terminal decline (``config.ECON.terminal_di_annual``),
applied by ``make_curve`` as the exponential-tail switch.
"""
from datetime import date

import numpy as np
from dateutil.relativedelta import relativedelta

from server.valuation.types import DeclineCurve, Forecast, ForecastProvenance


def _hyperbolic_q(t: np.ndarray, qi: float, di: float, b: float) -> np.ndarray:
    if b < 1e-6:
        return qi * np.exp(-di * t)
    return qi / np.power(1.0 + b * di * t, 1.0 / b)


def make_curve(
    qi: float,
    di: float,
    b: float,
    *,
    stream: str,
    terminal_di_annual: float,
    provenance: ForecastProvenance | None = None,
) -> DeclineCurve:
    """Build a curve from asserted parameters.

    The terminal switch is the calculator's tail policy: once the hyperbolic
    decline shallows to ``terminal_di_annual``, the curve follows an
    exponential at that rate. The switch month solves d(t) = terminal:
    ``(di/di_term − 1) / (b·di)``. It is infinite when ``b ≈ 0`` (the curve is
    already exponential) or ``di <= di_term`` (the asserted decline starts
    shallower than terminal and never steepens to it — allowed; the tool echo
    warns so Claude sees what it committed).
    """
    terminal_di_monthly = terminal_di_annual / 12.0
    if di > terminal_di_monthly and b > 1e-6:
        switch = max(0.0, (di / terminal_di_monthly - 1.0) / (b * di))
    else:
        switch = float("inf")
    return DeclineCurve(
        qi=float(qi),
        di=float(di),
        b=float(b),
        terminal_di_monthly=terminal_di_monthly,
        switch_month_from_peak=switch,
        stream=stream,
        provenance=provenance
        or ForecastProvenance(source="asserted", strategy="asserted"),
    )


def make_zero_curve(stream: str) -> DeclineCurve:
    """Flat-zero curve for a stream Claude did not assert (a well with no
    meaningful gas, say). Keeps the schedule math uniform: every well always
    carries both streams."""
    return DeclineCurve(
        qi=0.0,
        di=0.0,
        b=0.0,
        terminal_di_monthly=0.0,
        switch_month_from_peak=float("inf"),
        stream=stream,
        provenance=ForecastProvenance(source="asserted", strategy="not_asserted"),
    )


def curve_rate(curve: DeclineCurve, t_months: float | np.ndarray) -> float | np.ndarray:
    """Evaluate the curve at t months past its anchor (t=0 is where q == qi).

    Accepts a scalar or an ``np.ndarray``; returns the same shape. Past
    ``switch_month_from_peak`` the curve follows an exponential at
    ``terminal_di_monthly``. Raises ValueError if any t is negative
    (no pre-anchor extrapolation).
    """
    t = np.asarray(t_months, dtype=float)
    if np.any(t < 0):
        raise ValueError("curve_rate: negative t (pre-anchor extrapolation) not supported")

    q_hyp = _hyperbolic_q(t, curve.qi, curve.di, curve.b)
    if not np.isfinite(curve.switch_month_from_peak):
        result = q_hyp
    else:
        switch = curve.switch_month_from_peak
        q_at_switch = _hyperbolic_q(np.array([switch]), curve.qi, curve.di, curve.b)[0]
        post = t >= switch
        result = np.where(
            post,
            q_at_switch * np.exp(-curve.terminal_di_monthly * (t - switch)),
            q_hyp,
        )
    if np.ndim(t_months) == 0:
        return float(result)
    return result


def project(forecast: Forecast, *, horizon_months: int) -> tuple[list[date], np.ndarray]:
    """Project a Forecast forward as monthly rates. NO lateral_scale.

    Returns ``(months, rates)`` where ``months[i]`` is the calendar month and
    ``rates[i]`` is the curve evaluated at ``t = peak_offset + i``, with
    ``peak_offset`` being the months between ``peak_date`` and ``start_date``.
    Asserted curves anchor where they start (``peak_date == start_date`` ⇒
    ``peak_offset == 0`` ⇒ ``rates[0] == qi``); a nonzero offset appears only
    when replaying legacy fit-era stages whose qi was a peak rate.
    """
    if horizon_months <= 0:
        raise ValueError(f"horizon_months must be positive; got {horizon_months}")
    peak = forecast.peak_date.replace(day=1)
    start = forecast.start_date.replace(day=1)
    peak_offset = (start.year - peak.year) * 12 + (start.month - peak.month)
    if peak_offset < 0:
        raise ValueError(
            f"start_date {forecast.start_date} is before peak_date {forecast.peak_date}; "
            f"curve_rate does not support pre-peak extrapolation"
        )
    t_offsets = np.arange(peak_offset, peak_offset + horizon_months, dtype=float)
    rates = curve_rate(forecast.curve, t_offsets)

    months: list[date] = []
    cur = start
    for _ in range(horizon_months):
        months.append(cur)
        cur = cur + relativedelta(months=1)
    return months, rates


def aggregate(
    forecasts: list[Forecast],
    *,
    horizon_months: int,
    origin: date | None = None,
) -> tuple[list[date], np.ndarray]:
    """Sum N forecasts onto a shared monthly calendar axis.

    Each well is placed at its calendar offset from the axis ``origin`` (month
    0), so a well that comes online later contributes zeros until that month.
    ``origin`` defaults to the earliest ``start_date``; economics passes the
    valuation as-of month so a PUD coming online in 3 years is discounted as
    3 years out. A well whose ``start_date`` precedes ``origin`` (a producer
    already flowing at the as-of date) is clamped to month 0.

    Uses ``project`` per forecast so each well's ``peak_offset`` is honored.
    """
    if horizon_months <= 0:
        raise ValueError(f"horizon_months must be positive; got {horizon_months}")
    if not forecasts:
        return [], np.zeros(0)

    start = (origin or min(f.start_date for f in forecasts)).replace(day=1)
    months: list[date] = []
    cur = start
    for _ in range(horizon_months):
        months.append(cur)
        cur = cur + relativedelta(months=1)

    totals = np.zeros(horizon_months, dtype=float)
    for f in forecasts:
        f_start = f.start_date.replace(day=1)
        offset_months = (f_start.year - start.year) * 12 + (f_start.month - start.month)
        offset_months = max(0, offset_months)          # producing before origin -> month 0
        if offset_months >= horizon_months:
            continue
        per_forecast_horizon = horizon_months - offset_months
        _, rates = project(f, horizon_months=per_forecast_horizon)
        totals[offset_months:] += rates
    return months, totals
