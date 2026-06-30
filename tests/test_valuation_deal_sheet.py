from server.valuation.orchestrator import _well_meta_payload
from server.valuation.types import WellMeta


def _meta(**kw):
    base = dict(
        api="42-001-00001", status="PRODUCING", basin="MIDLAND",
        formation="WOLFCAMP", county="MIDLAND", lateral_ft=10000.0,
        spud_date=None, completion_date=None, first_prod_date=None,
        last_prod_date=None, n_history_months=24, planned_first_prod_date=None,
    )
    base.update(kw)
    return WellMeta(**base)


def test_wellmeta_carries_operator():
    m = _meta(operator="SURGEON ENERGY")
    assert m.operator == "SURGEON ENERGY"


def test_wellmeta_operator_defaults_none():
    m = _meta()
    assert m.operator is None


def test_well_meta_payload_maps_each_api():
    metas = {
        "A": _meta(api="A", operator="SURGEON ENERGY", basin="MIDLAND", formation="WOLFCAMP", status="PRODUCING"),
        "B": _meta(api="B", operator="MEWBOURNE", basin="MIDLAND", formation="SPRABERRY", status="DUC"),
    }
    out = _well_meta_payload(["A", "B"], metas)
    assert out["A"] == {"status": "PRODUCING", "operator": "SURGEON ENERGY", "basin": "MIDLAND", "formation": "WOLFCAMP", "lateral_ft": 10000.0}
    assert out["B"]["status"] == "DUC"


def test_well_meta_payload_tolerates_missing_api():
    out = _well_meta_payload(["A", "MISSING"], {"A": _meta(api="A")})
    assert out["MISSING"] == {"status": None, "operator": None, "basin": None, "formation": None, "lateral_ft": None}


from server.valuation.deal_sheet import roll_up_facts, _default_rates


WI_ASSUMPTIONS = {"interest_type": "wi", "wi_pct": 0.25, "nri_pct": 0.1875}
MIN_ASSUMPTIONS = {"interest_type": "minerals", "decimal": 0.03}
CENTERS = {"PDP": 0.15, "DUC": 0.20, "PUD": 0.25}


def _wm(status, operator, basin, formation):
    return {"status": status, "operator": operator, "basin": basin, "formation": formation}


def test_status_rows_band_center_and_default_to_center():
    well_meta = {
        "33-053-1": {"status": "PERMITTED", "operator": "X", "basin": "BAKKEN", "formation": "MB"},
    }
    interest = {"interest_type": "wi", "wi_pct": 0.5, "nri_pct": 0.375}
    facts, statuses = roll_up_facts(well_meta, interest, {"PDP": 0.15, "DUC": 0.20, "PUD": 0.22})
    pud = next(s for s in statuses if s["code"] == "PUD")
    assert pud["rates"] == ["19.5", "22", "24.5"]
    assert _default_rates({"PDP": 0.15, "DUC": 0.20, "PUD": 0.22})["PUD"] == "22"


def test_roll_up_facts_wi_grid():
    well_meta = {
        "A": _wm("PRODUCING", "SURGEON ENERGY", "MIDLAND", "WOLFCAMP"),
        "B": _wm("PRODUCING", "SURGEON ENERGY", "MIDLAND", "WOLFCAMP"),
        "C": _wm("DUC", "MEWBOURNE", "MIDLAND", "SPRABERRY"),
        "D": _wm("PERMITTED", "PERMIAN RES", "MIDLAND", "WOLFCAMP"),
    }
    facts, statuses = roll_up_facts(well_meta, WI_ASSUMPTIONS, CENTERS)
    assert facts["deal_type"] == "Working Interest"
    assert facts["interest"] == "25% WI · 18.75% NRI"
    assert facts["operator"] == "Surgeon Energy +2"
    assert facts["area"] == "Midland · Wolfcamp/Spraberry"
    by_code = {s["code"]: s for s in statuses}
    assert by_code["PDP"]["gross_wells"] == 2
    assert by_code["PDP"]["net_wells"] == 0.5     # 2 * 0.25
    assert by_code["DUC"]["gross_wells"] == 1
    assert by_code["PUD"]["gross_wells"] == 1
    assert [s["code"] for s in statuses] == ["PDP", "DUC", "PUD"]


def test_roll_up_facts_minerals_interest_and_net():
    well_meta = {"A": _wm("PRODUCING", "OP", "DJ", "NIOBRARA")}
    facts, statuses = roll_up_facts(well_meta, MIN_ASSUMPTIONS, CENTERS)
    assert facts["deal_type"] == "Minerals / Royalty"
    assert facts["interest"] == "3.00% decimal"
    assert statuses[0]["net_wells"] == 0.03      # 1 * decimal


