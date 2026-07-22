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


def test_build_artifact_payload_includes_production_when_active():
    payload = build_artifact_payload(economics=_economics(), wells=WELLS)
    assert payload["production"] is not None
    assert payload["production"][0]["oil"] == 100.0


def test_build_artifact_payload_omits_production_when_no_activity():
    zeroed = _economics(schedule={"origin": "2026-07-01", "totals": {
        "net_oil": [0.0] * 360, "net_gas": [0.0] * 360, "net_cashflow": [0.0] * 360}})
    payload = build_artifact_payload(economics=zeroed, wells=WELLS)
    assert payload["production"] is None


def test_build_artifact_payload_includes_cube_and_scenario_axes():
    econ = _economics(npv_by_status=CUBE, inputs={"price_mode": "strip"})
    payload = build_artifact_payload(economics=econ, wells=WELLS)
    e = payload["economics"]
    assert e["cube"] == CUBE
    assert e["decks"][0] == "Strip"            # base deck first
    assert e["default_deck"] == "Strip"
    # default rate = center rung, formatted like the cube keys ('17.5' style)
    assert e["default_rates"]["PDP"] == "17.5"
    assert set(payload) == {"facts", "production", "economics"}


def test_build_artifact_payload_statuses_are_data_only():
    econ = _economics(npv_by_status=CUBE, inputs={"price_mode": "strip"})
    payload = build_artifact_payload(economics=econ, wells=WELLS)
    statuses = payload["economics"]["statuses"]
    assert [s["code"] for s in statuses] == ["PDP", "DUC", "PUD"]
    pdp = statuses[0]
    assert set(pdp) == {"code", "label", "tag", "gross_wells", "net_wells", "rates"}
    assert pdp["gross_wells"] == 1
    assert "dot" not in pdp                    # no CSS-var presentation leakage
