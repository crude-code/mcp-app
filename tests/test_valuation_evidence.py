# tests/test_valuation_evidence.py — analog_cohort validation + evidence assembly.
import numpy as np
import pytest
from datetime import date

from dateutil.relativedelta import relativedelta

import server.valuation.orchestrator as orch
from server.valuation.evidence import build_evidence, collect_analog_apis
from server.valuation.forecast import make_curve
from server.valuation.orchestrator import (
    ForecastValidationError, _serialize_curve, forecast_wells_for_run,
)
from server.valuation.types import WellMeta


# ── shared fakes (pattern from test_valuation_forecast_unified) ──────────────

class _FakeStore:
    def __init__(self):
        self.stages = {}
        self.records = {}
    def new_run(self, *, user_id, case_file):
        self.records["run-1"] = {"run_id": "run-1", "user_id": user_id}
        return "run-1"
    def write_stage(self, run_id, *, stage, payload): self.stages[stage] = payload
    def read_stage(self, run_id, *, stage): return self.stages.get(stage)
    def get(self, run_id): return self.records.get(run_id)


def _meta(api, status, lateral=10000.0, n_hist=0, geom=None, name=None, operator="MEWBOURNE"):
    return WellMeta(api=api, status=status, basin="DELAWARE", formation="WOLFCAMP A",
                    county="REEVES", lateral_ft=lateral, spud_date=None,
                    completion_date=None, first_prod_date=None, last_prod_date=None,
                    n_history_months=n_hist, planned_first_prod_date=None,
                    geom_wkt=geom, operator=operator, well_name=name)


def _patch(monkeypatch, metas, prod, store=None):
    store = store or _FakeStore()
    monkeypatch.setattr(orch, "ValuationRunStore", lambda: store)
    monkeypatch.setattr(orch, "bulk_load_wells", lambda apis: [metas[a] for a in apis if a in metas])
    monkeypatch.setattr(orch, "bulk_load_production",
                        lambda apis: {a: prod.get(a, {"months": [], "oil_bbl": [], "gas_mcf": []})
                                      for a in apis})
    return store


_TODAY = date.today().replace(day=1)
_FUTURE = (_TODAY + relativedelta(months=6)).strftime("%Y-%m")


def _hist(n, qi=900.0, d=0.06):
    months = [(_TODAY - relativedelta(months=n - i)).isoformat() for i in range(n)]
    oil = list(qi * np.exp(-d * np.arange(n)))
    return {"months": months, "oil_bbl": oil, "gas_mcf": [0.0] * n}


def _pud_entry(**over):
    entry = {
        "wells": ["PUD1"],
        "oil": {"qi": 21000, "di": 0.24, "b": 1.2},
        "gas": None,
        "anchor_month": _FUTURE,
        "rationale": "type curve from the kept analogs, qi scaled to the planned lateral",
        "analog_cohort": {
            "curve_label": "Wolfcamp A · 10,000 ft",
            "criteria": "Wolfcamp A · 8-12k ft lateral · 2019+ · within 3 mi",
            "kept": ["AN1", "AN2"],
            "excluded": [{"api": "AX1", "reason": "different formation"}],
        },
    }
    entry.update(over)
    return entry


def _analog_world(monkeypatch, store=None, **meta_over):
    metas = {
        "PUD1": _meta("PUD1", "PERMITTED", name="BOBCAT 101H"),
        "AN1": _meta("AN1", "PRODUCING", n_hist=30, name="AJAX 1H",
                     geom="POINT(-103.5 31.5)"),
        "AN2": _meta("AN2", "PRODUCING", n_hist=28, name="AJAX 2H",
                     geom="POINT(-103.52 31.52)"),
        "AX1": _meta("AX1", "PRODUCING", n_hist=40, name="BIGHORN 14H",
                     geom="POINT(-103.48 31.49)"),
    }
    metas.update(meta_over)
    prod = {"AN1": _hist(30), "AN2": _hist(28, qi=700.0)}
    return _patch(monkeypatch, metas, prod, store=store)


def _violation_fields(excinfo):
    return {v["field"] for v in excinfo.value.violations}


# ── analog_cohort validation ─────────────────────────────────────────────────

