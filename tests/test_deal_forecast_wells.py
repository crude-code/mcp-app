# tests/test_deal_forecast_wells.py — forecast_wells_for_run, accept-and-echo.
import numpy as np
import pytest
from datetime import date

from dateutil.relativedelta import relativedelta

import server.valuation.orchestrator as orch
from server.valuation.orchestrator import ForecastValidationError, forecast_wells_for_run
from server.valuation.types import WellMeta


class _FakeStore:
    def __init__(self):
        self.stages = {}
        self.records = {}                        # run_id → record dict (for get())
    def new_run(self, *, user_id, case_file):
        self.records["run-1"] = {"run_id": "run-1", "user_id": user_id}
        return "run-1"
    def write_stage(self, run_id, *, stage, payload): self.stages[stage] = payload
    def read_stage(self, run_id, *, stage): return self.stages.get(stage)
    def get(self, run_id): return self.records.get(run_id)


def _meta(api, status, lateral=12000.0):
    return WellMeta(api=api, status=status, basin="PRB", formation="NIOBRARA B",
                    county="CAMPBELL", lateral_ft=lateral,
                    n_history_months=0)


def _patch(monkeypatch, metas, prod, store=None):
    store = store or _FakeStore()
    monkeypatch.setattr(orch, "ValuationRunStore", lambda: store)
    monkeypatch.setattr(orch, "bulk_load_wells", lambda apis: [metas[a] for a in apis if a in metas])
    monkeypatch.setattr(orch, "bulk_load_production",
                        lambda apis: {a: prod.get(a, {"months": [], "oil_bbl": [], "gas_mcf": []})
                                      for a in apis})
    return store


# 24 months of clean exponential decline ending last month — a producer whose
# last-month rate is a known number Claude can anchor to.
_TODAY = date.today().replace(day=1)
_HIST_N = 24
_HIST_MONTHS = [(_TODAY - relativedelta(months=_HIST_N - i)).isoformat() for i in range(_HIST_N)]
_HIST_OIL = list(900.0 * np.exp(-0.06 * np.arange(_HIST_N)))
_LAST_RATE = _HIST_OIL[-1]                                   # ≈ 226
_ANCHOR = _HIST_MONTHS[-1][:7]
_FUTURE = (_TODAY + relativedelta(months=6)).strftime("%Y-%m")


def _producer_entry(**over):
    entry = {
        "wells": ["H"],
        "oil": {"qi": round(_LAST_RATE, 1), "di": 0.06, "b": 0.9},
        "gas": None,
        "anchor_month": _ANCHOR,
        "rationale": "clean decline; qi from the last clean month; b from mature offsets",
    }
    entry.update(over)
    return entry


def _producer_world(monkeypatch, store=None):
    metas = {"H": _meta("H", "PRODUCING")}
    prod = {"H": {"months": _HIST_MONTHS, "oil_bbl": _HIST_OIL, "gas_mcf": [0.0] * _HIST_N}}
    return _patch(monkeypatch, metas, prod, store=store)


# ── happy path: producer ─────────────────────────────────────────────────────

def test_producer_commit_echoes_consequences(monkeypatch):
    _producer_world(monkeypatch)
    out = forecast_wells_for_run(run_id=None, user_id=7, forecasts=[_producer_entry()])
    assert out["run_id"] == "run-1"
    assert out["wells_committed"] == 1 and out["wells_in_run"] == 1
    assert out["by_status"] == {"PDP": 1, "DUC": 0, "PUD": 0}
    echo = out["committed"][0]
    assert echo["undrilled"] is False
    oil = echo["oil"]
    assert oil["next_12_cum"] < oil["trailing_12_actual"]     # declining well
    assert 0.0 < oil["eff_annual_decline_yr1"] < 1.0
    assert oil["eur"] == pytest.approx(oil["cum_to_date"] + oil["eur_remaining"], abs=0.2)
    assert oil["eur_per_ft"] is not None
    assert echo["gas"] is None


