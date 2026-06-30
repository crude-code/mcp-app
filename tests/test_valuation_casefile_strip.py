import pytest

from server.valuation.casefile import parse_run_params, CaseFileError

_BASE = {"interest_type": "minerals", "interest": {"decimal": 0.01},
         "asset_list": {"well_apis": ["30-000-00001"]}}


def test_strip_price_deck_is_accepted():
    cf = parse_run_params({**_BASE, "economics_overrides": {"price_deck": {"type": "strip"}}})
    assert cf.economics_overrides["price_deck"]["type"] == "strip"


def test_absent_price_deck_is_accepted():
    cf = parse_run_params({**_BASE, "economics_overrides": {}})
    assert "price_deck" not in cf.economics_overrides


def test_flat_price_deck_still_accepted():
    cf = parse_run_params({**_BASE, "economics_overrides": {
        "price_deck": {"type": "flat", "oil_usd_bbl": 65, "gas_usd_mmbtu": 3.0}}})
    assert cf.economics_overrides["price_deck"]["oil_usd_bbl"] == 65


def test_strip_rejects_flat_only_keys():
    with pytest.raises(CaseFileError):
        parse_run_params({**_BASE, "economics_overrides": {
            "price_deck": {"type": "strip", "oil_usd_bbl": 65}}})


def test_unknown_deck_type_rejected():
    with pytest.raises(CaseFileError):
        parse_run_params({**_BASE, "economics_overrides": {"price_deck": {"type": "futures"}}})
