import pytest
import numpy as np
from datetime import date
from server.valuation.types import DeclineCurve, Forecast, ForecastProvenance


def test_decline_curve_has_no_lateral_norm_ft():
    """Lateral normalization is gone from the model."""
    curve = DeclineCurve(
        qi_peak=1200.0, di=0.05, b=0.8,
        terminal_di_monthly=0.05 / 12,
        switch_month_from_peak=120.0,
        stream="oil",
        provenance=ForecastProvenance(source="fit"),
    )
    assert not hasattr(curve, "lateral_norm_ft")


def test_forecast_has_no_lateral_scale():
    curve = DeclineCurve(
        qi_peak=1200.0, di=0.05, b=0.8,
        terminal_di_monthly=0.05 / 12,
        switch_month_from_peak=120.0,
        stream="oil",
        provenance=ForecastProvenance(source="fit"),
    )
    f = Forecast(
        curve=curve,
        peak_date=date(2024, 1, 1),
        start_date=date(2024, 6, 1),
        provenance=ForecastProvenance(source="fit"),
    )
    assert not hasattr(f, "lateral_scale")


# ---------------------------------------------------------------------------
# fit_curve + curve_rate tests
# ---------------------------------------------------------------------------
from server.valuation.forecast import fit_curve, curve_rate


def test_fit_curve_recovers_synthetic_decline():
    """Generate q from known (qi=1000, di=0.05, b=0.8); fit should recover them."""
    months = np.arange(36, dtype=float)
    qi_true, di_true, b_true = 1000.0, 0.05, 0.8
    q = qi_true / np.power(1.0 + b_true * di_true * months, 1.0 / b_true)
    curve = fit_curve(months, q, stream="oil", b_fixed=b_true)
    assert abs(curve.qi_peak - qi_true) / qi_true < 0.01
    assert abs(curve.di - di_true) < 0.005


def test_fit_curve_raises_on_thin_history():
    months = np.arange(3, dtype=float)
    q = np.array([1000.0, 800.0, 700.0])
    with pytest.raises(ValueError, match="post-peak"):
        fit_curve(months, q, stream="oil", b_fixed=0.8, min_post_peak_months=6)


def test_curve_rate_scalar_and_array():
    curve = DeclineCurve(
        qi_peak=1000.0, di=0.05, b=0.8,
        terminal_di_monthly=0.05 / 12,
        switch_month_from_peak=120.0,
        stream="oil",
        provenance=ForecastProvenance(source="fit"),
    )
    assert curve_rate(curve, 0.0) == 1000.0  # qi at t=0
    arr = curve_rate(curve, np.array([0.0, 12.0, 24.0]))
    assert arr.shape == (3,)
    assert arr[0] > arr[1] > arr[2]


from server.valuation.forecast import percentile_curves


def test_percentile_curves_no_lateral_rescale():
    """Median across curves with NO lateral-based qi rescaling."""
    curves = []
    for qi in [800.0, 1000.0, 1200.0]:
        curves.append(fit_curve(
            months=np.arange(24, dtype=float),
            q=qi / np.power(1 + 0.8 * 0.05 * np.arange(24), 1.25),
            stream="oil", b_fixed=0.8,
        ))
    med = percentile_curves(curves, pct=0.5)
    # No lateral rescaling — median qi should be ~1000 regardless of well laterals
    assert 950.0 < med.qi_peak < 1050.0
    assert med.stream == "oil"


def test_percentile_curves_raises_on_empty():
    with pytest.raises(ValueError, match="at least one"):
        percentile_curves([], pct=0.5)


def test_percentile_curves_raises_on_mixed_streams():
    curves = []
    for stream in ("oil", "gas"):
        curves.append(fit_curve(
            months=np.arange(24, dtype=float),
            q=1000.0 / np.power(1 + 0.8 * 0.05 * np.arange(24), 1.25),
            stream=stream, b_fixed=0.8,
        ))
    with pytest.raises(ValueError, match="same stream"):
        percentile_curves(curves, pct=0.5)


