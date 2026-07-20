from datetime import date

import numpy as np
import pytest

from server.valuation.orchestrator import (
    _SCHEDULE_COLS,
    _build_schedule,
    _serialize_schedule,
    compose_artifact_payload_for_run,
)


# ── cashflow schedule (audit trail) — pure, no DB ──────────────────────────

def _fcdict(qi, start_iso, stream="oil"):
    """A serialized-forecast dict (run-record shape) with peak == start."""
    return {
        "curve": {
            "qi_peak": qi, "di": 0.05, "b": 0.8, "terminal_di_monthly": 0.05 / 12,
            "switch_month_from_peak": None, "stream": stream,
            "provenance": {"source": "fit", "strategy": "pdp"},
        },
        "peak_date": start_iso, "start_date": start_iso, "strategy": "pdp",
    }


def _well(qi_oil, start_iso):
    return {"oil": _fcdict(qi_oil, start_iso), "gas": _fcdict(0.0, start_iso, "gas")}


def _wi_schedule(forecasts, classifications, *, horizon=36, **overrides):
    kw = dict(
        forecasts=forecasts, classifications=classifications, origin=date(2026, 6, 1),
        horizon=horizon, oil_price=75.0, gas_price=3.0, oil_diff=0.0, gas_diff=0.0,
        interest_type="wi", wi_pct=0.5, nri_pct=0.4, decimal=None,
        tax_pct=0.075, gpt_pct=0.05,
        capex_per_well=0.0, opex_per_well_month=0.0, opex_per_bbl=0.0,
    )
    kw.update(overrides)
    return _build_schedule(**kw)


def test_build_schedule_totals_equal_sum_of_wells():
    """Totals are the elementwise sum of per-well lines (so NPV reconciles)."""
    forecasts = {"a": _well(1000.0, "2026-06-01"), "b": _well(2000.0, "2027-12-01")}
    sched = _wi_schedule(forecasts, {"a": "history", "b": "no_history"},
                         capex_per_well=6_500_000.0)
    for col in _SCHEDULE_COLS:
        assert np.allclose(
            sched["totals"][col],
            sched["by_well"]["a"][col] + sched["by_well"]["b"][col],
        )


def test_build_schedule_capex_hits_non_producing_at_online_month():
    forecasts = {"pdp": _well(1000.0, "2026-06-01"), "duc": _well(1000.0, "2027-12-01")}
    sched = _wi_schedule(forecasts, {"pdp": "history", "duc": "no_history"},
                         capex_per_well=6_500_000.0)
    assert sched["by_well"]["duc"]["capex"][18] == 0.5 * 6_500_000.0  # WI share, online month
    assert sched["by_well"]["pdp"]["capex"].sum() == 0.0              # producing: none


def test_build_schedule_non_producing_well_offline_until_online():
    forecasts = {"duc": _well(1000.0, "2027-12-01")}
    sched = _wi_schedule(forecasts, {"duc": "no_history"})
    oil = sched["by_well"]["duc"]["oil_bbl"]
    assert oil[17] == 0.0    # nothing until it comes online
    assert oil[18] > 0.0     # online at month 18


# ── _serialize_schedule: by_well audit cap at 200 wells ──────────────────────

def test_serialize_schedule_includes_by_well_when_under_cap():
    """≤200 wells: by_well is present and has one entry per well."""
    forecasts = {f"api_{i}": _well(1000.0, "2026-06-01") for i in range(5)}
    sched = _wi_schedule(forecasts, {api: "history" for api in forecasts}, horizon=12)
    origin = date(2026, 6, 1)
    serialized = _serialize_schedule(sched, origin=origin, horizon=12, rate_centers={"PDP": 0.15})
    assert "by_well" in serialized
    assert set(serialized["by_well"].keys()) == set(forecasts.keys())
    assert "totals" in serialized