def test_roll_up_facts_per_well_interest_sums_net_wells():
    well_meta = {
        "A": _wm("PRODUCING", "OP", "MIDLAND", "WOLFCAMP"),
        "B": _wm("PRODUCING", "OP", "MIDLAND", "WOLFCAMP"),
    }
    interest = {
        "interest_type": "wi", "wi_pct": 0.25, "nri_pct": 0.20,
        "by_api": {"B": {"wi_pct": 0.5, "nri_pct": 0.40}},
    }
    facts, statuses = roll_up_facts(well_meta, interest, CENTERS)
    by_code = {s["code"]: s for s in statuses}
    # net wells = sum of per-well WI in the bucket: 0.25 (A) + 0.5 (B) = 0.75
    assert by_code["PDP"]["net_wells"] == 0.75
    # label flags the per-well variation rather than a single blanket %
    assert "varies" in facts["interest"] or "per-well" in facts["interest"]


def test_roll_up_facts_per_well_minerals_sums_decimals():
    well_meta = {
        "A": _wm("PRODUCING", "OP", "DJ", "NIOBRARA"),
        "B": _wm("PRODUCING", "OP", "DJ", "NIOBRARA"),
    }
    interest = {"interest_type": "minerals", "decimal": 0.01, "by_api": {"B": 0.03}}
    facts, statuses = roll_up_facts(well_meta, interest, CENTERS)
    assert statuses[0]["net_wells"] == round(0.01 + 0.03, 2)   # 0.04


def test_roll_up_facts_single_operator_no_suffix():
    well_meta = {"A": _wm("PRODUCING", "SOLO OP", "MIDLAND", "WOLFCAMP")}
    facts, _ = roll_up_facts(well_meta, WI_ASSUMPTIONS, CENTERS)
    assert facts["operator"] == "Solo Op"


def test_roll_up_facts_area_orders_formations_by_frequency():
    # Spraberry seen first, but Wolfcamp dominates (3 vs 1) → Wolfcamp first.
    well_meta = {
        "A": _wm("PRODUCING", "OP", "MIDLAND", "SPRABERRY"),
        "B": _wm("PRODUCING", "OP", "MIDLAND", "WOLFCAMP"),
        "C": _wm("PRODUCING", "OP", "MIDLAND", "WOLFCAMP"),
        "D": _wm("PRODUCING", "OP", "MIDLAND", "WOLFCAMP"),
    }
    facts, _ = roll_up_facts(well_meta, WI_ASSUMPTIONS, CENTERS)
    assert facts["area"] == "Midland · Wolfcamp/Spraberry"


from server.valuation.deal_sheet import build_production_series


def _statuses(*present_codes):
    """Minimal status rows — only `code` + `gross_wells` drive the window."""
    return [{"code": c, "gross_wells": (1 if c in present_codes else 0)}
            for c in ("PDP", "DUC", "PUD")]


def test_window_anchors_at_first_production_for_pud_only():
    # PUD comes online +36mo → no volume until month 36.
    oil = [0.0] * 36 + [100.0] * 100 + [0.0] * 224
    totals = {"net_oil": oil, "net_gas": oil, "net_cashflow": oil}
    prod = build_production_series(
        schedule_totals=totals, horizon_months=360,
        origin="2026-07-01", statuses=_statuses("PUD"),
    )
    months = [p["m"] for p in prod["series"]]
    # first_prod=36, last_online=36 → max(36+12, 36+24)=60 → months 36..60
    assert months[0] == 36
    assert months[-1] == 60
    assert prod["start_month"] == 36
    assert prod["end_month"] == 60
    # monthly granularity, no gaps
    assert months == list(range(36, 61))


def test_window_stamps_calendar_dates_from_origin():
    oil = [0.0] * 36 + [100.0] * 100 + [0.0] * 224
    totals = {"net_oil": oil, "net_gas": oil, "net_cashflow": oil}
    prod = build_production_series(
        schedule_totals=totals, horizon_months=360,
        origin="2026-07-01", statuses=_statuses("PUD"),
    )
    # origin Jul 2026 + 36mo = Jul 2029; + 24mo end = Jul 2031.
    assert prod["series"][0]["date"] == "2029-07"
    assert prod["series"][-1]["date"] == "2031-07"
    assert prod["origin"] == "2026-07-01"


def test_window_carries_cashflow_per_point():
    oil = [0.0] * 36 + [7.0] * 100 + [0.0] * 224
    cash = [0.0] * 36 + [-559529.0] + [70.0] * 99 + [0.0] * 224
    totals = {"net_oil": oil, "net_gas": oil, "net_cashflow": cash}
    prod = build_production_series(
        schedule_totals=totals, horizon_months=360,
        origin="2026-07-01", statuses=_statuses("PUD"),
    )
    first = prod["series"][0]
    assert first["m"] == 36
    assert first["cashflow"] == -559529          # the CAPEX month
    assert prod["series"][1]["cashflow"] == 70


