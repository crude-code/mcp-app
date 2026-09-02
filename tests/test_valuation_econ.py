# tests/test_valuation_econ.py
import numpy as np
import pytest
from server.valuation.econ import cashflow_components, compute_gross_revenue, npv


def _net(**kw):
    """The holder's net monthly cashflow — the one component the old
    compute_net_cashflow wrapper returned."""
    return cashflow_components(**kw)["net_cashflow"]


def test_compute_gross_revenue_flat_deck():
    oil_bbl = np.array([100.0, 100.0, 100.0])
    gas_mcf = np.array([200.0, 200.0, 200.0])
    rev = compute_gross_revenue(oil_bbl, gas_mcf, oil_price=75.0, gas_price=3.0,
                                gas_btu_factor=1.0)
    # 100*75 + 200*1.0*3 = 7500 + 600 = 8100 per month
    assert np.allclose(rev, [8100.0, 8100.0, 8100.0])


def test_compute_gross_revenue_converts_mcf_to_mmbtu():
    """Gas volumes are mcf; the benchmark is $/MMBtu — revenue must carry the
    BTU factor (house default 1.05), applied after the diff comes off the deck."""
    from server.valuation import config
    oil_bbl = np.zeros(2)
    gas_mcf = np.array([1000.0, 1000.0])
    rev = compute_gross_revenue(oil_bbl, gas_mcf, oil_price=75.0, gas_price=4.0,
                                gas_diff=0.5, gas_btu_factor=1.2)
    assert np.allclose(rev, 1000.0 * 1.2 * 3.5)
    # Default comes from config.ECON, not a hardcoded 1.0.
    rev_default = compute_gross_revenue(oil_bbl, gas_mcf, oil_price=75.0, gas_price=4.0)
    assert np.allclose(rev_default, 1000.0 * config.ECON.gas_btu_factor * 4.0)


def test_net_cashflow_wi():
    gross_rev = np.array([10_000.0, 10_000.0])
    cf = _net(
        gross_rev=gross_rev,
        interest_type="wi",
        wi_pct=0.50, nri_pct=0.40,
        capex_per_month=np.array([8_000_000.0, 0.0]),
        opex_per_month=np.array([0.0, 0.0]),
        tax_pct=0.075, gpt_pct=0.05,
    )
    # Month 0: rev × NRI − capex − sev × rev × NRI − gpt × rev × WI
    # net_rev = 10000 * 0.40 = 4000
    # sev = 0.075 * 10000 * 0.40 = 300; gpt = 0.05 * 10000 * 0.50 = 250
    # cf[0] = 4000 - 8_000_000 - 300 - 250 = -7_996_550
    assert cf[0] < -7_900_000
    assert cf[1] > 0


def test_net_cashflow_minerals():
    gross_rev = np.array([10_000.0, 10_000.0])
    cf = _net(
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


def test_net_cashflow_wi_missing_params_raises():
    with pytest.raises(ValueError, match="wi_pct"):
        _net(gross_rev=np.array([1.0]), interest_type="wi")


def test_net_cashflow_minerals_missing_decimal_raises():
    with pytest.raises(ValueError, match="decimal"):
        _net(gross_rev=np.array([1.0]), interest_type="minerals")


def test_net_cashflow_unknown_type_raises():
    with pytest.raises(ValueError, match="unknown interest_type"):
        _net(gross_rev=np.array([1.0]), interest_type="npi")


def test_cashflow_components_wi_breaks_out_line_items():
    from server.valuation.econ import cashflow_components
    gross = np.array([10_000.0, 10_000.0])
    comp = cashflow_components(
        gross_rev=gross, interest_type="wi", wi_pct=0.5, nri_pct=0.4,
        capex_per_month=np.array([8_000_000.0, 0.0]), opex_per_month=np.array([0.0, 0.0]),
        tax_pct=0.075, gpt_pct=0.05,
    )
    assert np.allclose(comp["net_rev"], gross * 0.4)
    # Severance follows revenue interest (NRI); GPT stays on the WI share
    # (cost-free-royalty convention).
    assert np.allclose(comp["sev_tax"], 0.075 * gross * 0.4)
    assert np.allclose(comp["gpt"], 0.05 * gross * 0.5)
    expected_net = gross * 0.4 - 0.075 * gross * 0.4 - 0.05 * gross * 0.5 - np.array([8_000_000.0, 0.0])
    assert np.allclose(comp["net_cashflow"], expected_net)


def test_severance_sums_to_exactly_one_tax_across_cap_table():
    """A 100% WI / 75% NRI well with a 25% royalty: the WI's severance plus the
    royalty's severance must equal tax × gross exactly — no double taxation."""
    from server.valuation.econ import cashflow_components
    gross = np.array([10_000.0])
    wi = cashflow_components(gross_rev=gross, interest_type="wi",
                             wi_pct=1.0, nri_pct=0.75, tax_pct=0.075, gpt_pct=0.0)
    roy = cashflow_components(gross_rev=gross, interest_type="minerals",
                              decimal=0.25, tax_pct=0.075, gpt_pct=0.0)
    assert np.allclose(wi["sev_tax"] + roy["sev_tax"], 0.075 * gross)


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
