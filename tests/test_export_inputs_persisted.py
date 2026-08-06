from server.valuation import orchestrator as orch
from server.valuation.types import DeclineCurve, ForecastProvenance


def _serial_curve(stream):
    c = DeclineCurve(qi=500.0, di=0.12, b=0.8, terminal_di_monthly=0.005,
                     switch_month_from_peak=float("inf"), stream=stream,
                     provenance=ForecastProvenance(source="self", strategy="pdp"))
    return orch._serialize_curve(c)


def test_economics_persists_price_path_and_cost_inputs():
    fc = {"oil": orch._place_curve(self_curve=_serial_curve("oil"),
                                   start_date="2026-01-01", strategy="pdp"),
          "gas": orch._place_curve(self_curve=_serial_curve("gas"),
                                   start_date="2026-01-01", strategy="pdp")}
    forecasts = {"42-000-00000": fc}
    needs_capex = {"42-000-00000": False}
    statuses = {"42-000-00000": "PRODUCING"}
    econ_overrides = {
        "interest_type": "minerals", "interest": {"decimal": 0.05},
        # flat deck avoids the NYMEX-strip DB fetch
        "price_deck": {"type": "flat", "oil_usd_bbl": 70.0, "gas_usd_mmbtu": 3.0},
        "opex_per_bbl_usd": 2.5, "opex_per_well_per_month_usd": 1500.0,
        "capex_per_well_usd": 8_000_000.0,
    }
    econ = orch._economics_from_forecasts(
        forecasts=forecasts, needs_capex=needs_capex,
        statuses=statuses, econ_overrides=econ_overrides)
    horizon = econ["horizon_months"]
    assert set(econ["price_path"]) == {"oil", "gas"}
    assert len(econ["price_path"]["oil"]) == horizon
    assert len(econ["price_path"]["gas"]) == horizon
    assert econ["cost_inputs"] == {
        "capex_per_well": 8_000_000.0,
        "opex_per_well_month": 1500.0,
        "opex_per_bbl": 2.5,
    }