def test_serialize_schedule_omits_by_well_when_over_cap():
    """201+ wells: by_well is omitted and by_well_omitted note is present; totals always built."""
    n = 201
    forecasts = {f"api_{i}": _well(1000.0, "2026-06-01") for i in range(n)}
    sched = _wi_schedule(forecasts, {api: "history" for api in forecasts}, horizon=12)
    origin = date(2026, 6, 1)
    serialized = _serialize_schedule(sched, origin=origin, horizon=12, rate_centers={"PDP": 0.15})
    assert "by_well" not in serialized
    assert "by_well_omitted" in serialized
    assert "201" in serialized["by_well_omitted"]
    assert "totals" in serialized


def test_serialize_schedule_totals_present_both_sides_of_cap():
    """Totals are built unconditionally — the deal-sheet math depends on them."""
    for n in (1, 200, 201):
        forecasts = {f"api_{i}": _well(1000.0, "2026-06-01") for i in range(n)}
        sched = _wi_schedule(forecasts, {api: "history" for api in forecasts}, horizon=6)
        serialized = _serialize_schedule(sched, origin=date(2026, 6, 1), horizon=6, rate_centers={})
        assert "totals" in serialized, f"totals missing at n={n}"
        assert len(serialized["totals"]["net_cashflow"]) == 6


# ── risked PV cube: per-status NPV across decks × rates (forks 1 + 3) ───────

def test_partition_net_cashflow_buckets_by_status_and_covers_total():
    """Every well's net cashflow lands in exactly one status bucket, and the
    three buckets sum back to the schedule total (nothing lost, nothing double
    counted)."""
    from server.valuation.orchestrator import _partition_net_cashflow
    forecasts = {
        "p": _well(1000.0, "2026-06-01"),
        "d": _well(800.0, "2027-12-01"),
        "x": _well(600.0, "2029-06-01"),
    }
    sched = _wi_schedule(
        forecasts, {"p": "history", "d": "no_history", "x": "no_history"},
        capex_per_well=6_500_000.0,
    )
    statuses = {"p": "PRODUCING", "d": "DUC", "x": "PERMITTED"}
    buckets = _partition_net_cashflow(sched["by_well"], statuses)
    assert set(buckets) == {"PDP", "DUC", "PUD"}
    total = buckets["PDP"] + buckets["DUC"] + buckets["PUD"]
    assert np.allclose(total, sched["totals"]["net_cashflow"])


def test_partition_net_cashflow_groups_multiple_wells_in_one_bucket():
    from server.valuation.orchestrator import _partition_net_cashflow
    forecasts = {"p1": _well(1000.0, "2026-06-01"), "p2": _well(500.0, "2026-06-01")}
    sched = _wi_schedule(forecasts, {"p1": "history", "p2": "history"})
    buckets = _partition_net_cashflow(sched["by_well"], {"p1": "PRODUCING", "p2": "PRODUCING"})
    assert np.allclose(
        buckets["PDP"],
        sched["by_well"]["p1"]["net_cashflow"] + sched["by_well"]["p2"]["net_cashflow"],
    )
    assert np.allclose(buckets["DUC"], 0.0)
    assert np.allclose(buckets["PUD"], 0.0)


def test_status_pv_cube_shape_and_rate_labels():
    from server.valuation.orchestrator import _status_pv_cube
    forecasts = {"p": _well(1000.0, "2026-06-01"), "d": _well(800.0, "2027-12-01")}
    cls = {"p": "history", "d": "no_history"}
    statuses = {"p": "PRODUCING", "d": "DUC"}
    schedules = {
        label: _wi_schedule(forecasts, cls, oil_price=dk, capex_per_well=6_500_000.0)
        for label, dk in [("Strip", 70.0), ("$70", 70.0), ("$75", 75.0), ("$80", 80.0)]
    }
    rate_centers = {"PDP": 0.15, "DUC": 0.20, "PUD": 0.25}
    cube = _status_pv_cube(schedules, statuses, rate_centers)
    assert set(cube) == {"Strip", "$70", "$75", "$80"}
    assert set(cube["Strip"]) == {"PDP", "DUC", "PUD"}
    assert set(cube["Strip"]["PDP"]) == {"12.5", "15", "17.5"}
    assert set(cube["Strip"]["DUC"]) == {"17.5", "20", "22.5"}
    assert set(cube["Strip"]["PUD"]) == {"22.5", "25", "27.5"}


