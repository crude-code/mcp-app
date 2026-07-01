from server.valuation.artifact_payload import build_artifact_payload

WELLS = {"well_meta": {"A": {"status": "PRODUCING", "operator": "SURGEON ENERGY",
                              "basin": "MIDLAND", "formation": "WOLFCAMP"}}}


def _economics(**overrides):
    base = {
        "rate_centers": {"PDP": 0.175, "DUC": 0.225, "PUD": 0.275},
        "interest": {"interest_type": "wi", "wi_pct": 0.25, "nri_pct": 0.1875},
        "schedule": {"origin": "2026-07-01", "totals": {
            "net_oil": [100.0] * 360, "net_gas": [50.0] * 360,
            "net_cashflow": [1000.0] * 360}},
        "horizon_months": 360,
        "npv_at_centers": {"by_status": {"PDP": 20e6, "DUC": 4e6, "PUD": 3e6}, "total": 27e6},
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


def test_build_artifact_payload_excludes_cube_and_bucket_detail():
    payload = build_artifact_payload(economics=_economics(), wells=WELLS)
    assert "cube" not in payload
    assert "statuses" not in payload
    assert set(payload) == {"facts", "production", "economics"}