def test_committed_curve_starts_at_asserted_qi_not_peak(monkeypatch):
    """The continue-decline regression, restated for assertions: qi is the
    anchor rate, so the first projected month equals qi (~226), never the
    historical peak (~900)."""
    store = _producer_world(monkeypatch)
    out = forecast_wells_for_run(run_id=None, user_id=7, forecasts=[_producer_entry()])
    fcs, needs_capex, _st = orch._load_forecast_stage(
        forecast=store.read_stage(out["run_id"], stage="forecast"),
        as_of=date.today(), months_override=None)
    from server.valuation.forecast import project
    _mo, rates = project(orch._deserialize_forecast(fcs["H"]["oil"]), horizon_months=3)
    assert rates[0] == pytest.approx(_LAST_RATE, rel=0.01), \
        f"forecast must start at asserted qi (~{_LAST_RATE:.0f}), got {rates[0]:.1f}"
    assert needs_capex == {"H": False}


def test_uptime_factor_scales_committed_qi(monkeypatch):
    store = _producer_world(monkeypatch)
    forecast_wells_for_run(run_id=None, user_id=7, forecasts=[_producer_entry(uptime_factor=0.9)])
    stored = store.stages["forecast"]["forecasts"]["H"]["oil"]["curve"]
    assert stored["qi"] == pytest.approx(_LAST_RATE * 0.9, rel=0.01)
    # raw assertion preserved unscaled in the audit block
    a = store.stages["forecast"]["forecasts"]["H"]["assertion"]
    assert a["uptime_factor"] == 0.9
    assert a["asserted"]["oil"]["qi"] == pytest.approx(_LAST_RATE, rel=0.01)


def test_unasserted_gas_with_history_warns_and_zeroes(monkeypatch):
    metas = {"H": _meta("H", "PRODUCING")}
    prod = {"H": {"months": _HIST_MONTHS, "oil_bbl": _HIST_OIL,
                  "gas_mcf": [100.0] * _HIST_N}}
    store = _patch(monkeypatch, metas, prod)
    out = forecast_wells_for_run(run_id=None, user_id=7, forecasts=[_producer_entry()])
    echo = out["committed"][0]
    assert any("gas not asserted" in w for w in echo["warnings"])
    assert store.stages["forecast"]["forecasts"]["H"]["gas"]["curve"]["qi"] == 0.0


# ── undrilled wells: asserted timing ─────────────────────────────────────────

def test_undrilled_permitted_well_asserts_online_month(monkeypatch):
    metas = {"P": _meta("P", "PERMITTED")}
    store = _patch(monkeypatch, metas, prod={})
    out = forecast_wells_for_run(run_id=None, user_id=7, forecasts=[{
        "wells": ["P"], "oil": {"qi": 800.0, "di": 0.10, "b": 1.1}, "gas": None,
        "anchor_month": _FUTURE,
        "rationale": "offsets set the level; operator cadence says ~6 months out",
    }])
    echo = out["committed"][0]
    assert echo["undrilled"] is True and echo["online_month"] == _FUTURE
    assert echo["oil"]["trailing_12_actual"] is None
    assert out["by_status"]["PUD"] == 1

    stage = store.stages["forecast"]["forecasts"]["P"]
    assert stage["needs_capex"] is True
    assert stage["anchor_month"] == _FUTURE
    # placement: the asserted online month IS the start date (no config offset)
    fcs, needs_capex, statuses = orch._load_forecast_stage(
        forecast=store.stages["forecast"], as_of=date.today(), months_override=None)
    assert fcs["P"]["oil"]["start_date"] == _FUTURE + "-01"
    assert needs_capex["P"] is True and statuses["P"] == "PERMITTED"


def test_anchored_duc_still_needs_capex(monkeypatch):
    """Decision 5: capex follows status, not the anchor — an anchored DUC gets
    its AFE at the asserted online month."""
    metas = {"D": _meta("D", "DUC")}
    store = _patch(monkeypatch, metas, prod={})
    forecast_wells_for_run(run_id=None, user_id=7, forecasts=[{
        "wells": ["D"], "oil": {"qi": 500.0, "di": 0.08, "b": 1.0}, "gas": None,
        "anchor_month": _FUTURE, "rationale": "AFE in dataroom dates completion",
    }])
    assert store.stages["forecast"]["forecasts"]["D"]["needs_capex"] is True


# ── cohorts ──────────────────────────────────────────────────────────────────