def test_status_pv_cube_value_matches_partition_npv():
    from server.valuation.orchestrator import _status_pv_cube, _partition_net_cashflow
    from server.valuation.econ import npv
    forecasts = {"p": _well(1000.0, "2026-06-01"), "d": _well(800.0, "2027-12-01")}
    cls = {"p": "history", "d": "no_history"}
    statuses = {"p": "PRODUCING", "d": "DUC"}
    schedules = {
        label: _wi_schedule(forecasts, cls, oil_price=dk, capex_per_well=6_500_000.0)
        for label, dk in [("Strip", 70.0), ("$70", 70.0), ("$75", 75.0), ("$80", 80.0)]
    }
    rate_centers = {"PDP": 0.15, "DUC": 0.20, "PUD": 0.25}
    cube = _status_pv_cube(schedules, statuses, rate_centers)
    buckets = _partition_net_cashflow(schedules["Strip"]["by_well"], statuses)
    assert cube["Strip"]["PDP"]["15"] == pytest.approx(npv(buckets["PDP"], annual_rate=0.15))
    assert cube["$80"]["DUC"]["20"] == pytest.approx(npv(
        _partition_net_cashflow(schedules["$80"]["by_well"], statuses)["DUC"], annual_rate=0.20))


def test_status_pv_cube_additive_at_uniform_rate():
    """The reconciliation guarantee: at a single common rate, the per-status
    NPVs sum to the NPV of the total cashflow (exact by linearity). This is what
    licenses the client to just add the three selected cells."""
    from server.valuation.orchestrator import _partition_net_cashflow
    from server.valuation.econ import npv
    forecasts = {
        "p": _well(1000.0, "2026-06-01"),
        "d": _well(800.0, "2027-12-01"),
        "x": _well(600.0, "2029-06-01"),
    }
    sched = _wi_schedule(
        forecasts, {"p": "history", "d": "no_history", "x": "no_history"},
        capex_per_well=6_500_000.0,
    )
    statuses = {"p": "PRODUCING", "d": "DUC", "x": "PERMITTED"}
    buckets = _partition_net_cashflow(sched["by_well"], statuses)
    r = 0.10
    per_status_sum = (
        npv(buckets["PDP"], annual_rate=r)
        + npv(buckets["DUC"], annual_rate=r)
        + npv(buckets["PUD"], annual_rate=r)
    )
    assert per_status_sum == pytest.approx(npv(sched["totals"]["net_cashflow"], annual_rate=r))


