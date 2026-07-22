"""Per-well forecast routing — dateless. Classifies a well by its production
shape and returns a DeclineCurve blending its own data with a Claude-supplied
analog type curve. No dates, no calendar placement (run_valuation owns that).

WellState ladder:
    HISTORY       — peaked AND >=9 post-peak months -> own fit, analog lends b;
                    at >=30 post-peak months the well earns its OWN b via a
                    bounded grid fit (strategy "history_own_b") — backtested
                    2026-07: halves holdout MAE vs borrowed b on long histories
    THIN_PEAKED   — peaked AND <9 post-peak months  -> own peak, analog di+b
    CLIMBING      — has production but argmax == last -> max(analog, own_max), analog di+b
    NO_HISTORY    — no production -> analog curve outright

Zero-stream guard (before the ladder): all-zero stream or all-zero-after-peak ->
flat-zero curve (fit_curve would raise; the analog would fabricate volumes).
"""
from enum import Enum
import numpy as np

from server.valuation.forecast import fit_curve, fit_curve_best_b
from server.valuation.types import DeclineCurve, ForecastProvenance


_MIN_POST_PEAK_HISTORY = 9
_SERVER_DEFAULT_B = 0.8
_OWN_B_MIN_POST_PEAK = 30                    # earn your own b above this
B_GRID = tuple(round(0.30 + 0.05 * i, 2) for i in range(21))   # 0.30 … 1.30


class AnalogRequired(Exception):
    """Raised by build_curve when the well's state needs an analog but none given.
    Carries the stream so the orchestrator can bounce with a useful message."""

    def __init__(self, stream: str):
        self.stream = stream
        super().__init__(f"analog required for {stream} stream")


class WellState(str, Enum):
    HISTORY = "history"
    THIN_PEAKED = "thin_peaked"
    CLIMBING = "climbing"
    NO_HISTORY = "no_history"


def classify_well(months: list[str], q: np.ndarray) -> WellState:
    if len(q) == 0:
        return WellState.NO_HISTORY
    peak_idx = int(np.argmax(q))
    if peak_idx == len(q) - 1:
        return WellState.CLIMBING
    if (len(q) - 1 - peak_idx) >= _MIN_POST_PEAK_HISTORY:
        return WellState.HISTORY
    return WellState.THIN_PEAKED


def _zero_curve(stream: str) -> DeclineCurve:
    return DeclineCurve(
        qi_peak=0.0, di=0.0, b=0.0, terminal_di_monthly=0.0,
        switch_month_from_peak=float("inf"), stream=stream,
        provenance=ForecastProvenance(source="rule", strategy="zero_stream"),
    )


def _blend(qi: float, analog: DeclineCurve, stream: str, strategy: str) -> DeclineCurve:
    return DeclineCurve(
        qi_peak=qi, di=analog.di, b=analog.b,
        terminal_di_monthly=analog.terminal_di_monthly,
        switch_month_from_peak=analog.switch_month_from_peak,
        stream=stream,
        provenance=ForecastProvenance(source="blend", strategy=strategy),
    )


def build_curve(months: list[str], q: np.ndarray, *,
                analog: DeclineCurve | None, stream: str) -> tuple[DeclineCurve, WellState, str]:
    """Return (curve, state, strategy). Dateless — caller stores the anchor month
    separately and run_valuation places the curve on the calendar."""
    state = classify_well(months, q)

    if state == WellState.NO_HISTORY:
        if analog is None:
            raise AnalogRequired(stream)
        return analog, state, "pure_analog"

    # Zero-stream guard (producing states only).
    peak_idx = int(np.argmax(q))
    if float(q.sum()) <= 0.0 or (peak_idx < len(q) - 1 and float(q[peak_idx + 1:].sum()) <= 0.0):
        return _zero_curve(stream), state, "zero_stream"

    if state == WellState.HISTORY:
        if (len(q) - 1 - peak_idx) >= _OWN_B_MIN_POST_PEAK:
            curve = fit_curve_best_b(np.arange(len(q), dtype=float), q, stream=stream,
                                     b_grid=B_GRID,
                                     min_post_peak_months=_MIN_POST_PEAK_HISTORY)
            return curve, state, "history_own_b"
        b = analog.b if analog is not None else _SERVER_DEFAULT_B
        curve = fit_curve(np.arange(len(q), dtype=float), q, stream=stream,
                          b_fixed=b, min_post_peak_months=_MIN_POST_PEAK_HISTORY)
        return curve, state, "history"

    if analog is None:
        raise AnalogRequired(stream)

    if state == WellState.THIN_PEAKED:
        return _blend(float(q[peak_idx]), analog, stream, "thin_blend"), state, "thin_blend"

    # CLIMBING
    return _blend(max(analog.qi_peak, float(q.max())), analog, stream, "climbing"), state, "climbing"
