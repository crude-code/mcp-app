"""Slim, artifact-facing payload for a completed valuation run.

Pure assembly, no DB/IO — mirrors `deal_sheet.py`'s pattern and reuses its
`roll_up_facts` helper. Returns only what an artifact-building Claude turn
needs: exec facts, the blended bottom-line economics with the full
deck x rate PV cube and scenario axes (powering the template's deck/rate
selectors and risk-bucket detail), the resolved assumptions, and the
per-assertion evidence record.
"""
from pathlib import Path

from server.valuation import config
from server.valuation import deal_sheet as ds

_VIEWER_PATH = Path(__file__).resolve().parent / "viewer" / "DealSheet.jsx"


def load_viewer() -> str:
    """Source of the frozen DealSheet.jsx artifact template. `run_valuation`
    ships it alongside `data`; Claude pastes the payload in verbatim and never
    rebuilds the component."""
    return _VIEWER_PATH.read_text(encoding="utf-8")


def build_artifact_payload(*, economics: dict, wells: dict) -> dict:
    """`economics`/`wells` are the run record's stage payloads. Returns
    `{"facts", "economics", "assumptions", "evidence"}` where economics
    carries the full scenario cube plus the axes the deal-sheet template's
    selectors index: `{npv_at_centers, cube, decks, default_deck,
    default_rates, statuses}`. Statuses are data-only (code/label/tag/counts/
    rate ladder) — colors and layout belong to the template, not the payload.
    `assumptions` feeds the template's provenance panel; `evidence` is the
    per-assertion judgment record built at valuation time (None on legacy
    runs valued before evidence capture — the template hides the modules).
    """
    rate_centers = economics.get("rate_centers") or config.resolve_rate_centers(None)
    well_meta = wells.get("well_meta", {})
    interest = economics.get("interest") or economics.get("assumptions") or {}

    facts, statuses = ds.roll_up_facts(well_meta, interest, rate_centers)

    price_mode = (economics.get("inputs") or {}).get("price_mode", "strip")
    decks, default_deck = config.deck_labels(price_mode)

    inputs = economics.get("inputs") or {}
    costs = economics.get("cost_inputs") or {}
    capex_col = (economics["schedule"].get("totals") or {}).get("capex") or []
    assumptions = {
        "effective_month": str(economics["schedule"]["origin"])[:7],
        "price_mode": price_mode,
        "strip_trade_date": inputs.get("strip_trade_date"),
        "oil_price": inputs.get("oil_price"),
        "gas_price": inputs.get("gas_price"),
        "oil_diff": inputs.get("oil_diff"),
        "gas_diff": inputs.get("gas_diff"),
        "tax_pct": inputs.get("tax_pct"),
        "gpt_pct": inputs.get("gpt_pct"),
        "horizon_months": int(economics.get("horizon_months", 360)),
        "capex_per_well": costs.get("capex_per_well"),
        "opex_per_well_month": costs.get("opex_per_well_month"),
        "opex_per_bbl": costs.get("opex_per_bbl"),
        "undiscounted_cashflow": economics.get("cashflow_total_undiscounted"),
        "net_capex_total": round(float(sum(capex_col))) if capex_col else 0,
    }

    return {
        "facts": facts,
        "assumptions": assumptions,
        "evidence": wells.get("evidence"),
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