def test_compute_npv_by_status_loops_decks_and_holds_gas():
    """The cube is built one schedule per oil band rung, gas held at the supplied
    vector. The 'Strip' deck must equal a direct schedule build at oil=70, gas=3."""
    import numpy as np
    from server.valuation.orchestrator import _compute_npv_by_status, _status_pv_cube
    forecasts = {"p": _well(1000.0, "2026-06-01"), "d": _well(800.0, "2027-12-01")}
    cls = {"p": "history", "d": "no_history"}
    statuses = {"p": "PRODUCING", "d": "DUC"}
    base_kwargs = dict(
        forecasts=forecasts, classifications=cls, origin=date(2026, 6, 1),
        horizon=36, oil_diff=0.0, gas_diff=0.0,
        interest_type="wi", wi_pct=0.5, nri_pct=0.4, decimal=None,
        tax_pct=0.075, gpt_pct=0.05,
        capex_per_well=6_500_000.0, opex_per_well_month=0.0, opex_per_bbl=0.0,
    )
    rate_centers = {"PDP": 0.15, "DUC": 0.20, "PUD": 0.25}
    oil_vec = np.full(36, 70.0)
    gas_vec = np.full(36, 3.0)
    cube = _compute_npv_by_status(
        base_schedule_kwargs=base_kwargs, oil_price_vec=oil_vec, gas_price_vec=gas_vec,
        price_mode="strip", statuses=statuses, rate_centers=rate_centers,
    )
    assert set(cube) == {"Strip", "$70", "$75", "$80"}
    # Reconcile the Strip (base) deck against an independent build at oil=70, gas=3.
    sched_strip = _build_schedule(**base_kwargs, oil_price=70.0, gas_price=3.0)
    expected = _status_pv_cube({"Strip": sched_strip}, statuses, rate_centers)["Strip"]
    assert _flatten_cube_deck(cube["Strip"]) == pytest.approx(_flatten_cube_deck(expected))
    # And a flat reference deck reconciles against a direct flat-oil build (gas held).
    sched_80 = _build_schedule(**base_kwargs, oil_price=80.0, gas_price=3.0)
    expected_80 = _status_pv_cube({"$80": sched_80}, statuses, rate_centers)["$80"]
    assert _flatten_cube_deck(cube["$80"]) == pytest.approx(_flatten_cube_deck(expected_80))


def _flatten_cube_deck(deck: dict) -> dict:
    """pytest.approx can't recurse nested dicts; flatten one deck to scalars."""
    return {f"{c}/{r}": v for c, rates in deck.items() for r, v in rates.items()}


def test_build_schedule_minerals_bear_no_costs():
    forecasts = {"duc": _well(1000.0, "2027-12-01")}
    sched = _build_schedule(
        forecasts=forecasts, classifications={"duc": "no_history"}, origin=date(2026, 6, 1),
        horizon=36, oil_price=75.0, gas_price=3.0, oil_diff=0.0, gas_diff=0.0,
        interest_type="minerals", wi_pct=None, nri_pct=None, decimal=0.05,
        tax_pct=0.075, gpt_pct=0.05,
        capex_per_well=6_500_000.0, opex_per_well_month=5_000.0, opex_per_bbl=8.0,
    )
    assert sched["totals"]["capex"].sum() == 0.0   # minerals never pay capex/opex
    assert sched["totals"]["opex"].sum() == 0.0
    assert sched["totals"]["gpt"].sum() == 0.0


def test_curve_serde_roundtrip_preserves_fields_and_infinity():
    from server.valuation.orchestrator import _serialize_curve, _deserialize_curve
    from server.valuation.types import DeclineCurve, ForecastProvenance
    c = DeclineCurve(
        qi_peak=900.0, di=0.15, b=1.05, terminal_di_monthly=0.004,
        switch_month_from_peak=float("inf"), stream="oil",
        provenance=ForecastProvenance(source="fit", strategy="own_fit"),
    )
    d = _serialize_curve(c)
    assert d["switch_month_from_peak"] is None          # infinity → None for JSON
    back = _deserialize_curve(d)
    assert back.qi_peak == 900.0 and back.b == 1.05 and back.stream == "oil"
    assert back.switch_month_from_peak == float("inf")  # None → infinity on the way back
    assert back.provenance.source == "fit"


