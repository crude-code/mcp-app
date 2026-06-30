from server.valuation import deal_sheet as ds


def test_build_deal_sheet_spec_carries_run_id():
    facts = {"deal_type": "Minerals", "interest": "6% RI",
             "operator": "Op", "area": "Reeves"}
    statuses = [{"code": "PDP", "label": "Producing", "tag": "", "dot": "#000",
                 "gross_wells": 1, "net_wells": 1.0, "rates": ["10"]}]
    cube = {"Strip": {"PDP": {"10": 1000.0}}}
    production = {"series": [], "start_month": 0, "end_month": 0, "origin": "2026-01-01"}
    spec = ds.build_deal_sheet_spec(
        headline="h", tldr="t", title="Reeves", facts=facts, statuses=statuses,
        cube=cube, production=production, rate_centers={"PDP": 0.10},
        price_mode="strip", run_id="run-xyz")
    widget = spec["sections"][0]["widgets"][0]
    assert widget["run_id"] == "run-xyz"
