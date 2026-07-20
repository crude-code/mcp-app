"""Case file parser tests."""
import pytest
from server.valuation.casefile import parse_case_file, CaseFileError, MAX_ASSET_WELLS


def _minimal_wi():
    return {
        "interest_type": "wi",
        "interest": {"wi_pct": 0.25, "nri_pct": 0.1875},
        "asset_list": {"well_apis": ["42-389-12345"]},
        "transcript": [{"role": "user", "content": "value these"}],
        "queries_run": [],
        "handoff": "value EOG Reeves wells",
    }


def _minimal_minerals():
    return {
        "interest_type": "minerals",
        "interest": {"decimal": 0.01875},
        "asset_list": {"filter_sql": "WHERE operator='EOG'"},
        "transcript": [{"role": "user", "content": "what's this worth"}],
        "queries_run": [],
        "handoff": "value EOG mineral position",
    }


def test_parse_minimal_wi_passes():
    cf = parse_case_file(_minimal_wi())
    assert cf.interest_type == "wi"
    assert cf.interest == {"wi_pct": 0.25, "nri_pct": 0.1875}
    assert cf.asset_list["well_apis"] == ["42-389-12345"]


def test_parse_minimal_minerals_passes():
    cf = parse_case_file(_minimal_minerals())
    assert cf.interest_type == "minerals"
    assert cf.interest == {"decimal": 0.01875}


def test_interest_type_must_be_enum():
    body = _minimal_wi()
    body["interest_type"] = "royalty"
    with pytest.raises(CaseFileError, match="interest_type"):
        parse_case_file(body)


def test_wi_interest_requires_wi_and_nri():
    body = _minimal_wi()
    body["interest"] = {"wi_pct": 0.25}
    with pytest.raises(CaseFileError, match="nri_pct"):
        parse_case_file(body)


def test_minerals_interest_requires_decimal():
    body = _minimal_minerals()
    body["interest"] = {}
    with pytest.raises(CaseFileError, match="decimal"):
        parse_case_file(body)


def test_asset_list_requires_exactly_one_of_apis_or_sql():
    body = _minimal_wi()
    body["asset_list"] = {}
    with pytest.raises(CaseFileError, match="well_apis"):
        parse_case_file(body)
    body["asset_list"] = {"well_apis": ["x"], "filter_sql": "WHERE 1=1"}
    with pytest.raises(CaseFileError, match="exactly one"):
        parse_case_file(body)


def test_interests_must_be_in_zero_to_one():
    body = _minimal_wi()
    body["interest"]["wi_pct"] = 1.5
    with pytest.raises(CaseFileError, match="0.*1"):
        parse_case_file(body)


def test_handoff_required():
    body = _minimal_wi()
    del body["handoff"]
    with pytest.raises(CaseFileError, match="handoff"):
        parse_case_file(body)


def test_transcript_required_nonempty():
    body = _minimal_wi()
    body["transcript"] = []
    with pytest.raises(CaseFileError, match="transcript"):
        parse_case_file(body)


def test_economics_overrides_optional():
    body = _minimal_wi()
    cf = parse_case_file(body)
    assert cf.economics_overrides == {}


def test_economics_overrides_passed_through():
    body = _minimal_wi()
    body["economics_overrides"] = {"tax_pct": 0.08}
    cf = parse_case_file(body)
    assert cf.economics_overrides == {"tax_pct": 0.08}


# ── pinned economic schema (economics_overrides is the single input surface) ──

def test_economics_overrides_unknown_key_rejected():
    body = _minimal_wi()
    body["economics_overrides"] = {"oil_price": 80}        # not a real field — typo for price_deck
    with pytest.raises(CaseFileError, match="unknown key"):
        parse_case_file(body)


def test_price_deck_flat_passes():
    body = _minimal_wi()
    body["economics_overrides"] = {"price_deck": {"type": "flat", "oil_usd_bbl": 80, "gas_usd_mmbtu": 3.5}}
    cf = parse_case_file(body)
    assert cf.economics_overrides["price_deck"]["oil_usd_bbl"] == 80


def test_price_deck_strip_rejects_flat_keys():
    body = _minimal_wi()
    body["economics_overrides"] = {"price_deck": {"type": "strip", "oil_usd_bbl": 80}}
    with pytest.raises(CaseFileError, match="type 'strip' takes no price keys"):
        parse_case_file(body)


def test_price_deck_negative_price_rejected():
    body = _minimal_wi()
    body["economics_overrides"] = {"price_deck": {"type": "flat", "oil_usd_bbl": -5}}
    with pytest.raises(CaseFileError, match="price_deck.oil_usd_bbl must be non-negative"):
        parse_case_file(body)


def test_diffs_pass_and_allow_premium():
    body = _minimal_wi()
    # positive = discount off the deck; negative = premium (realizes above benchmark)
    body["economics_overrides"] = {"oil_diff": 4.0, "gas_diff": -0.25}
    cf = parse_case_file(body)
    assert (cf.economics_overrides["oil_diff"], cf.economics_overrides["gas_diff"]) == (4.0, -0.25)