def _cohort_world(monkeypatch):
    metas = {a: _meta(a, "PRODUCING") for a in ("C1", "C2", "C3")}
    prod = {
        # trailing-12 oil: C1 1200, C2 600, C3 200 → shares 0.6 / 0.3 / 0.1
        "C1": {"months": _HIST_MONTHS, "oil_bbl": [100.0] * _HIST_N, "gas_mcf": [0.0] * _HIST_N},
        "C2": {"months": _HIST_MONTHS, "oil_bbl": [50.0] * _HIST_N, "gas_mcf": [0.0] * _HIST_N},
        "C3": {"months": _HIST_MONTHS, "oil_bbl": [100.0 / 6] * _HIST_N, "gas_mcf": [0.0] * _HIST_N},
    }
    return _patch(monkeypatch, metas, prod)


def _cohort_entry():
    return {
        "wells": ["C1", "C2", "C3"],
        "oil": {"qi": 300.0, "di": 0.04, "b": 0.8}, "gas": None,
        "anchor_month": _ANCHOR,
        "rationale": "coherent tail cohort, summed stream; b from mature offsets",
    }


def test_cohort_shares_are_trailing12_pro_rata(monkeypatch):
    _cohort_world(monkeypatch)
    out = forecast_wells_for_run(run_id=None, user_id=7, forecasts=[_cohort_entry()])
    shares = out["committed"][0]["shares"]["oil"]
    assert shares["C1"] == pytest.approx(0.6, abs=0.001)
    assert shares["C2"] == pytest.approx(0.3, abs=0.001)
    assert shares["C3"] == pytest.approx(0.1, abs=0.001)
    assert sum(shares.values()) == pytest.approx(1.0)


def test_cohort_member_curves_sum_to_cohort_stream(monkeypatch):
    store = _cohort_world(monkeypatch)
    forecast_wells_for_run(run_id=None, user_id=7, forecasts=[_cohort_entry()])
    from server.valuation.forecast import curve_rate, make_curve
    from server.valuation import config
    t = np.arange(0, 25, dtype=float)
    total = np.zeros_like(t)
    for api in ("C1", "C2", "C3"):
        c = orch._deserialize_curve(store.stages["forecast"]["forecasts"][api]["oil"]["curve"])
        total += np.asarray(curve_rate(c, t))
    cohort = make_curve(300.0, 0.04, 0.8, stream="oil",
                        terminal_di_annual=config.ECON.terminal_di_annual)
    np.testing.assert_allclose(total, np.asarray(curve_rate(cohort, t)), rtol=1e-9)


def test_cohort_dry_member_bounces_with_actionable_message(monkeypatch):
    metas = {a: _meta(a, "PRODUCING") for a in ("C1", "C2")}
    prod = {
        "C1": {"months": _HIST_MONTHS, "oil_bbl": [100.0] * _HIST_N, "gas_mcf": [0.0] * _HIST_N},
        "C2": {"months": _HIST_MONTHS, "oil_bbl": [0.0] * _HIST_N, "gas_mcf": [0.0] * _HIST_N},
    }
    _patch(monkeypatch, metas, prod)
    with pytest.raises(ForecastValidationError) as exc:
        forecast_wells_for_run(run_id=None, user_id=7, forecasts=[{
            "wells": ["C1", "C2"], "oil": {"qi": 100.0, "di": 0.05, "b": 0.8}, "gas": None,
            "anchor_month": _ANCHOR, "rationale": "cohort",
        }])
    (v,) = exc.value.violations
    assert v["well"] == "C2" and "forecast it individually" in v["message"]


# ── merge / overwrite semantics ──────────────────────────────────────────────

def test_recommit_overwrites_one_well_and_keeps_others(monkeypatch):
    metas = {"H": _meta("H", "PRODUCING"), "H2": _meta("H2", "PRODUCING")}
    prod = {a: {"months": _HIST_MONTHS, "oil_bbl": _HIST_OIL, "gas_mcf": [0.0] * _HIST_N}
            for a in ("H", "H2")}
    store = _patch(monkeypatch, metas, prod)
    out1 = forecast_wells_for_run(run_id=None, user_id=7, forecasts=[
        _producer_entry(),
        _producer_entry(wells=["H2"]),
    ])
    out2 = forecast_wells_for_run(run_id=out1["run_id"], user_id=7, forecasts=[
        _producer_entry(oil={"qi": 150.0, "di": 0.05, "b": 0.8}),
    ])
    assert out2["wells_committed"] == 1 and out2["wells_in_run"] == 2
    fcs = store.stages["forecast"]["forecasts"]
    assert fcs["H"]["oil"]["curve"]["qi"] == pytest.approx(150.0)     # overwritten
    assert fcs["H2"]["oil"]["curve"]["qi"] == pytest.approx(_LAST_RATE, rel=0.01)  # survived


