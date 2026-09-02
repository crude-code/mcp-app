"""forecast.py — the calculator. Curves are built as literals or via
make_curve; there is no fitting to test anymore."""
import numpy as np
import pytest
from datetime import date

from server.valuation.forecast import curve_rate, make_curve, make_zero_curve, project
from server.valuation.types import DeclineCurve, Forecast, ForecastProvenance


def _curve(qi=1000.0, di=0.05, b=0.8, switch=120.0, stream="oil"):
    return DeclineCurve(
        qi=qi, di=di, b=b,
        terminal_di_monthly=0.05 / 12,
        switch_month_from_peak=switch,
        stream=stream,
        provenance=ForecastProvenance(source="asserted", strategy="asserted"),
    )


# ── make_curve: the switch-month formula's one home ──────────────────────────

def test_make_curve_switch_month_closed_form():
    # di=0.05/mo vs terminal 0.05/12/mo, b=1.0 → switch = (12−1)/0.05 = 220.
    c = make_curve(1000.0, 0.05, 1.0, stream="oil", terminal_di_annual=0.05)
    assert c.switch_month_from_peak == pytest.approx(220.0)
    assert c.terminal_di_monthly == pytest.approx(0.05 / 12)
    assert c.provenance.source == "asserted"


def test_make_curve_b_zero_is_exponential_never_switches():
    c = make_curve(1000.0, 0.05, 0.0, stream="oil", terminal_di_annual=0.05)
    assert c.switch_month_from_peak == float("inf")
    # b≈0 branch: q(t) = qi·e^(−di·t)
    assert curve_rate(c, 12.0) == pytest.approx(1000.0 * np.exp(-0.05 * 12))


def test_make_curve_di_at_or_below_terminal_never_switches():
    c = make_curve(1000.0, 0.001, 1.0, stream="oil", terminal_di_annual=0.05)
    assert c.switch_month_from_peak == float("inf")


def test_make_zero_curve_is_flat_zero():
    z = make_zero_curve("gas")
    assert z.qi == 0.0
    assert curve_rate(z, 0.0) == 0.0 and curve_rate(z, 240.0) == 0.0
    assert z.provenance.strategy == "not_asserted"


# ── curve_rate ───────────────────────────────────────────────────────────────

def test_curve_rate_scalar_and_array():
    curve = _curve()
    assert curve_rate(curve, 0.0) == 1000.0  # qi at t=0
    arr = curve_rate(curve, np.array([0.0, 12.0, 24.0]))
    assert arr.shape == (3,)
    assert arr[0] > arr[1] > arr[2]


def test_curve_rate_rejects_negative_t():
    with pytest.raises(ValueError, match="negative t"):
        curve_rate(_curve(), -1.0)


def test_curve_rate_terminal_tail_is_exponential():
    c = make_curve(1000.0, 0.05, 1.0, stream="oil", terminal_di_annual=0.05)
    switch = c.switch_month_from_peak
    q_sw = curve_rate(c, switch)
    # 12 months past the switch the rate follows exp(−terminal · 12).
    assert curve_rate(c, switch + 12.0) == pytest.approx(q_sw * np.exp(-c.terminal_di_monthly * 12))


# ── project ──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_project_horizon_months():
    f = Forecast(curve=_curve(), start_date=date(2024, 1, 1))
    months, rates = project(f, horizon_months=360)
    assert len(months) == 360
    assert len(rates) == 360
    assert rates[0] == pytest.approx(1000.0)     # anchor rate: q(0) == qi
    assert rates[0] > rates[-1]                  # decline


def test_project_raises_on_zero_horizon():
    f = Forecast(curve=_curve(), start_date=date(2024, 1, 1))
    with pytest.raises(ValueError, match="positive"):
        project(f, horizon_months=0)