def test_diff_must_be_a_number():
    body = _minimal_wi()
    body["economics_overrides"] = {"oil_diff": "4"}
    with pytest.raises(CaseFileError, match="oil_diff must be a number"):
        parse_case_file(body)


def test_forecast_horizon_bounds():
    for bad in (0, 601, 12.5, True, "120"):
        body = _minimal_wi()
        body["economics_overrides"] = {"forecast_horizon": bad}
        with pytest.raises(CaseFileError, match="forecast_horizon"):
            parse_case_file(body)
    body = _minimal_wi()
    body["economics_overrides"] = {"forecast_horizon": 240}
    assert parse_case_file(body).economics_overrides["forecast_horizon"] == 240


def test_tax_and_gpt_must_be_fraction():
    for k in ("tax_pct", "gpt_pct"):
        for bad in (1.0, -0.1, "0.05", True):
            body = _minimal_wi()
            body["economics_overrides"] = {k: bad}
            with pytest.raises(CaseFileError, match=k):
                parse_case_file(body)


def test_costs_must_be_non_negative():
    for k in ("opex_per_bbl_usd", "opex_per_well_per_month_usd", "capex_per_well_usd"):
        body = _minimal_wi()
        body["economics_overrides"] = {k: -1}
        with pytest.raises(CaseFileError, match=k):
            parse_case_file(body)


def test_effective_date_must_be_iso():
    body = _minimal_wi()
    body["economics_overrides"] = {"effective_date": "08/01/2026"}
    with pytest.raises(CaseFileError, match="effective_date"):
        parse_case_file(body)
    body = _minimal_wi()
    body["economics_overrides"] = {"effective_date": "2026-08-01"}
    assert parse_case_file(body).economics_overrides["effective_date"] == "2026-08-01"


def test_discount_rates_map_passes():
    body = _minimal_wi()
    body["economics_overrides"] = {"discount_rates": {"PUD": 0.25, "DUC": 0.20}}
    cf = parse_case_file(body)
    assert cf.economics_overrides["discount_rates"] == {"PUD": 0.25, "DUC": 0.20}


def test_discount_rates_absent_ok():
    body = _minimal_wi()
    body["economics_overrides"] = {}
    cf = parse_case_file(body)
    assert "discount_rates" not in cf.economics_overrides


def test_discount_rates_list_rejected():
    # The old flat-list form is retired — discount_rates must be a per-status map.
    body = _minimal_wi()
    body["economics_overrides"] = {"discount_rates": [0.10, 0.15]}
    with pytest.raises(CaseFileError, match="discount_rates must be an object"):
        parse_case_file(body)


def test_discount_rates_unknown_status_rejected():
    body = _minimal_wi()
    body["economics_overrides"] = {"discount_rates": {"PDNP": 0.15}}
    with pytest.raises(CaseFileError, match="unknown status"):
        parse_case_file(body)


def test_discount_rates_value_out_of_range_rejected():
    for bad in (0, 1, -0.1, 1.5, "0.2", True):
        body = _minimal_wi()
        body["economics_overrides"] = {"discount_rates": {"PUD": bad}}
        with pytest.raises(CaseFileError, match="discount_rates"):
            parse_case_file(body)


# ── per-status online-timing override (months_to_first_prod) ───────────────

def test_months_to_first_prod_map_passes():
    body = _minimal_wi()
    body["economics_overrides"] = {"months_to_first_prod": {"PUD": 1, "DUC": 6}}
    cf = parse_case_file(body)
    assert cf.economics_overrides["months_to_first_prod"] == {"PUD": 1, "DUC": 6}


def test_months_to_first_prod_zero_allowed():
    body = _minimal_wi()
    body["economics_overrides"] = {"months_to_first_prod": {"PUD": 0}}
    assert parse_case_file(body).economics_overrides["months_to_first_prod"] == {"PUD": 0}


def test_months_to_first_prod_must_be_object():
    body = _minimal_wi()
    body["economics_overrides"] = {"months_to_first_prod": 12}
    with pytest.raises(CaseFileError, match="months_to_first_prod must be an object"):
        parse_case_file(body)


def test_months_to_first_prod_rejects_pdp():
    body = _minimal_wi()
    body["economics_overrides"] = {"months_to_first_prod": {"PDP": 1}}
    with pytest.raises(CaseFileError, match="cannot set 'PDP'"):
        parse_case_file(body)


def test_months_to_first_prod_unknown_status_rejected():
    body = _minimal_wi()
    body["economics_overrides"] = {"months_to_first_prod": {"PDNP": 1}}
    with pytest.raises(CaseFileError, match="unknown status"):
        parse_case_file(body)


