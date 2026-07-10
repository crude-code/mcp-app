"""Slim, artifact-facing payload for a completed valuation run.

Pure assembly, no DB/IO — mirrors `deal_sheet.py`'s pattern and reuses its
`roll_up_facts`/`build_production_series` helpers. Returns only what an
artifact-building Claude turn needs: exec facts, a net production/cashflow
series (omitted when the deal has no active status), and the blended
bottom-line economics with the full deck x rate PV cube and scenario axes —
the latter powers the template's deck/rate selectors and risk-bucket detail.
"""
from pathlib import Path

from server.valuation import config
from server.valuation import deal_sheet as ds

_VIEWER_PATH = Path(__file__).resolve().parent / "viewer" / "DealSheet.jsx"


def load_viewer() -> str:
    """Source of the frozen DealSheet.jsx artifact template. `run_valuation`
    ships it alongside `data`; Claude pastes the payload in verbatim and never
    rebuilds the component."""
    return _VIEWER_PATH.read_text()


def build_artifact_payload(*, economics: dict, wells: dict) -> dict:
    """`economics`/`wells` are the run record's stage payloads. Returns
    `{"facts", "production", "economics"}` where economics carries the full
    scenario cube plus the axes the deal-sheet template's selectors index:
    `{npv_at_centers, cube, decks, default_deck, default_rates, statuses}`.
    Statuses are data-only (code/label/tag/counts/rate ladder) — colors and
    layout belong to the template, not the payload.
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

    price_mode = (economics.get("inputs") or {}).get("price_mode", "strip")
    decks, default_deck = config.deck_labels(price_mode)

    return {
        "facts": facts,
        "production": production["series"] if has_activity else None,
        "economics": {
            "npv_at_centers": economics["npv_at_centers"],
            "cube": economics["npv_by_status"],
            "decks": decks,
            "default_deck": default_deck,
            "default_rates": ds.default_rates(rate_centers),
            "statuses": [
                {k: s[k] for k in ("code", "label", "tag", "gross_wells", "net_wells", "rates")}
                for s in statuses
            ],
        },
    }