def test_analog_cohort_commits_and_persists(monkeypatch):
    store = _analog_world(monkeypatch)
    result = forecast_wells_for_run(run_id=None, user_id=7, forecasts=[_pud_entry()])
    echo = result["committed"][0]["analog_cohort"]
    assert echo == {"curve_label": "Wolfcamp A · 10,000 ft", "kept": 2, "excluded": 1}
    saved = store.stages["forecast"]["forecasts"]["PUD1"]["assertion"]
    assert saved["analog_cohort"]["kept"] == ["AN1", "AN2"]
    assert saved["analog_cohort"]["normalization"] == "per_1000ft"
    assert saved["entry_id"]


@pytest.mark.parametrize("mutation, field_frag", [
    ({"analog_cohort": "not a dict"}, "analog_cohort"),
    ({"analog_cohort": {"criteria": "x", "kept": ["AN1"]}}, "analog_cohort"),          # no label
    ({"analog_cohort": {"curve_label": "L", "criteria": " ", "kept": ["AN1"]}}, "criteria"),
    ({"analog_cohort": {"curve_label": "L", "criteria": "c", "kept": []}}, "kept"),
    ({"analog_cohort": {"curve_label": "L", "criteria": "c", "kept": ["AN1", "AN1"]}}, "kept"),
    ({"analog_cohort": {"curve_label": "L", "criteria": "c", "kept": ["AN1"],
                        "normalization": "per_acre"}}, "normalization"),
    ({"analog_cohort": {"curve_label": "L", "criteria": "c", "kept": ["AN1"],
                        "excluded": [{"api": "AX1"}]}}, "excluded"),
    ({"analog_cohort": {"curve_label": "L", "criteria": "c", "kept": ["AN1"],
                        "excluded": [{"api": "AN1", "reason": "dup"}]}}, "analog_cohort"),
])
def test_analog_cohort_structural_violations(monkeypatch, mutation, field_frag):
    _analog_world(monkeypatch)
    with pytest.raises(ForecastValidationError) as e:
        forecast_wells_for_run(run_id=None, user_id=7, forecasts=[_pud_entry(**mutation)])
    assert any(field_frag in f for f in _violation_fields(e))


def test_analog_cohort_subject_as_own_analog_bounces(monkeypatch):
    _analog_world(monkeypatch)
    entry = _pud_entry()
    entry["analog_cohort"]["kept"] = ["AN1", "PUD1"]
    with pytest.raises(ForecastValidationError) as e:
        forecast_wells_for_run(run_id=None, user_id=7, forecasts=[entry])
    assert any("own analog" in v["message"] for v in e.value.violations)


def test_analog_cohort_unknown_api_bounces(monkeypatch):
    _analog_world(monkeypatch)
    entry = _pud_entry()
    entry["analog_cohort"]["kept"] = ["AN1", "NOPE"]
    with pytest.raises(ForecastValidationError) as e:
        forecast_wells_for_run(run_id=None, user_id=7, forecasts=[entry])
    assert any("NOPE not found" in v["message"] for v in e.value.violations)


def test_analog_cohort_kept_analog_without_history_bounces(monkeypatch):
    _analog_world(monkeypatch, AN2=_meta("AN2", "PRODUCING", n_hist=0))
    with pytest.raises(ForecastValidationError) as e:
        forecast_wells_for_run(run_id=None, user_id=7, forecasts=[_pud_entry()])
    assert any("no reported production" in v["message"] for v in e.value.violations)


def test_entry_without_analog_cohort_still_commits(monkeypatch):
    store = _analog_world(monkeypatch)
    entry = _pud_entry()
    del entry["analog_cohort"]
    forecast_wells_for_run(run_id=None, user_id=7, forecasts=[entry])
    assert store.stages["forecast"]["forecasts"]["PUD1"]["assertion"]["analog_cohort"] is None


# ── evidence assembly (pure) ─────────────────────────────────────────────────

def _curve_dict(qi, di=0.05, b=1.0, stream="oil"):
    return _serialize_curve(make_curve(qi, di, b, stream=stream, terminal_di_annual=0.05))