def test_months_to_first_prod_value_must_be_nonneg_int():
    for bad in (-1, 1.5, "2", True, None):
        body = _minimal_wi()
        body["economics_overrides"] = {"months_to_first_prod": {"PUD": bad}}
        with pytest.raises(CaseFileError, match="months_to_first_prod"):
            parse_case_file(body)


# ── per-well interest (by_api overrides) ───────────────────────────────────

def test_wi_by_api_overrides_accepted():
    body = _minimal_wi()
    body["interest"]["by_api"] = {"42-389-12345": {"wi_pct": 0.5, "nri_pct": 0.375}}
    cf = parse_case_file(body)
    assert cf.interest["by_api"]["42-389-12345"] == {"wi_pct": 0.5, "nri_pct": 0.375}
    # blanket still present as the default for unlisted wells
    assert cf.interest["wi_pct"] == 0.25


def test_minerals_by_api_overrides_accepted():
    body = _minimal_minerals()
    body["interest"]["by_api"] = {"42-389-12345": 0.005, "42-389-67890": 0.02}
    cf = parse_case_file(body)
    assert cf.interest["by_api"]["42-389-12345"] == 0.005
    assert cf.interest["by_api"]["42-389-67890"] == 0.02


def test_wi_by_api_entry_requires_wi_and_nri():
    body = _minimal_wi()
    body["interest"]["by_api"] = {"42-389-12345": {"wi_pct": 0.5}}
    with pytest.raises(CaseFileError, match="nri_pct"):
        parse_case_file(body)


def test_wi_by_api_value_out_of_range_rejected():
    body = _minimal_wi()
    body["interest"]["by_api"] = {"42-389-12345": {"wi_pct": 1.5, "nri_pct": 0.375}}
    with pytest.raises(CaseFileError, match="wi_pct"):
        parse_case_file(body)


def test_minerals_by_api_value_out_of_range_rejected():
    body = _minimal_minerals()
    body["interest"]["by_api"] = {"42-389-12345": 1.2}
    with pytest.raises(CaseFileError, match="by_api"):
        parse_case_file(body)


def test_minerals_by_api_value_must_be_number():
    body = _minimal_minerals()
    body["interest"]["by_api"] = {"42-389-12345": {"decimal": 0.01}}
    with pytest.raises(CaseFileError, match="by_api"):
        parse_case_file(body)


def test_by_api_must_be_object():
    body = _minimal_wi()
    body["interest"]["by_api"] = [["42-389-12345", 0.5]]
    with pytest.raises(CaseFileError, match="by_api"):
        parse_case_file(body)


# ── well_facts (per-well DB overrides) ─────────────────────────────────────

def test_well_facts_absent_defaults_empty():
    cf = parse_case_file(_minimal_wi())
    assert cf.well_facts == {}


def test_well_facts_valid_lateral_passes():
    body = _minimal_wi()
    body["well_facts"] = {"42-389-12345": {"lateral_ft": 15398}}
    cf = parse_case_file(body)
    assert cf.well_facts == {"42-389-12345": {"lateral_ft": 15398}}


def test_well_facts_must_be_object():
    body = _minimal_wi()
    body["well_facts"] = [{"api": "42-389-12345", "lateral_ft": 15398}]
    with pytest.raises(CaseFileError, match="well_facts must be an object"):
        parse_case_file(body)


def test_well_facts_entry_must_be_object():
    body = _minimal_wi()
    body["well_facts"] = {"42-389-12345": 15398}
    with pytest.raises(CaseFileError, match=r"well_facts\[.*\] must be an object"):
        parse_case_file(body)


def test_well_facts_lateral_ft_must_be_positive():
    for bad in (0, -100, "15398", True):
        body = _minimal_wi()
        body["well_facts"] = {"42-389-12345": {"lateral_ft": bad}}
        with pytest.raises(CaseFileError, match="lateral_ft"):
            parse_case_file(body)


def test_well_facts_rejects_unknown_subkey():
    body = _minimal_wi()
    body["well_facts"] = {"42-389-12345": {"lateral_length": 15398}}
    with pytest.raises(CaseFileError, match="unknown key"):
        parse_case_file(body)


# ── well_apis cap, type-check, dedupe ──────────────────────────────────────

def test_well_apis_rejects_bare_string():
    body = _minimal_wi()
    body["asset_list"] = {"well_apis": "4212345678"}
    with pytest.raises(CaseFileError, match="list"):
        parse_case_file(body)


def test_well_apis_rejects_over_cap():
    apis = [f"42-{i:09d}" for i in range(MAX_ASSET_WELLS + 1)]
    body = _minimal_wi()
    body["asset_list"] = {"well_apis": apis}
    with pytest.raises(CaseFileError, match="at most"):
        parse_case_file(body)


def test_well_apis_dedupes_preserving_order():
    body = _minimal_wi()
    body["asset_list"] = {"well_apis": ["A", "B", "A", "C"]}
    cf = parse_case_file(body)
    assert cf.asset_list["well_apis"] == ["A", "B", "C"]
