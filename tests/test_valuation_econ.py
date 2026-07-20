# tests/test_valuation_econ.py
import numpy as np
import pytest
from server.valuation.econ import compute_gross_revenue, compute_net_cashflow, npv


def test_compute_gross_revenue_flat_deck():
    oil_bbl = np.array([100.0, 100.0, 100.0])
    gas_mcf = np.array([200.0, 200.0, 200.0])
    rev = compute_gross_revenue(oil_bbl, gas_mcf, oil_price=75.0, gas_price=3.0)
    # 100*75 + 200*3 = 7500 + 600 = 8100 per month
    assert np.allclose(rev, [8100.0, 8100.0, 8100.0])


def test_compute_net_cashflow_wi():
    gross_rev = np.array([10_000.0, 10_000.0])
    cf = compute_net_cashflow(
        gross_rev=gross_rev,
        interest_type="wi",
        wi_pct=0.50, nri_pct=0.40,
        capex_per_month=np.array([8_000_000.0, 0.0]),
        opex_per_month=np.array([0.0, 0.0]),
        tax_pct=0.075, gpt_pct=0.05,
    )
    # Month 0: rev × NRI − capex − tax × rev × WI
    # net_rev = 10000 * 0.40 = 4000
    # taxes = (0.075 + 0.05) * 10000 * 0.50 = 625
    # cf[0] = 4000 - 8_000_000 - 625 = -7_996_625
    assert cf[0] < -7_900_000
    assert cf[1] > 0


def test_compute_net_cashflow_minerals():
    gross_rev = np.array([10_000.0, 10_000.0])
    cf = compute_net_cashflow(
        gross_rev=gross_rev,
        interest_type="minerals",
        decimal=0.05,
        capex_per_month=np.array([0.0, 0.0]),    # mineral owners pay no capex
        opex_per_month=np.array([0.0, 0.0]),
        tax_pct=0.075, gpt_pct=0.0,              # mineral owners pay no GPT
    )
    # cf = rev * decimal - tax_pct * rev * decimal = 10000 * 0.05 * (1 - 0.075) = 462.5
    assert np.allclose(cf, [462.5, 462.5])


def test_npv_discounts_correctly():
    # Constant cashflow of $100/month for 12 months at 10% annual
    cf = np.full(12, 100.0)
    assert abs(npv(cf, annual_rate=0.10) - 1_136.78) < 1.0  # rough check
    # PV0 == sum (no discount)
    assert abs(npv(cf, annual_rate=0.0) - 1_200.0) < 0.01


def test_compute_net_cashflow_wi_missing_params_raises():
    with pytest.raises(ValueError, match="wi_pct"):
        compute_net_cashflow(gross_rev=np.array([1.0]), interest_type="wi")


def test_compute_net_cashflow_minerals_missing_decimal_raises():
    with pytest.raises(ValueError, match="decimal"):
        compute_net_cashflow(gross_rev=np.array([1.0]), interest_type="minerals")


def test_compute_net_cashflow_unknown_type_raises():
    with pytest.raises(ValueError, match="unknown interest_type"):
        compute_net_cashflow(gross_rev=np.array([1.0]), interest_type="npi")


def test_cashflow_components_wi_breaks_out_line_items():
    from server.valuation.econ import cashflow_components
    gross = np.array([10_000.0, 10_000.0])
    comp = cashflow_components(
        gross_rev=gross, interest_type="wi", wi_pct=0.5, nri_pct=0.4,
        capex_per_month=np.array([8_000_000.0, 0.0]), opex_per_month=np.array([0.0, 0.0]),
        tax_pct=0.075, gpt_pct=0.05,
    )
    assert np.allclose(comp["net_rev"], gross * 0.4)
    assert np.allclose(comp["sev_tax"], 0.075 * gross * 0.5)
    assert np.allclose(comp["gpt"], 0.05 * gross * 0.5)
    expected_net = gross * 0.4 - 0.075 * gross * 0.5 - 0.05 * gross * 0.5 - np.array([8_000_000.0, 0.0])
    assert np.allclose(comp["net_cashflow"], expected_net)


def test_cashflow_components_minerals_no_gpt_capex_opex():
    from server.valuation.econ import cashflow_components
    gross = np.array([10_000.0])
    comp = cashflow_components(
        gross_rev=gross, interest_type="minerals", decimal=0.05,
        capex_per_month=np.array([999.0]), opex_per_month=np.array([999.0]),
        tax_pct=0.075, gpt_pct=0.05,
    )
    assert comp["gpt"][0] == 0.0
    assert comp["capex"][0] == 0.0      # ignored for minerals
    assert comp["opex"][0] == 0.0
    assert np.allclose(comp["net_cashflow"], gross * 0.05 * (1 - 0.075))


def test_compute_net_cashflow_matches_components():
    from server.valuation.econ import cashflow_components, compute_net_cashflow
    gross = np.array([10_000.0, 9_000.0])
    kw = dict(gross_rev=gross, interest_type="wi", wi_pct=0.5, nri_pct=0.4,
              capex_per_month=np.array([1_000.0, 0.0]), opex_per_month=np.array([200.0, 200.0]))
    assert np.allclose(compute_net_cashflow(**kw), cashflow_components(**kw)["net_cashflow"])


# ── per-well interest resolution (blanket + by_api overrides) ──────────────

from server.valuation.econ import resolve_well_interest


def test_resolve_wi_blanket_when_no_override():
    eff = resolve_well_interest("wi", "A", wi_pct=0.25, nri_pct=0.1875, by_api=None)
    assert eff == {"wi_pct": 0.25, "nri_pct": 0.1875}


def test_resolve_wi_by_api_override_wins():
    eff = resolve_well_interest(
        "wi", "A", wi_pct=0.25, nri_pct=0.1875,
        by_api={"A": {"wi_pct": 0.5, "nri_pct": 0.375}},
    )
    assert eff == {"wi_pct": 0.5, "nri_pct": 0.375}


def test_resolve_wi_unlisted_well_falls_back_to_blanket():
    eff = resolve_well_interest(
        "wi", "B", wi_pct=0.25, nri_pct=0.1875,
        by_api={"A": {"wi_pct": 0.5, "nri_pct": 0.375}},
    )
    assert eff == {"wi_pct": 0.25, "nri_pct": 0.1875}


def test_resolve_minerals_blanket_when_no_override():
    eff = resolve_well_interest("minerals", "A", decimal=0.01, by_api=None)
    assert eff == {"decimal": 0.01}


def test_resolve_minerals_by_api_override_wins():
    eff = resolve_well_interest("minerals", "A", decimal=0.01, by_api={"A": 0.005})
    assert eff == {"decimal": 0.005}
