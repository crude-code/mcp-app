import numpy as np
import pytest
from server.valuation.routing import (
    WellState, classify_well, build_curve, AnalogRequired,
)
from server.valuation.types import DeclineCurve, ForecastProvenance


def _analog(stream="oil"):
    return DeclineCurve(
        qi_peak=1000.0, di=0.6, b=1.1, terminal_di_monthly=0.004,
        switch_month_from_peak=120.0, stream=stream,
        provenance=ForecastProvenance(source="percentile", strategy=None),
    )


def test_classify_history_thin_climbing_nohistory():
    # peaked at idx 2, 10 post-peak months -> HISTORY
    q = np.array([5, 8, 12, 11, 10, 9, 8, 7, 6, 5, 4, 3, 2], dtype=float)
    assert classify_well([f"2020-{i:02d}" for i in range(1, 14)], q) == WellState.HISTORY
    # peaked, only 3 post-peak -> THIN_PEAKED
    q2 = np.array([5, 12, 11, 10, 9], dtype=float)
    assert classify_well(["a", "b", "c", "d", "e"], q2) == WellState.THIN_PEAKED
    # last month is the max -> CLIMBING
    q3 = np.array([5, 8, 12], dtype=float)
    assert classify_well(["a", "b", "c"], q3) == WellState.CLIMBING
    # no production -> NO_HISTORY
    assert classify_well([], np.array([], dtype=float)) == WellState.NO_HISTORY


def test_build_curve_no_history_uses_analog_outright():
    curve, state, strat = build_curve([], np.array([], dtype=float),
                                      analog=_analog(), stream="oil")
    assert state == WellState.NO_HISTORY
    assert strat == "pure_analog"
    assert curve.qi_peak == 1000.0 and curve.di == 0.6 and curve.b == 1.1


def test_build_curve_thin_keeps_own_peak_borrows_analog_shape():
    q = np.array([5, 50, 40, 30], dtype=float)  # THIN_PEAKED, own peak = 50
    curve, state, strat = build_curve(["a", "b", "c", "d"], q,
                                      analog=_analog(), stream="oil")
    assert state == WellState.THIN_PEAKED and strat == "thin_blend"
    assert curve.qi_peak == 50.0          # own peak
    assert curve.di == 0.6 and curve.b == 1.1   # analog shape


def test_build_curve_climbing_uses_max_own_analog():
    q = np.array([5, 8, 1500], dtype=float)  # CLIMBING, own max 1500 > analog 1000
    curve, state, strat = build_curve(["a", "b", "c"], q, analog=_analog(), stream="oil")
    assert state == WellState.CLIMBING and strat == "climbing"
    assert curve.qi_peak == 1500.0


def test_build_curve_needs_analog_raises_when_missing():
    with pytest.raises(AnalogRequired):
        build_curve([], np.array([], dtype=float), analog=None, stream="oil")


def test_build_curve_zero_stream_returns_flat_zero():
    q = np.array([0, 0, 0], dtype=float)
    curve, state, strat = build_curve(["a", "b", "c"], q, analog=_analog(), stream="gas")
    assert strat == "zero_stream"
    assert curve.qi_peak == 0.0


def test_build_curve_history_fits_own_with_analog_b():
    q = np.array([5, 80, 70, 60, 50, 44, 40, 36, 33, 30, 28, 26], dtype=float)
    curve, state, strat = build_curve([f"2020-{i:02d}" for i in range(1, 13)], q,
                                      analog=_analog(), stream="oil")
    assert state == WellState.HISTORY and strat == "history"
    assert curve.b == 1.1                 # b borrowed from analog
    assert curve.qi_peak > 0
