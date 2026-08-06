"""consequences.py — the echo math, hand-checked.

Exponential cases (b=0) are used wherever a closed form exists: q(t) =
qi·e^(−di·t), so every expected number here can be recomputed by hand.
"""
import math
from datetime import date

import pytest

from server.valuation import consequences as cq
from server.valuation.forecast import make_curve, make_zero_curve


def _exp_curve(qi=1000.0, di=0.05):
    # b=0 → pure exponential, no terminal switch (already exponential).
    return make_curve(qi, di, 0.0, stream="oil", terminal_di_annual=0.05)


# ── effective_annual_decline ─────────────────────────────────────────────────

def test_effective_decline_exponential_closed_form():
    c = _exp_curve(di=0.05)
    expected = 1.0 - math.exp(-0.05 * 12)          # ≈ 0.4512
    for year in (1, 5):                             # exponential: same every year
        assert cq.effective_annual_decline(c, year=year) == pytest.approx(expected, rel=1e-9)


def test_effective_decline_zero_curve_is_none():
    z = make_zero_curve("gas")
    assert cq.effective_annual_decline(z, year=1) is None


def test_effective_decline_rejects_year_zero():
    with pytest.raises(ValueError):
        cq.effective_annual_decline(_exp_curve(), year=0)


def test_effective_decline_hyperbolic_declines_shallow_with_age():
    c = make_curve(1000.0, 0.10, 1.0, stream="oil", terminal_di_annual=0.05)
    yr1 = cq.effective_annual_decline(c, year=1)
    yr5 = cq.effective_annual_decline(c, year=5)
    assert yr1 > yr5 > 0.0                          # hyperbolic shallows over time


# ── trailing window / cum-through ────────────────────────────────────────────

_MONTHS = [f"2025-{m:02d}-01" for m in range(1, 13)] + [f"2026-{m:02d}-01" for m in range(1, 7)]
_Q = [100.0] * 18


def test_trailing_window_is_12_months_inclusive():
    got = cq.trailing_window_cum(_MONTHS, _Q, anchor=date(2026, 6, 1))
    assert got == pytest.approx(1200.0)             # 2025-07..2026-06

def test_trailing_window_clips_at_series_start():
    got = cq.trailing_window_cum(_MONTHS, _Q, anchor=date(2025, 3, 1))
    assert got == pytest.approx(300.0)              # only Jan–Mar exist

def test_cum_through_stops_at_anchor():
    got = cq.cum_through(_MONTHS, _Q, anchor=date(2025, 12, 1))
    assert got == pytest.approx(1200.0)

def test_nan_months_are_skipped_not_zeroed():
    q = [100.0, float("nan"), 100.0]
    got = cq.cum_through(["2026-01-01", "2026-02-01", "2026-03-01"], q, anchor=date(2026, 3, 1))
    assert got == pytest.approx(200.0)


# ── allocation shares ────────────────────────────────────────────────────────

def test_allocation_shares_sum_to_one():
    shares = cq.allocation_shares({"a": 900.0, "b": 100.0})
    assert shares == {"a": 0.9, "b": 0.1}
    assert sum(shares.values()) == pytest.approx(1.0)

def test_allocation_shares_reject_nonpositive_member():
    with pytest.raises(ValueError):
        cq.allocation_shares({"a": 900.0, "b": 0.0})


# ── stream_consequences ──────────────────────────────────────────────────────

def test_producer_next12_starts_at_t1():
    c = _exp_curve(qi=1000.0, di=0.05)
    out = cq.stream_consequences(
        c, anchor=date(2026, 5, 1), horizon_months=360,
        trailing_12_actual=14000.0, cum_to_date=50000.0, lateral_ft=10000.0,
    )
    expected_12 = sum(1000.0 * math.exp(-0.05 * t) for t in range(1, 13))
    assert out["next_12_cum"] == pytest.approx(expected_12, abs=0.1)
    assert out["next12_over_trailing12"] == pytest.approx(expected_12 / 14000.0, abs=1e-3)


def test_undrilled_window_starts_at_t0():
    c = _exp_curve(qi=1000.0, di=0.05)
    out = cq.stream_consequences(
        c, anchor=date(2027, 6, 1), horizon_months=360,
        trailing_12_actual=None, cum_to_date=0.0, lateral_ft=None,
        anchor_is_future=True,
    )
    expected_12 = sum(1000.0 * math.exp(-0.05 * t) for t in range(0, 12))
    assert out["next_12_cum"] == pytest.approx(expected_12, abs=0.1)
    assert out["trailing_12_actual"] is None
    assert out["next12_over_trailing12"] is None
    assert out["eur_per_ft"] is None
    assert out["cum_to_date"] == 0.0


def test_eur_is_cum_plus_remaining():
    c = _exp_curve(qi=1000.0, di=0.05)
    out = cq.stream_consequences(
        c, anchor=date(2026, 5, 1), horizon_months=360,
        trailing_12_actual=None, cum_to_date=50000.0, lateral_ft=8000.0,
    )
    assert out["eur"] == pytest.approx(out["cum_to_date"] + out["eur_remaining"], abs=0.2)
    assert out["eur_per_ft"] == pytest.approx(out["eur"] / 8000.0, abs=0.05)


def test_terminal_switch_date_lands_at_anchor_plus_months():
    # di=0.05/mo vs terminal 0.05/yr (0.0041667/mo), b=1.0:
    # switch = (0.05/0.0041667 − 1)/0.05 = 11/0.05 = 220 months.
    c = make_curve(1000.0, 0.05, 1.0, stream="oil", terminal_di_annual=0.05)
    out = cq.stream_consequences(
        c, anchor=date(2026, 1, 1), horizon_months=360,
        trailing_12_actual=None, cum_to_date=0.0, lateral_ft=None,
    )
    assert out["terminal_switch"]["months_from_anchor"] == pytest.approx(220.0, abs=0.1)
    assert out["terminal_switch"]["date"] == "2044-05"   # 2026-01 + 220mo


def test_shallow_di_never_switches():
    c = make_curve(1000.0, 0.001, 1.0, stream="oil", terminal_di_annual=0.05)
    out = cq.stream_consequences(
        c, anchor=date(2026, 1, 1), horizon_months=360,
        trailing_12_actual=None, cum_to_date=0.0, lateral_ft=None,
    )
    assert out["terminal_switch"] == {"months_from_anchor": None, "date": None}


def test_short_horizon_omits_windows():
    c = _exp_curve()
    out = cq.stream_consequences(
        c, anchor=date(2026, 1, 1), horizon_months=6,
        trailing_12_actual=100.0, cum_to_date=0.0, lateral_ft=None,
    )
    assert out["next_12_cum"] is None and out["next_24_cum"] is None