def test_compose_artifact_payload_for_run_reads_stages(monkeypatch):
    """compose reads the wells + economics stages and returns the slim payload."""
    economics = {
        "rate_centers": {"PDP": 0.175, "DUC": 0.225, "PUD": 0.275},
        "interest": {"interest_type": "wi", "wi_pct": 0.25, "nri_pct": 0.1875},
        "schedule": {"origin": "2026-07-01", "totals": {
            "net_oil": [100.0] * 360, "net_gas": [50.0] * 360,
            "net_cashflow": [1000.0] * 360}},
        "horizon_months": 360,
        "npv_at_centers": {"by_status": {"PDP": 20e6, "DUC": 4e6, "PUD": 3e6}, "total": 27e6},
        "npv_by_status": {"Strip": {"PDP": {"17.5": 20e6}, "DUC": {"22.5": 4e6}, "PUD": {"27.5": 3e6}}},
        "inputs": {"price_mode": "strip"},
    }
    wells = {"well_meta": {"A": {"status": "PRODUCING", "operator": "SURGEON ENERGY",
                                  "basin": "MIDLAND", "formation": "WOLFCAMP"}}}

    def fake_read_stage(self, run_id, *, stage):
        return {"economics": economics, "wells": wells}.get(stage)
    monkeypatch.setattr(
        "server.valuation.orchestrator.ValuationRunStore.read_stage", fake_read_stage)

    payload = compose_artifact_payload_for_run("r1")
    assert payload["facts"]["deal_type"] == "Working Interest"
    assert payload["production"] is not None
    assert payload["economics"]["npv_at_centers"]["total"] == 27e6


def test_compose_artifact_payload_for_run_raises_without_economics(monkeypatch):
    monkeypatch.setattr(
        "server.valuation.orchestrator.ValuationRunStore.read_stage",
        lambda self, run_id, *, stage: None)
    with pytest.raises(ValueError, match="no economics stage"):
        compose_artifact_payload_for_run("r1")


# ── per-well interest in the schedule (by_api overrides + net volumes) ─────

def test_build_schedule_per_well_interest_override_scales_cashflow():
    # Identical wells; well b carries 2x the WI/NRI via by_api → 2x net cashflow.
    forecasts = {"a": _well(1000.0, "2026-06-01"), "b": _well(1000.0, "2026-06-01")}
    sched = _wi_schedule(
        forecasts, {"a": "history", "b": "history"},
        wi_pct=0.25, nri_pct=0.20,
        by_api={"b": {"wi_pct": 0.5, "nri_pct": 0.40}},
    )
    assert np.allclose(sched["by_well"]["b"]["net_cashflow"],
                       2.0 * sched["by_well"]["a"]["net_cashflow"])


def test_build_schedule_unlisted_well_uses_blanket_interest():
    forecasts = {"a": _well(1000.0, "2026-06-01"), "b": _well(1000.0, "2026-06-01")}
    sched = _wi_schedule(
        forecasts, {"a": "history", "b": "history"},
        wi_pct=0.25, nri_pct=0.20,
        by_api={"b": {"wi_pct": 0.5, "nri_pct": 0.40}},
    )
    # a is not in by_api → same as a pure-blanket schedule's well.
    blanket = _wi_schedule({"a": _well(1000.0, "2026-06-01")}, {"a": "history"},
                           wi_pct=0.25, nri_pct=0.20)
    assert np.allclose(sched["by_well"]["a"]["net_cashflow"],
                       blanket["by_well"]["a"]["net_cashflow"])


def test_build_schedule_net_volume_columns_use_per_well_nri():
    forecasts = {"a": _well(1000.0, "2026-06-01"), "b": _well(1000.0, "2026-06-01")}
    sched = _wi_schedule(
        forecasts, {"a": "history", "b": "history"},
        wi_pct=0.25, nri_pct=0.20,
        by_api={"b": {"wi_pct": 0.5, "nri_pct": 0.40}},
    )
    assert np.allclose(sched["by_well"]["a"]["net_oil"], sched["by_well"]["a"]["oil_bbl"] * 0.20)
    assert np.allclose(sched["by_well"]["b"]["net_oil"], sched["by_well"]["b"]["oil_bbl"] * 0.40)


def test_build_schedule_minerals_net_volume_uses_decimal():
    forecasts = {"a": _well(1000.0, "2026-06-01")}
    sched = _wi_schedule(
        forecasts, {"a": "history"},
        interest_type="minerals", wi_pct=None, nri_pct=None, decimal=0.05,
    )
    assert np.allclose(sched["by_well"]["a"]["net_oil"], sched["by_well"]["a"]["oil_bbl"] * 0.05)