def test_unknown_and_foreign_run_id_are_rejected(monkeypatch):
    store = _FakeStore()
    store.records["run-owned"] = {"run_id": "run-owned", "user_id": 7}
    _producer_world(monkeypatch, store=store)
    with pytest.raises(ForecastValidationError, match="validation_failed") as exc:
        forecast_wells_for_run(run_id="run-nope", forecasts=[_producer_entry()], user_id=7)
    assert "unknown run_id" in exc.value.violations[0]["message"]
    with pytest.raises(ForecastValidationError) as exc:
        forecast_wells_for_run(run_id="run-owned", forecasts=[_producer_entry()], user_id=8)
    assert "another user" in exc.value.violations[0]["message"]


# ── validation matrix ────────────────────────────────────────────────────────

@pytest.mark.parametrize("mutation, field_frag", [
    ({"oil": {"qi": -5.0, "di": 0.06, "b": 0.9}}, "oil.qi"),
    ({"oil": {"qi": 100.0, "di": 0.0, "b": 0.9}}, "oil.di"),
    ({"oil": {"qi": 100.0, "di": 1.5, "b": 0.9}}, "oil.di"),
    ({"oil": {"qi": 100.0, "di": 0.06, "b": 3.0}}, "oil.b"),
    ({"oil": {"qi": 100.0, "di": 0.06, "b": 0.9, "extra": 1}}, "oil"),
    ({"oil": None, "gas": None}, "oil/gas"),
    ({"uptime_factor": 0.2}, "uptime_factor"),
    ({"anchor_month": "not-a-month"}, "anchor_month"),
    ({"rationale": "  "}, "rationale"),
    ({"struck_months": ["2025-13"]}, "struck_months"),
    ({"wells": []}, "wells"),
])
def test_structural_violations_are_named(monkeypatch, mutation, field_frag):
    _producer_world(monkeypatch)
    with pytest.raises(ForecastValidationError) as exc:
        forecast_wells_for_run(run_id=None, user_id=7, forecasts=[_producer_entry(**mutation)])
    assert any(v["field"].startswith(field_frag) for v in exc.value.violations), \
        exc.value.violations


def test_producer_future_anchor_rejected(monkeypatch):
    _producer_world(monkeypatch)
    with pytest.raises(ForecastValidationError) as exc:
        forecast_wells_for_run(run_id=None, user_id=7, forecasts=[_producer_entry(anchor_month=_FUTURE)])
    assert "must not be in the future" in exc.value.violations[0]["message"]


def test_undrilled_past_anchor_rejected(monkeypatch):
    metas = {"P": _meta("P", "PERMITTED")}
    _patch(monkeypatch, metas, prod={})
    with pytest.raises(ForecastValidationError) as exc:
        forecast_wells_for_run(run_id=None, user_id=7, forecasts=[{
            "wells": ["P"], "oil": {"qi": 800.0, "di": 0.10, "b": 1.1}, "gas": None,
            "anchor_month": "2024-01", "rationale": "x",
        }])
    assert "asserted first-production month" in exc.value.violations[0]["message"]


def test_all_or_nothing_on_mixed_call(monkeypatch):
    """One bad entry poisons the whole call: nothing persisted, every violation listed."""
    store = _producer_world(monkeypatch)
    with pytest.raises(ForecastValidationError) as exc:
        forecast_wells_for_run(run_id=None, user_id=7, forecasts=[
            _producer_entry(),
            {"wells": ["H"], "oil": {"qi": 1.0, "di": 0.05, "b": 5.0}, "gas": None,
             "anchor_month": _ANCHOR, "rationale": "bad b"},
        ])
    # duplicate-well violation for H appearing twice + the b bound
    fields = {v["field"] for v in exc.value.violations}
    assert "oil.b" in fields
    assert store.stages.get("forecast") is None


def test_duplicate_well_across_entries_rejected(monkeypatch):
    _producer_world(monkeypatch)
    with pytest.raises(ForecastValidationError) as exc:
        forecast_wells_for_run(run_id=None, user_id=7, forecasts=[
            _producer_entry(), _producer_entry(oil={"qi": 100.0, "di": 0.05, "b": 0.8}),
        ])
    assert any("already appears" in v["message"] for v in exc.value.violations)