def _fc_entry(status, qi_oil, anchor, assertion_extra=None, entry_id="e1", rationale="r"):
    assertion = {
        "entry_id": entry_id,
        "asserted": {"oil": {"qi": qi_oil, "di": 0.05, "b": 1.0}, "gas": None},
        "uptime_factor": 1.0, "struck_months": [], "rationale": rationale,
        "cohort": None, "analog_cohort": None, "committed_at": "t",
    }
    assertion.update(assertion_extra or {})
    return {
        "anchor_month": anchor, "status": status, "needs_capex": status != "PRODUCING",
        "assertion": assertion,
        "oil": {"curve": _curve_dict(qi_oil)},
        "gas": {"curve": _curve_dict(0.0)},
    }


_RATES = {"PDP": 0.15, "DUC": 0.20, "PUD": 0.25}


def _schedule(apis, cf=1000.0, n=24):
    return {"origin": "2026-09-01",
            "by_well": {a: {"net_cashflow": [cf] * n} for a in apis}}


def test_evidence_producing_single_has_hist_curve_and_pv():
    hist = _hist(20)
    anchor = hist["months"][-1][:7]
    forecast = {"forecasts": {"W1": _fc_entry("PRODUCING", 500.0, anchor)}}
    out = build_evidence(
        forecast=forecast, schedule=_schedule(["W1"]),
        meta_by_api={"W1": _meta("W1", "PRODUCING", n_hist=20, name="HORTON 18H")},
        prod={"W1": hist}, analog_meta={}, analog_prod={}, rate_centers=_RATES)
    (e,) = out["entries"]
    assert e["kind"] == "producing" and e["label"] == "HORTON 18H"
    assert e["pv"] and e["pv_share"] == 1.0
    assert len(e["hist"]["months"]) == 20
    assert e["curve"]["start_month"] == anchor
    assert e["curve"]["overlap_months"] == 1          # anchored at the last month
    assert e["curve"]["oil"][0] == 500.0
    assert e["assertion"]["rationale"] == "r"


def test_evidence_hist_capped_at_60_months():
    hist = _hist(80)
    anchor = hist["months"][-1][:7]
    forecast = {"forecasts": {"W1": _fc_entry("PRODUCING", 500.0, anchor)}}
    out = build_evidence(forecast=forecast, schedule=_schedule(["W1"]),
                         meta_by_api={"W1": _meta("W1", "PRODUCING")}, prod={"W1": hist},
                         analog_meta={}, analog_prod={}, rate_centers=_RATES)
    assert len(out["entries"][0]["hist"]["months"]) == 60


def test_evidence_cohort_groups_into_one_entry_with_summed_history():
    hist_a, hist_b = _hist(20), _hist(20, qi=300.0)
    anchor = hist_a["months"][-1][:7]
    cohort = {"cohort": {"wells": ["A", "B"], "shares": {"oil": {"A": 0.7, "B": 0.3}}}}
    forecast = {"forecasts": {
        "A": _fc_entry("PRODUCING", 350.0, anchor, cohort, entry_id="eC"),
        "B": _fc_entry("PRODUCING", 150.0, anchor, cohort, entry_id="eC"),
    }}
    out = build_evidence(forecast=forecast, schedule=_schedule(["A", "B"]),
                         meta_by_api={"A": _meta("A", "PRODUCING"), "B": _meta("B", "PRODUCING")},
                         prod={"A": hist_a, "B": hist_b},
                         analog_meta={}, analog_prod={}, rate_centers=_RATES)
    (e,) = out["entries"]
    assert len(e["wells"]) == 2
    assert e["hist"]["oil"][0] == round(hist_a["oil_bbl"][0] + hist_b["oil_bbl"][0], 1)
    assert e["curve"]["oil"][0] == 500.0              # member curves sum
    assert e["pv"] == 2 * out["entries"][0]["wells"][0]["pv"]


