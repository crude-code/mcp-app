from server.valuation.artifact_payload import build_artifact_payload

WELLS = {"well_meta": {"A": {"status": "PRODUCING", "operator": "SURGEON ENERGY",
                              "basin": "MIDLAND", "formation": "WOLFCAMP"}}}

CUBE = {
    "Strip": {"PDP": {"15": 20e6, "17.5": 19e6, "20": 18e6},
              "DUC": {"20": 4.5e6, "22.5": 4e6, "25": 3.6e6},
              "PUD": {"25": 3.3e6, "27.5": 3e6, "30": 2.7e6}},
    "$70":  {"PDP": {"15": 18e6, "17.5": 17e6, "20": 16e6},
             "DUC": {"20": 4.1e6, "22.5": 3.7e6, "25": 3.3e6},
             "PUD": {"25": 3.0e6, "27.5": 2.7e6, "30": 2.4e6}},
}


def _economics(**overrides):
    base = {
        "rate_centers": {"PDP": 0.175, "DUC": 0.225, "PUD": 0.275},
        "interest": {"interest_type": "wi", "wi_pct": 0.25, "nri_pct": 0.1875},
        "schedule": {"origin": "2026-07-01", "totals": {
            "net_oil": [100.0] * 360, "net_gas": [50.0] * 360,
            "net_cashflow": [1000.0] * 360}},
        "horizon_months": 360,
        "npv_at_centers": {"by_status": {"PDP": 20e6, "DUC": 4e6, "PUD": 3e6}, "total": 27e6},
        "npv_by_status": CUBE,
        "inputs": {"price_mode": "strip"},
    }
    base.update(overrides)
    return base


def test_build_artifact_payload_returns_facts_and_economics():
    payload = build_artifact_payload(economics=_economics(), wells=WELLS)
    assert payload["facts"]["deal_type"] == "Working Interest"
    assert payload["facts"]["operator"] == "Surgeon Energy"
    assert payload["economics"]["npv_at_centers"]["total"] == 27e6


def test_build_artifact_payload_includes_cube_and_scenario_axes():
    econ = _economics(npv_by_status=CUBE, inputs={"price_mode": "strip"})
    payload = build_artifact_payload(economics=econ, wells=WELLS)
    e = payload["economics"]
    assert e["cube"] == CUBE
    assert e["decks"][0] == "Strip"            # base deck first
    assert e["default_deck"] == "Strip"
    # default rate = center rung, formatted like the cube keys ('17.5' style)
    assert e["default_rates"]["PDP"] == "17.5"
    assert set(payload) == {"facts", "economics", "assumptions", "evidence"}


def test_build_artifact_payload_assumptions_and_evidence_passthrough():
    econ = _economics(
        inputs={"price_mode": "strip", "strip_trade_date": "2026-08-11",
                "oil_price": 68.2, "gas_price": 3.1, "oil_diff": 2.5, "gas_diff": 0.0,
                "tax_pct": 0.075, "gpt_pct": 0.05},
        cost_inputs={"capex_per_well": 9.4e6, "opex_per_well_month": 4000.0, "opex_per_bbl": 2.0},
        cashflow_total_undiscounted=41e6,
    )
    econ["schedule"]["totals"]["capex"] = [0.0] * 359 + [235000.0]
    evidence = {"entries": [{"id": "e1", "kind": "producing", "pv": 1.0}]}
    payload = build_artifact_payload(economics=econ, wells={**WELLS, "evidence": evidence})
    a = payload["assumptions"]
    assert a["effective_month"] == "2026-07"
    assert a["price_mode"] == "strip" and a["strip_trade_date"] == "2026-08-11"
    assert a["capex_per_well"] == 9.4e6
    assert a["undiscounted_cashflow"] == 41e6
    assert a["net_capex_total"] == 235000
    assert payload["evidence"] == evidence


def test_build_artifact_payload_statuses_are_data_only():
    econ = _economics(npv_by_status=CUBE, inputs={"price_mode": "strip"})
    payload = build_artifact_payload(economics=econ, wells=WELLS)
    statuses = payload["economics"]["statuses"]
    assert [s["code"] for s in statuses] == ["PDP", "DUC", "PUD"]
    pdp = statuses[0]
    assert set(pdp) == {"code", "label", "tag", "gross_wells", "net_wells", "rates"}
    assert pdp["gross_wells"] == 1
    assert "dot" not in pdp                    # no CSS-var presentation leakage
