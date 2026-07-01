"""Slim, artifact-facing payload for a completed valuation run.

Pure assembly, no DB/IO — mirrors `deal_sheet.py`'s pattern and reuses its
`roll_up_facts`/`build_production_series` helpers. Returns only what an
artifact-building Claude turn needs: exec facts, a net production/cashflow
series (omitted when the deal has no active status), and the blended
bottom-line economics. No PDP/DUC/PUD bucket detail, no deck x rate PV cube —
`run_valuation` hands this to Claude to build a deal-sheet artifact from,
instead of the MCP app rendering a fixed widget.
"""
from server.valuation import config
from server.valuation import deal_sheet as ds


def build_artifact_payload(*, economics: dict, wells: dict) -> dict:
    """`economics`/`wells` are the run record's stage payloads — the same
    shape `compose_briefing_for_run` reads. Returns
    `{"facts", "production", "economics": {"npv_at_centers"}}`.
    """
    rate_centers = economics.get("rate_centers") or config.resolve_rate_centers(None)
    well_meta = wells.get("well_meta", {})
    interest = economics.get("interest") or economics.get("assumptions") or {}

    facts, statuses = ds.roll_up_facts(well_meta, interest, rate_centers)

    production = ds.build_production_series(
        schedule_totals=economics["schedule"]["totals"],
        horizon_months=int(economics.get("horizon_months", 360)),
        origin=economics["schedule"]["origin"],
        statuses=statuses,
    )
    has_activity = any(
        pt["oil"] or pt["gas"] or pt["cashflow"] for pt in production["series"]
    )

    return {
        "facts": facts,
        "production": production["series"] if has_activity else None,
        "economics": {"npv_at_centers": economics["npv_at_centers"]},
    }