def test_build_schedule_totals_include_net_volumes():
    forecasts = {"a": _well(1000.0, "2026-06-01"), "b": _well(1000.0, "2026-06-01")}
    sched = _wi_schedule(forecasts, {"a": "history", "b": "history"})
    assert "net_oil" in sched["totals"] and "net_gas" in sched["totals"]
    assert np.allclose(sched["totals"]["net_oil"],
                       sched["by_well"]["a"]["net_oil"] + sched["by_well"]["b"]["net_oil"])


def test_well_meta_payload_includes_lateral_ft():
    from server.valuation.orchestrator import _well_meta_payload
    from server.valuation.types import WellMeta
    m = WellMeta(
        api="42-329-00001", status="PRODUCING", operator="OP",
        basin="MIDLAND", formation="WOLFCAMP", county="MIDLAND",
        lateral_ft=9800.0, spud_date=None, completion_date=None,
        first_prod_date=None, last_prod_date=None, n_history_months=0,
        planned_first_prod_date=None,
    )
    out = _well_meta_payload(["42-329-00001"], {"42-329-00001": m})
    assert out["42-329-00001"]["lateral_ft"] == 9800.0
    # missing well → None, not a crash
    out2 = _well_meta_payload(["x"], {})
    assert out2["x"]["lateral_ft"] is None


# ── by_api membership: a typo'd API must not silently misprice ──────────────

def test_validate_by_api_membership_raises_on_unknown_api():
    from server.valuation.orchestrator import _validate_by_api_membership
    with pytest.raises(ValueError, match="silently misprice"):
        _validate_by_api_membership({"42-TYPO-00001": {"wi_pct": 0.5, "nri_pct": 0.4}},
                                    {"42-329-00001", "42-329-00002"})


def test_validate_by_api_membership_names_the_unknown_apis():
    from server.valuation.orchestrator import _validate_by_api_membership
    with pytest.raises(ValueError, match="42-TYPO-00001"):
        _validate_by_api_membership({"42-TYPO-00001": 0.05}, {"42-329-00001"})


def test_validate_by_api_membership_caps_named_apis_at_five():
    from server.valuation.orchestrator import _validate_by_api_membership
    by_api = {f"42-TYPO-{i:05d}": 0.05 for i in range(8)}
    with pytest.raises(ValueError) as exc:
        _validate_by_api_membership(by_api, {"42-329-00001"})
    msg = str(exc.value)
    assert msg.count("42-TYPO-") == 5
    assert "8 interest.by_api key(s)" in msg           # total count still reported


def test_validate_by_api_membership_accepts_known_and_empty():
    from server.valuation.orchestrator import _validate_by_api_membership
    known = {"42-329-00001", "42-329-00002"}
    _validate_by_api_membership({"42-329-00001": 0.05}, known)   # no raise
    _validate_by_api_membership({}, known)                       # no raise
    _validate_by_api_membership(None, known)                     # no raise


# ── _resolve_asset_list: cap + dedupe enforcement ──────────────────────────

def test_resolve_asset_list_caps_well_apis():
    from server.valuation.orchestrator import _resolve_asset_list
    from server.valuation.casefile import MAX_ASSET_WELLS
    apis = [f"42-{i:09d}" for i in range(MAX_ASSET_WELLS + 1)]
    with pytest.raises(ValueError, match="at most"):
        _resolve_asset_list({"well_apis": apis})


def test_resolve_asset_list_dedupes():
    from server.valuation.orchestrator import _resolve_asset_list
    assert _resolve_asset_list({"well_apis": ["A", "B", "A"]}) == ["A", "B"]


def test_resolve_asset_list_empty_raises_clear_error():
    """{} (neither key) must be a clear ValueError, not KeyError("'filter_sql'")."""
    from server.valuation.orchestrator import _resolve_asset_list
    with pytest.raises(ValueError, match="well_apis or filter_sql"):
        _resolve_asset_list({})




