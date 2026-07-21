"""Decline curve fitting and projection. Pure math — no DB, no lateral norm."""
from datetime import date

import numpy as np
from dateutil.relativedelta import relativedelta
from scipy.optimize import curve_fit

from server.valuation.types import DeclineCurve, Forecast, ForecastProvenance


def _hyperbolic_q(t: np.ndarray, qi: float, di: float, b: float) -> np.ndarray:
    if b < 1e-6:
        return qi * np.exp(-di * t)
    return qi / np.power(1.0 + b * di * t, 1.0 / b)


def fit_curve(
    months: np.ndarray,
    q: np.ndarray,
    *,
    stream: str,
    terminal_di_annual: float = 0.05,
    min_post_peak_months: int = 6,
    b_fixed: float | None = None,
) -> DeclineCurve:
    """Fit hyperbolic decline to a well's production from peak forward.

    No ``lateral_norm_ft`` parameter — the cohort filter handles lateral matching.

    When ``b_fixed`` is set, fits only ``(qi_peak, di)`` with ``b`` held at the
    given value — Arps b is poorly identified on <~24 post-peak months and the
    3-param fit was riding the bounds (b≈0 or b≈2) on ~37% of wells. Pass a
    basin-typical b (0.7–1.0 for unconventional oil) for stable fits.

    Raises:
        ValueError if post-peak history is shorter than min_post_peak_months,
        or if all post-peak production is zero.
    """
    months = np.asarray(months, dtype=float)
    q = np.asarray(q, dtype=float)

    peak_idx = int(np.argmax(q))
    months_fit = months[peak_idx:]
    q_fit = q[peak_idx:]
    n_post_peak = len(q_fit) - 1
    if n_post_peak < min_post_peak_months:
        raise ValueError(
            f"thin history: need at least {min_post_peak_months} post-peak months, "
            f"got {n_post_peak} (peak at idx {peak_idx} of {len(q)})"
        )
    t_rel = months_fit - months_fit[0]
    if q_fit[1:].sum() <= 0.0:
        raise ValueError("fit_curve: no production data after peak")

    if b_fixed is None:
        p0 = [float(q_fit[0]), 0.05, 0.5]
        bounds = ([0.0, 0.0, 0.001], [1e8, 1.0, 2.0])
        popt, _ = curve_fit(_hyperbolic_q, t_rel, q_fit, p0=p0, bounds=bounds, maxfev=5000)
        qi_peak, di, b = (float(x) for x in popt)
    else:
        b = float(b_fixed)

        def _model_fixed_b(t, qi, di):
            return _hyperbolic_q(t, qi, di, b)

        p0 = [float(q_fit[0]), 0.05]
        bounds = ([0.0, 0.0], [1e8, 1.0])
        popt, _ = curve_fit(_model_fixed_b, t_rel, q_fit, p0=p0, bounds=bounds, maxfev=5000)
        qi_peak, di = (float(x) for x in popt)

    terminal_di_monthly = terminal_di_annual / 12.0
    if di > terminal_di_monthly and b > 1e-6:
        switch_month = max(0.0, (di / terminal_di_monthly - 1.0) / (b * di))
    else:
        switch_month = float("inf")

    return DeclineCurve(
        qi_peak=qi_peak,
        di=di,
        b=b,
        terminal_di_monthly=terminal_di_monthly,
        switch_month_from_peak=switch_month,
        stream=stream,
        provenance=ForecastProvenance(source="fit", fit_n_input_months=len(q_fit)),
    )


def percentile_curves(curves: list[DeclineCurve], *, pct: float = 0.5) -> DeclineCurve:
    """Aggregate N curves into a cohort curve via percentile.

    ``pct`` is in ``[0, 1]`` (0.5 = median, 0.1 = P10, 0.9 = P90). NO lateral
    rescaling — the cohort filter already constrains the inputs to comparable
    laterals.

    Raises:
        ValueError if ``curves`` is empty, if input curves mix streams, or if
        ``pct`` is outside ``[0, 1]``.
    """
    if not curves:
        raise ValueError("percentile_curves requires at least one input curve")
    if not 0.0 <= pct <= 1.0:
        raise ValueError(f"pct must be in [0, 1]; got {pct}")
    streams = {c.stream for c in curves}
    if len(streams) > 1:
        raise ValueError(f"all curves must share the same stream; got {streams}")

    qis = [c.qi_peak for c in curves]
    qi_pct = float(np.percentile(qis, pct * 100.0))
    di_pct = float(np.percentile([c.di for c in curves], pct * 100.0))
    b_pct = float(np.percentile([c.b for c in curves], pct * 100.0))
    terminal_di_pct = float(np.percentile([c.terminal_di_monthly for c in curves], pct * 100.0))
    if di_pct > terminal_di_pct and b_pct > 1e-6:
        switch_month = max(0.0, (di_pct / terminal_di_pct - 1.0) / (b_pct * di_pct))
    else:
        switch_month = float("inf")
    return DeclineCurve(
        qi_peak=qi_pct, di=di_pct, b=b_pct,
        terminal_di_monthly=terminal_di_pct,
        switch_month_from_peak=switch_month,
        stream=curves[0].stream,
        provenance=ForecastProvenance(
            source="percentile",
            component_curves=tuple(c.provenance for c in curves),
        ),
    )