def test_evidence_type_curve_merges_by_label_and_hydrates_analogs():
    ac = {"analog_cohort": {
        "curve_label": "WC A long", "criteria": "c", "normalization": "per_1000ft",
        "kept": ["AN1"], "excluded": [{"api": "AX1", "reason": "different formation"}],
    }}
    forecast = {"forecasts": {
        "P1": _fc_entry("PERMITTED", 2000.0, "2027-02", ac, entry_id="p1"),
        "P2": _fc_entry("PERMITTED", 2000.0, "2027-02", ac, entry_id="p2"),
    }}
    an_meta = {"AN1": _meta("AN1", "PRODUCING", lateral=8000.0, n_hist=30,
                            geom="POINT(-103.5 31.5)", name="AJAX 1H"),
               "AX1": _meta("AX1", "PRODUCING", geom="POINT(-103.6 31.6)")}
    out = build_evidence(
        forecast=forecast, schedule=_schedule(["P1", "P2"]),
        meta_by_api={"P1": _meta("P1", "PERMITTED", lateral=10000.0, geom="POINT(-103.55 31.55)"),
                     "P2": _meta("P2", "PERMITTED", lateral=10000.0, geom="POINT(-103.56 31.55)")},
        prod={}, analog_meta=an_meta, analog_prod={"AN1": _hist(30)},
        rate_centers=_RATES)
    (e,) = out["entries"]                              # merged by curve_label
    assert e["kind"] == "undrilled" and e["label"] == "WC A long"
    assert len(e["wells"]) == 2
    tc = e["type_curve"]
    assert tc["plan_lat_ft"] == 10000
    assert tc["series"][0] == 200.0                    # 2000 × 1000/10000
    (kept,) = tc["kept"]
    assert kept["series"][0] == round(_hist(30)["oil_bbl"][0] * 1000 / 8000.0, 1)
    assert kept["first_prod"] and kept["cum12_oil"]
    assert tc["excluded"][0]["reason"] == "different formation"
    assert tc["map"] and len(tc["map"]["subjects"]) == 2
    assert all(k["x"] is not None for k in tc["kept"])


def test_evidence_absolute_normalization_when_lateral_missing():
    ac = {"analog_cohort": {"curve_label": "L", "criteria": "c",
                            "normalization": "per_1000ft", "kept": ["AN1"], "excluded": []}}
    forecast = {"forecasts": {"P1": _fc_entry("PERMITTED", 2000.0, "2027-02", ac)}}
    out = build_evidence(
        forecast=forecast, schedule=_schedule(["P1"]),
        meta_by_api={"P1": _meta("P1", "PERMITTED", lateral=None)},
        prod={}, analog_meta={"AN1": _meta("AN1", "PRODUCING", n_hist=30)},
        analog_prod={"AN1": _hist(30)}, rate_centers=_RATES)
    tc = out["entries"][0]["type_curve"]
    assert tc["normalization"] == "absolute"
    assert tc["series"][0] == 2000.0


def test_evidence_pv_none_when_by_well_omitted():
    hist = _hist(12)
    forecast = {"forecasts": {"W1": _fc_entry("PRODUCING", 500.0, hist["months"][-1][:7])}}
    out = build_evidence(forecast=forecast,
                         schedule={"origin": "2026-09-01"},          # no by_well (audit cap)
                         meta_by_api={"W1": _meta("W1", "PRODUCING")}, prod={"W1": hist},
                         analog_meta={}, analog_prod={}, rate_centers=_RATES)
    assert out["entries"][0]["pv"] is None
    assert out["entries"][0]["pv_share"] is None


def test_evidence_legacy_stage_without_assertion_survives():
    hist = _hist(12)
    forecast = {"forecasts": {"W1": {
        "anchor_month": None, "status": "PRODUCING",
        "oil": {"curve": _curve_dict(500.0)}, "gas": {"curve": _curve_dict(0.0)},
    }}}
    out = build_evidence(forecast=forecast, schedule=_schedule(["W1"]),
                         meta_by_api={"W1": _meta("W1", "PRODUCING")}, prod={"W1": hist},
                         analog_meta={}, analog_prod={}, rate_centers=_RATES)
    (e,) = out["entries"]
    assert e["assertion"] is None and e["kind"] == "producing"
    assert "curve" not in e                            # no anchor → no curve series


def test_collect_analog_apis():
    ac = {"curve_label": "L", "criteria": "c", "kept": ["K1", "K2"],
          "excluded": [{"api": "X1", "reason": "r"}]}
    forecast = {"forecasts": {
        "P1": {"assertion": {"analog_cohort": ac}},
        "W1": {"assertion": {"analog_cohort": None}},
        "L1": {},
    }}
    kept, all_ = collect_analog_apis(forecast)
    assert kept == ["K1", "K2"]
    assert all_ == ["K1", "K2", "X1"]