def test_window_blend_spans_now_to_last_online_plus_12():
    # PDP produces from month 0, PUD online +36 → window [0, 48].
    net = [10.0] * 360
    totals = {"net_oil": net, "net_gas": net, "net_cashflow": net}
    prod = build_production_series(
        schedule_totals=totals, horizon_months=360,
        origin="2026-07-01", statuses=_statuses("PDP", "PUD"),
    )
    assert prod["start_month"] == 0
    assert prod["end_month"] == 48               # max(36+12, 0+24)


def test_window_all_pdp_uses_24mo_floor():
    net = [10.0] * 360
    totals = {"net_oil": net, "net_gas": net, "net_cashflow": net}
    prod = build_production_series(
        schedule_totals=totals, horizon_months=360,
        origin="2026-07-01", statuses=_statuses("PDP"),
    )
    # first_prod=0, last_online=0 → max(0+12, 0+24)=24, never just 12.
    assert prod["end_month"] == 24


from server.valuation.deal_sheet import build_deal_sheet_spec


def _cube():
    # minimal cube: one value per (deck, status, rate) used below.
    mk = lambda base: {"15": base, "17.5": base, "20": base,
                       "20.0": base, "22.5": base, "25": base,
                       "25.0": base, "27.5": base, "30": base}
    return {
        d: {"PDP": mk(20_000_000), "DUC": mk(4_000_000), "PUD": mk(3_000_000)}
        for d in ("Strip", "$70", "$75", "$80")
    }


def test_build_deal_sheet_spec_shape():
    facts = {"deal_type": "Working Interest", "interest": "25% WI · 18.75% NRI",
             "operator": "Surgeon Energy +2", "area": "Midland · Wolfcamp"}
    statuses = [
        {"code": "PDP", "label": "Producing", "tag": "(PDP)", "dot": "x",
         "gross_wells": 156, "net_wells": 39.0, "rates": ["15", "17.5", "20"]},
        {"code": "DUC", "label": "DUC", "tag": "+18mo", "dot": "x",
         "gross_wells": 36, "net_wells": 9.0, "rates": ["20", "22.5", "25"]},
        {"code": "PUD", "label": "Permitted", "tag": "(PUD) +36mo", "dot": "x",
         "gross_wells": 48, "net_wells": 12.0, "rates": ["25", "27.5", "30"]},
    ]
    production = {"series": [{"m": 0, "oil": 1.0, "gas": 2.0}], "duc_month": 18,
                  "pud_month": 36, "horizon_months": 360}
    spec = build_deal_sheet_spec(
        headline="PV: $27.0MM on a Midland WI package",
        tldr="Value concentrates in the producing core.",
        title="Midland Basin · WI Package",
        facts=facts, statuses=statuses, cube=_cube(), production=production,
        rate_centers=CENTERS,
    )
    assert spec["kind"] == "briefing"
    assert spec["headline"].startswith("PV")
    assert spec["layout"] == "deal_sheet"          # SpecRenderer branch flag
    section = spec["sections"][0]
    assert section["layout"] == "full-width"
    widget = section["widgets"][0]
    assert widget["type"] == "deal_sheet"
    assert widget["default_deck"] == "Strip"
    assert widget["default_rates"] == {"PDP": "15", "DUC": "20", "PUD": "25"}
    assert widget["decks"] == ["Strip", "$70", "$75", "$80"]
    assert widget["facts"] == facts
    assert widget["statuses"] == statuses
    assert widget["cube"] == _cube()
    assert widget["production"] == production
    # headline_npv summary (default-scheme sum) kept at top level for narration.
    assert spec["headline_npv"] == round(20_000_000 + 4_000_000 + 3_000_000, 2)


from server.valuation.deal_sheet import build_econ_block


def test_realized_price_is_deck_minus_diff():
    """econ.py prices at deck − diff; the audit tab must show the same number."""
    block = build_econ_block(
        inputs={
            "oil_price": 70.0, "gas_price": 3.0,
            "oil_diff": 5.0, "gas_diff": 0.5,
            "tax_pct": 0.046, "gpt_pct": 0.02,
            "horizon_months": 360,
        },
        interest={"interest_type": "wi", "wi_pct": 1.0, "nri_pct": 0.75},
        effective_date="2026-06-01",
    )
    assert block["price"]["oil_realized"] == 65.0
    assert block["price"]["gas_realized"] == 2.5