def test_percentile_curves_rejects_pct_out_of_range():
    curve = fit_curve(
        months=np.arange(24, dtype=float),
        q=1000.0 / np.power(1 + 0.8 * 0.05 * np.arange(24), 1.25),
        stream="oil", b_fixed=0.8,
    )
    with pytest.raises(ValueError, match=r"\[0, 1\]"):
        percentile_curves([curve], pct=50.0)


from server.valuation.forecast import project, aggregate


def test_project_horizon_months():
    curve = fit_curve(
        months=np.arange(24, dtype=float),
        q=1000.0 / np.power(1 + 0.8 * 0.05 * np.arange(24), 1.25),
        stream="oil", b_fixed=0.8,
    )
    f = Forecast(
        curve=curve,
        peak_date=date(2024, 1, 1),
        start_date=date(2024, 1, 1),
        provenance=ForecastProvenance(source="fit"),
    )
    months, rates = project(f, horizon_months=360)
    assert len(months) == 360
    assert len(rates) == 360
    assert rates[0] > rates[-1]                  # decline


def test_aggregate_sums_streams():
    # 2 forecasts, both anchored same date, 12-month horizon
    forecasts = []
    for qi in [500.0, 700.0]:
        c = fit_curve(np.arange(24, dtype=float),
                      qi / np.power(1 + 0.8 * 0.05 * np.arange(24), 1.25),
                      stream="oil", b_fixed=0.8)
        forecasts.append(Forecast(
            curve=c, peak_date=date(2024, 1, 1), start_date=date(2024, 1, 1),
            provenance=ForecastProvenance(source="fit"),
        ))
    months, totals = aggregate(forecasts, horizon_months=12)
    assert len(months) == 12
    # Aggregate at t=0 ≈ sum of qi_peaks (within fit noise)
    assert 1150.0 < totals[0] < 1250.0


def _flat_forecast(qi, start):
    """A forecast with peak == start so project starts at qi (no peak offset)."""
    c = DeclineCurve(
        qi_peak=qi, di=0.05, b=0.8, terminal_di_monthly=0.05 / 12,
        switch_month_from_peak=float("inf"), stream="oil",
        provenance=ForecastProvenance(source="fit"),
    )
    return Forecast(curve=c, peak_date=start, start_date=start,
                    provenance=ForecastProvenance(source="fit"))


def test_aggregate_origin_offsets_future_wells():
    """A well coming online after the origin contributes zeros until that month,
    then jumps in at qi — this is the calendar alignment economics relies on."""
    origin = date(2026, 6, 1)
    producing = _flat_forecast(1000.0, origin)               # online at month 0
    future = _flat_forecast(2000.0, date(2028, 6, 1))        # online at month 24
    months, totals = aggregate([producing, future], horizon_months=36, origin=origin)

    assert months[0] == origin
    assert 950.0 < totals[0] < 1050.0          # month 0: only the producer (~its qi)
    assert totals[23] < 1000.0                 # month 23: future still offline, producer declined
    assert totals[24] - totals[23] > 1500.0    # month 24: future comes online at qi 2000


def test_aggregate_origin_clamps_a_well_already_producing_before_origin():
    """A well whose start_date precedes the origin (a producer flowing at the
    as-of date) lands at month 0, not a negative index."""
    origin = date(2026, 6, 1)
    already_flowing = _flat_forecast(800.0, date(2024, 1, 1))   # started well before origin
    months, totals = aggregate([already_flowing], horizon_months=12, origin=origin)
    assert months[0] == origin
    assert totals[0] > 0.0                     # contributes from month 0, not dropped


def test_project_respects_peak_to_start_offset():
    """A PDP forecast: peak in Jan 2022, anchor at Jan 2024 (24 months post-peak).
    rates[0] must be the rate at t=24, not at t=0 (which would be qi_peak)."""
    curve = fit_curve(
        months=np.arange(36, dtype=float),
        q=1000.0 / np.power(1 + 0.8 * 0.05 * np.arange(36), 1.25),
        stream="oil", b_fixed=0.8,
    )
    f = Forecast(
        curve=curve,
        peak_date=date(2022, 1, 1),
        start_date=date(2024, 1, 1),
        provenance=ForecastProvenance(source="fit"),
    )
    months, rates = project(f, horizon_months=12)
    # rates[0] should be curve evaluated at t=24, NOT t=0.
    # At t=0, rate is qi_peak ≈ 1000. At t=24, it's well below.
    assert rates[0] < 800.0, f"rates[0]={rates[0]} suggests start_date offset was ignored"
    assert months[0] == date(2024, 1, 1)


