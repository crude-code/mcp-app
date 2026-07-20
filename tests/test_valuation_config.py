"""Unit tests for valuation dating config — no DB, no agent.

The non-producing-well online-date rule: anchor at the first of the month
*following* the as-of date, then offset by status (DUC = 18mo, PERMITTED = 36mo).
"""
from datetime import date

from server.valuation.config import (
    ECON,
    planned_first_prod_date,
    resolve_as_of,
    resolve_price_inputs,
    status_code,
)


def test_resolve_price_inputs_defaults_when_empty():
    out = resolve_price_inputs({})
    assert out == {
        "horizon_months": ECON.horizon_months,
        "oil_price": ECON.oil_price, "gas_price": ECON.gas_price,
        "oil_diff": ECON.oil_diff, "gas_diff": ECON.gas_diff,
        "tax_pct": ECON.tax_pct, "gpt_pct": ECON.gpt_pct,
    }


def test_resolve_price_inputs_reads_price_deck_and_diffs():
    out = resolve_price_inputs({
        "price_deck": {"type": "flat", "oil_usd_bbl": 80, "gas_usd_mmbtu": 4.0},
        "oil_diff": 4.0, "gas_diff": -0.25,
        "forecast_horizon": 240, "tax_pct": 0.05, "gpt_pct": 0.04,
    })
    assert out["oil_price"] == 80.0 and out["gas_price"] == 4.0
    assert out["oil_diff"] == 4.0 and out["gas_diff"] == -0.25
    assert out["horizon_months"] == 240
    assert out["tax_pct"] == 0.05 and out["gpt_pct"] == 0.04


def test_resolve_price_inputs_handles_none():
    assert resolve_price_inputs(None)["oil_price"] == ECON.oil_price


def test_offsets_are_18_and_36():
    assert ECON.duc_months_to_first_prod == 18
    assert ECON.permit_months_to_first_prod == 36


# ── deal-sheet status bucketing (fork 1) + price decks (fork 3) ──────────────

def test_status_code_maps_well_status_to_deal_sheet_code():
    # The deal sheet's three rows come from public.wells.well_status, NOT the
    # forecast routing classification.
    assert status_code("PRODUCING") == "PDP"
    assert status_code("DUC") == "DUC"
    assert status_code("PERMITTED") == "PUD"


def test_status_code_is_case_insensitive():
    assert status_code("producing") == "PDP"
    assert status_code("  Duc ") == "DUC"


def test_status_code_unknown_falls_back_to_producing_bucket():
    # The ingest only loads PRODUCING/DUC/PERMITTED; anything else (or None)
    # lands in the producing bucket so it never silently vanishes from the cube.
    assert status_code(None) == "PDP"
    assert status_code("ABANDONED") == "PDP"


def test_default_rate_centers_are_pdp15_duc20_pud25():
    from server.valuation.config import ECON
    assert ECON.default_rate_centers == {"PDP": 0.15, "DUC": 0.20, "PUD": 0.25}


def test_rate_spread_is_2_5_pct():
    from server.valuation.config import ECON
    assert ECON.rate_spread == 0.025


def test_rate_ladder_bands_center_by_spread():
    from server.valuation.config import rate_ladder
    assert rate_ladder(0.15) == (0.125, 0.15, 0.175)
    assert rate_ladder(0.25) == (0.225, 0.25, 0.275)


def test_resolve_rate_centers_defaults_when_no_override():
    from server.valuation.config import resolve_rate_centers
    assert resolve_rate_centers({}) == {"PDP": 0.15, "DUC": 0.20, "PUD": 0.25}
    assert resolve_rate_centers(None) == {"PDP": 0.15, "DUC": 0.20, "PUD": 0.25}


def test_resolve_rate_centers_applies_partial_override():
    from server.valuation.config import resolve_rate_centers
    out = resolve_rate_centers({"discount_rates": {"PUD": 0.22}})
    assert out == {"PDP": 0.15, "DUC": 0.20, "PUD": 0.22}


def test_default_deck_label_strip_is_strip():
    from server.valuation.config import default_deck_label
    assert default_deck_label("strip") == "Strip"
    assert default_deck_label("flat") == "Flat"


def test_deck_oil_flat_reference_decks():
    # The cube leads with the base price path (strip/flat), then these flat decks.
    assert ECON.deck_oil_flat == (70.0, 75.0, 80.0)


