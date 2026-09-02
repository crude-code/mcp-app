"""Hyperbolic evaluation and projection. Pure math — the calculator.

There is no fitting and no parameter selection anywhere in this module (or this
server): decline parameters are asserted upstream by Claude via
``deal_forecast_wells`` and arrive here as literals. The calculator owns exactly one
number of its own — the terminal decline (``config.ECON.terminal_di_annual``),
applied by ``make_curve`` as the exponential-tail switch.
"""
import math
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


def curve_to_dict(c: DeclineCurve) -> dict:
    """DeclineCurve → the JSON shape the forecast stage persists. An infinite
    switch month is stored as None."""
    switch = c.switch_month_from_peak
    return {
        "qi": c.qi, "di": c.di, "b": c.b,
        "terminal_di_monthly": c.terminal_di_monthly,
        "switch_month_from_peak": switch if math.isfinite(switch) else None,
        "stream": c.stream,
        "provenance": {"source": c.provenance.source, "strategy": c.provenance.strategy},
    }


def curve_from_dict(c: dict) -> DeclineCurve:
    """Inverse of `curve_to_dict`. None switch month → float('inf'). The one
    reader of persisted curves, shared by the orchestrator, the evidence
    builder and the export lane."""
    switch = c["switch_month_from_peak"]
    prov = c.get("provenance") or {}
    return DeclineCurve(
        qi=c["qi"], di=c["di"], b=c["b"],
        terminal_di_monthly=c["terminal_di_monthly"],
        switch_month_from_peak=float("inf") if switch is None else switch,
        stream=c["stream"],
        provenance=ForecastProvenance(source=prov.get("source", "asserted"),
                                      strategy=prov.get("strategy")),
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
    """Project a Forecast forward as monthly rates.

    Returns ``(months, rates)``: ``months[i]`` is the calendar month
    ``start_date + i`` and ``rates[i]`` the curve at ``t = i`` — so
    ``rates[0] == qi``, the asserted anchor rate.
    """
    if horizon_months <= 0:
        raise ValueError(f"horizon_months must be positive; got {horizon_months}")
    rates = curve_rate(forecast.curve, np.arange(horizon_months, dtype=float))

    months: list[date] = []
    cur = forecast.start_date.replace(day=1)
    for _ in range(horizon_months):
        months.append(cur)
        cur = cur + relativedelta(months=1)
    return months, rates