def test_project_raises_on_zero_horizon():
    f = Forecast(
        curve=DeclineCurve(
            qi_peak=1000.0, di=0.05, b=0.8,
            terminal_di_monthly=0.05 / 12,
            switch_month_from_peak=120.0,
            stream="oil",
            provenance=ForecastProvenance(source="fit"),
        ),
        peak_date=date(2024, 1, 1), start_date=date(2024, 1, 1),
        provenance=ForecastProvenance(source="fit"),
    )
    with pytest.raises(ValueError, match="positive"):
        project(f, horizon_months=0)


def test_project_raises_on_start_before_peak():
    f = Forecast(
        curve=DeclineCurve(
            qi_peak=1000.0, di=0.05, b=0.8,
            terminal_di_monthly=0.05 / 12,
            switch_month_from_peak=120.0,
            stream="oil",
            provenance=ForecastProvenance(source="fit"),
        ),
        peak_date=date(2024, 6, 1), start_date=date(2024, 1, 1),
        provenance=ForecastProvenance(source="fit"),
    )
    with pytest.raises(ValueError, match="pre-peak"):
        project(f, horizon_months=12)


# ── fit_curve_best_b / override_b (added with the 2026-07 b-sourcing change) ──

def _hyp_q(b, n, qi=900.0, di=0.08):
    t = np.arange(n, dtype=float)
    return qi / np.power(1.0 + b * di * t, 1.0 / b)


def test_fit_curve_best_b_recovers_true_b_from_grid():
    from server.valuation.forecast import fit_curve_best_b
    grid = tuple(round(0.30 + 0.05 * i, 2) for i in range(21))
    q = _hyp_q(0.85, 40)
    curve = fit_curve_best_b(np.arange(40, dtype=float), q, stream="oil", b_grid=grid)
    assert abs(curve.b - 0.85) <= 0.051
    assert curve.qi_peak == pytest.approx(900.0, rel=0.05)


def test_fit_curve_best_b_rejects_empty_grid_and_thin_history():
    from server.valuation.forecast import fit_curve_best_b
    q = _hyp_q(0.8, 40)
    with pytest.raises(ValueError, match="b_grid"):
        fit_curve_best_b(np.arange(40, dtype=float), q, stream="oil", b_grid=())
    with pytest.raises(ValueError, match="thin history"):
        fit_curve_best_b(np.arange(4, dtype=float), _hyp_q(0.8, 4), stream="oil",
                         b_grid=(0.8,), min_post_peak_months=9)


def test_override_b_recomputes_switch_and_appends_note():
    from server.valuation.forecast import override_b
    curve = DeclineCurve(
        qi_peak=1000.0, di=0.06, b=0.9, terminal_di_monthly=0.05 / 12,
        switch_month_from_peak=100.0, stream="oil",
        provenance=ForecastProvenance(source="percentile", notes=("x",)),
    )
    out = override_b(curve, 0.5, note="b:test")
    assert out.b == 0.5
    expected = (curve.di / curve.terminal_di_monthly - 1.0) / (0.5 * curve.di)
    assert out.switch_month_from_peak == pytest.approx(expected)
    assert out.qi_peak == curve.qi_peak and out.di == curve.di
    assert out.provenance.notes == ("x", "b:test")
    assert out.provenance.source == "percentile"


def test_override_b_infinite_switch_when_di_below_terminal():
    from server.valuation.forecast import override_b
    curve = DeclineCurve(
        qi_peak=1000.0, di=0.001, b=0.9, terminal_di_monthly=0.05 / 12,
        switch_month_from_peak=float("inf"), stream="oil",
        provenance=ForecastProvenance(source="fit"),
    )
    assert override_b(curve, 0.5, note="n").switch_month_from_peak == float("inf")