def test_unknown_api_rejected(monkeypatch):
    _producer_world(monkeypatch)
    with pytest.raises(ForecastValidationError) as exc:
        forecast_wells_for_run(run_id=None, user_id=7, forecasts=[_producer_entry(wells=["NOPE"])])
    assert "not found in public.wells" in exc.value.violations[0]["message"]


# ── legacy fit-era stages still replay ───────────────────────────────────────

def _legacy_curve(qi_peak):
    return {"qi_peak": qi_peak, "di": 0.05, "b": 0.8, "terminal_di_monthly": 0.05 / 12,
            "switch_month_from_peak": None, "stream": "oil",
            "provenance": {"source": "fit", "strategy": "history"}}


def test_legacy_stage_replays_with_peak_offset_and_capex_fallback():
    stage = {"forecasts": {
        "OLD-PDP": {
            "oil": {"curve": _legacy_curve(900.0), "peak_month": "2024-01"},
            "gas": {"curve": {**_legacy_curve(0.0), "stream": "gas"}},
            "classification": "history", "strategy": "history", "status": "PRODUCING",
            "anchor_month": "2025-06",
        },
        "OLD-PUD": {
            "oil": {"curve": _legacy_curve(800.0)},
            "gas": {"curve": {**_legacy_curve(0.0), "stream": "gas"}},
            "classification": "no_history", "strategy": "pure_analog", "status": "PERMITTED",
        },
    }}
    fcs, needs_capex, statuses = orch._load_forecast_stage(
        forecast=stage, as_of=date(2026, 8, 1), months_override=None)
    # legacy qi_peak deserializes; peak offset honored (17 months peak→anchor)
    from server.valuation.forecast import curve_rate, project
    f = orch._deserialize_forecast(fcs["OLD-PDP"]["oil"])
    assert f.curve.qi == 900.0
    _mo, rates = project(f, horizon_months=2)
    assert rates[0] == pytest.approx(float(curve_rate(f.curve, 17.0)))
    # anchor-less PUD dated by the config fallback (+36mo from as_of next month)
    assert fcs["OLD-PUD"]["oil"]["start_date"] == "2029-09-01"
    assert needs_capex == {"OLD-PDP": False, "OLD-PUD": True}
    assert statuses["OLD-PUD"] == "PERMITTED"


@pytest.mark.db  # run_valuation_for_run loads the strip curve from the DB
def test_forecast_then_deal_valuation_round_trip(monkeypatch):
    metas = {"H": _meta("H", "PRODUCING"), "P": _meta("P", "PERMITTED")}
    prod = {"H": {"months": _HIST_MONTHS, "oil_bbl": _HIST_OIL, "gas_mcf": [0.0] * _HIST_N}}
    _patch(monkeypatch, metas, prod)
    out = forecast_wells_for_run(run_id=None, user_id=7, forecasts=[
        _producer_entry(),
        {"wells": ["P"], "oil": {"qi": 800.0, "di": 0.10, "b": 1.1}, "gas": None,
         "anchor_month": _FUTURE, "rationale": "offset level, operator cadence"},
    ])
    res = orch.run_valuation_for_run(run_id=out["run_id"], user_id=7, params={
        "interest_type": "minerals", "interest": {"decimal": 0.05},
        "asset_list": {"well_apis": ["H", "P"]}, "economics_overrides": {}})
    assert "total" in res["npv_at_centers"]


def test_run_valuation_refuses_a_run_the_caller_does_not_own(monkeypatch):
    """The valuation writes the run's economics stage, so it proves ownership
    before reading anything — with no DB in the loop here, reaching the
    forecast stage would be the failure."""
    metas = {"H": _meta("H", "PRODUCING")}
    store = _patch(monkeypatch, metas, {})
    store.records["run-1"] = {"run_id": "run-1", "user_id": 7}
    params = {"interest_type": "minerals", "interest": {"decimal": 0.05},
              "asset_list": {"well_apis": ["H"]}, "economics_overrides": {}}
    with pytest.raises(orch.RunAccessError, match="another user"):
        orch.run_valuation_for_run(run_id="run-1", params=params, user_id=8)
    with pytest.raises(orch.RunAccessError, match="unknown run_id"):
        orch.run_valuation_for_run(run_id="run-9", params=params, user_id=7)