def fit_curve_best_b(
    months: np.ndarray,
    q: np.ndarray,
    *,
    stream: str,
    b_grid: tuple[float, ...],
    terminal_di_annual: float = 0.05,
    min_post_peak_months: int = 6,
) -> DeclineCurve:
    """Fixed-b fits across ``b_grid``; returns the minimum-SSE curve.

    A bounded "free b" that cannot bound-ride: every candidate is a stable
    2-parameter :func:`fit_curve` at a fixed b, compared on post-peak SSE.
    Backtested 2026-07: for ≥30-post-peak-month wells this halves holdout MAE
    vs borrowing a cohort b (results/backtest_baseline_v1.json).

    Raises:
        ValueError if ``b_grid`` is empty, or wherever fit_curve raises (thin
        history, all-zero post-peak) — data validity is b-independent.
    """
    if not b_grid:
        raise ValueError("fit_curve_best_b requires a non-empty b_grid")
    q = np.asarray(q, dtype=float)
    peak_idx = int(np.argmax(q))
    q_fit = q[peak_idx:]
    t_rel = np.arange(len(q_fit), dtype=float)

    best: DeclineCurve | None = None
    best_sse = float("inf")
    for b in b_grid:
        curve = fit_curve(months, q, stream=stream, b_fixed=float(b),
                          terminal_di_annual=terminal_di_annual,
                          min_post_peak_months=min_post_peak_months)
        sse = float(np.sum((np.asarray(curve_rate(curve, t_rel)) - q_fit) ** 2))
        if sse < best_sse:
            best, best_sse = curve, sse
    return best


def override_b(curve: DeclineCurve, b: float, *, note: str) -> DeclineCurve:
    """The same curve with a re-sourced ``b``. The terminal switch month depends
    on (di, b), so it is recomputed; everything else is preserved. ``note`` lands
    in provenance.notes so the run record says where the b came from."""
    if curve.di > curve.terminal_di_monthly and b > 1e-6:
        switch = max(0.0, (curve.di / curve.terminal_di_monthly - 1.0) / (b * curve.di))
    else:
        switch = float("inf")
    return DeclineCurve(
        qi_peak=curve.qi_peak, di=curve.di, b=float(b),
        terminal_di_monthly=curve.terminal_di_monthly,
        switch_month_from_peak=switch,
        stream=curve.stream,
        provenance=ForecastProvenance(
            source=curve.provenance.source,
            fit_n_input_months=curve.provenance.fit_n_input_months,
            component_curves=curve.provenance.component_curves,
            notes=(*curve.provenance.notes, note),
        ),
    )


def curve_rate(curve: DeclineCurve, t_months: float | np.ndarray) -> float | np.ndarray:
    """Evaluate the curve at t months past peak.

    Accepts a scalar or an ``np.ndarray``; returns the same shape. Past
    ``switch_month_from_peak`` the curve follows an exponential at
    ``terminal_di_monthly``. Raises ValueError if any t is negative
    (no pre-peak extrapolation).
    """
    t = np.asarray(t_months, dtype=float)
    if np.any(t < 0):
        raise ValueError("curve_rate: negative t (pre-peak extrapolation) not supported")

    q_hyp = _hyperbolic_q(t, curve.qi_peak, curve.di, curve.b)
    if not np.isfinite(curve.switch_month_from_peak):
        result = q_hyp
    else:
        switch = curve.switch_month_from_peak
        q_at_switch = _hyperbolic_q(np.array([switch]), curve.qi_peak, curve.di, curve.b)[0]
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
    For wells where ``start_date == peak_date`` (PUDs, climbing wells)
    ``peak_offset == 0``. For PDP wells with history, ``peak_offset`` is the
    months elapsed between the historical peak and the forecast anchor.
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
