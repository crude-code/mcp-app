from datetime import date

import numpy as np

from server.valuation import orchestrator as orch


def _one_well_forecast():
    """A minimal placed-forecast dict (PDP, anchored at origin) for one well."""
    curve = {
        "qi": 1000.0, "di": 0.15, "b": 0.8, "terminal_di_monthly": 0.004,
        "switch_month_from_peak": None, "stream": "oil",
        "provenance": {"source": "fit", "strategy": "pdp"},
    }
    gcurve = {**curve, "stream": "gas"}
    placed = {
        "30-000-00001": {
            "oil": {"curve": curve, "peak_date": "2026-07-01", "start_date": "2026-07-01", "strategy": "pdp"},
            "gas": {"curve": gcurve, "peak_date": "2026-07-01", "start_date": "2026-07-01", "strategy": "pdp"},
        }
    }
    needs_capex = {"30-000-00001": False}
    statuses = {"30-000-00001": "PRODUCING"}
    return placed, needs_capex, statuses


def _fake_strip(monkeypatch):
    """Pin resolve_price_series to a deterministic 2-month strip (then flat)."""
    def fake(econ_overrides, *, origin, horizon_months, flat_oil, flat_gas, db_query=None):
        return {
            "oil": np.full(horizon_months, 70.0),
            "gas": np.full(horizon_months, 3.5),
            "mode": "strip", "trade_date": date(2026, 6, 23),
            "oil_repr": 70.0, "gas_repr": 3.5,
        }
    monkeypatch.setattr(orch.strip, "resolve_price_series", fake)


def test_cube_keys_are_deck_labels_and_band_shifts_oil(monkeypatch):
    _fake_strip(monkeypatch)
    placed, needs_capex, statuses = _one_well_forecast()
    econ = orch._economics_from_forecasts(
        forecasts=placed, needs_capex=needs_capex, statuses=statuses,
        econ_overrides={"interest_type": "minerals", "interest": {"decimal": 0.01}},
    )
    cube = econ["npv_by_status"]
    assert set(cube) == {"Strip", "$70", "$75", "$80"}       # base strip + flat decks
    # fake strip prices oil at flat 70, so the $80 flat deck > Strip (volumes identical)
    pdp_base = cube["Strip"]["PDP"]
    pdp_up = cube["$80"]["PDP"]
    center = econ["rate_centers"]["PDP"]
    from server.valuation.config import rate_ladder
    key = f"{rate_ladder(center)[1] * 100:g}"
    assert pdp_up[key] > pdp_base[key] > 0
    # persisted price metadata
    assert econ["inputs"]["price_mode"] == "strip"
    assert econ["inputs"]["strip_trade_date"] == "2026-06-23"