def test_duc_dated_18_months_from_next_month_first():
    # as-of 2026-05-28 -> anchor 2026-06-01 -> +18mo = 2027-12-01
    assert planned_first_prod_date("DUC", as_of=date(2026, 5, 28)) == date(2027, 12, 1)


def test_permit_dated_36_months_from_next_month_first():
    # as-of 2026-05-28 -> anchor 2026-06-01 -> +36mo = 2029-06-01
    assert planned_first_prod_date("PERMITTED", as_of=date(2026, 5, 28)) == date(2029, 6, 1)


def test_anchor_always_rolls_to_next_month_even_when_as_of_is_a_first():
    # as-of already first-of-month (2026-05-01) -> still rolls to 2026-06-01
    assert planned_first_prod_date("DUC", as_of=date(2026, 5, 1)) == date(2027, 12, 1)


def test_status_is_case_insensitive():
    assert planned_first_prod_date("duc", as_of=date(2026, 5, 28)) == date(2027, 12, 1)
    assert planned_first_prod_date("Permitted", as_of=date(2026, 5, 28)) == date(2029, 6, 1)


def test_producing_or_unknown_status_returns_none():
    # Only DUC / PERMITTED have an online-date basis; everything else is None
    # (the engine has no rule to date it).
    assert planned_first_prod_date("PRODUCING", as_of=date(2026, 5, 28)) is None
    assert planned_first_prod_date(None, as_of=date(2026, 5, 28)) is None
    assert planned_first_prod_date("", as_of=date(2026, 5, 28)) is None


def test_months_override_replaces_permit_delta():
    # {"PUD": 1} pulls a permit online one month after the anchor (2026-06-01)
    # instead of the default +36mo.
    assert planned_first_prod_date(
        "PERMITTED", as_of=date(2026, 5, 28), months_override={"PUD": 1}
    ) == date(2026, 7, 1)


def test_months_override_replaces_duc_delta():
    assert planned_first_prod_date(
        "DUC", as_of=date(2026, 5, 28), months_override={"DUC": 3}
    ) == date(2026, 9, 1)


def test_months_override_only_touches_named_status():
    # A PUD override leaves DUC on its default +18mo.
    ov = {"PUD": 1}
    assert planned_first_prod_date("DUC", as_of=date(2026, 5, 28), months_override=ov) == date(2027, 12, 1)
    assert planned_first_prod_date("PERMITTED", as_of=date(2026, 5, 28), months_override=ov) == date(2026, 7, 1)


def test_months_override_of_zero_lands_on_anchor():
    assert planned_first_prod_date(
        "PERMITTED", as_of=date(2026, 5, 28), months_override={"PUD": 0}
    ) == date(2026, 6, 1)


def test_empty_or_none_override_keeps_defaults():
    assert planned_first_prod_date("DUC", as_of=date(2026, 5, 28), months_override=None) == date(2027, 12, 1)
    assert planned_first_prod_date("DUC", as_of=date(2026, 5, 28), months_override={}) == date(2027, 12, 1)


def test_resolve_as_of_prefers_effective_date_string():
    assert resolve_as_of("2025-01-15", today=date(2026, 5, 28)) == date(2025, 1, 15)


def test_resolve_as_of_accepts_date_object():
    assert resolve_as_of(date(2025, 1, 15), today=date(2026, 5, 28)) == date(2025, 1, 15)


def test_resolve_as_of_falls_back_to_today_when_missing():
    assert resolve_as_of(None, today=date(2026, 5, 28)) == date(2026, 5, 28)


def test_resolve_as_of_falls_back_to_today_on_unparseable():
    assert resolve_as_of("not-a-date", today=date(2026, 5, 28)) == date(2026, 5, 28)


def test_econ_defaults_hold_the_house_economic_assumptions():
    assert ECON.oil_price == 70.0
    assert ECON.gas_price == 3.50
    assert ECON.oil_diff == 0.0
    assert ECON.gas_diff == 0.0
    assert ECON.tax_pct == 0.075
    assert ECON.gpt_pct == 0.05
    assert ECON.opex_per_bbl_usd == 0.0
    assert ECON.opex_per_well_per_month_usd == 0.0
    assert ECON.capex_per_well_usd == 0.0
    assert ECON.horizon_months == 360
