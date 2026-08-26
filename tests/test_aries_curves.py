"""aries-to-valuation translator: pinned conventions, engine drift, CLI.

The decline-conversion constants are pinned against pairs ARIES itself
stored (AC_FCST carries both DECLINERATE and NOMINALRATE): a real database's
78 segments matched these formulas to 1e-9, and per-well EURs rebuilt from
section-4 lines matched the shop's own oneliner to <=0.013% per stream.
"""

import importlib.util
import json
import math
import subprocess
import sys
from pathlib import Path

_SKILL_DIR = Path(__file__).resolve().parent.parent / "skills" / "aries-to-valuation"
_SCRIPT = _SKILL_DIR / "aries_curves.py"

_spec = importlib.util.spec_from_file_location("aries_curves", _SCRIPT)
ac = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ac)


# ── pinned conversion (values ARIES itself stored) ───────────────────────────

def test_effective_to_nominal_exponential_matches_aries():
    # ExpRT segment: DECLINERATE 7 (%), b=0 -> NOMINALRATE 0.006047557736236292
    assert math.isclose(ac.a_mo_from_eff(0.07, 0.0), 0.006047557736236292,
                        rel_tol=1e-12)


def test_effective_to_nominal_hyperbolic_matches_aries():
    # HyperRT segment: DECLINERATE 72.3 (%), b=0.9 -> NOMINALRATE 0.2014054590842716
    assert math.isclose(ac.a_mo_from_eff(0.723, 0.9), 0.2014054590842716,
                        rel_tol=1e-12)


def test_closed_form_cum_matches_numerical_integration():
    for q0, a, b in [(5278.048, 0.05163924, 0.9), (1000.0, 0.006, 0.0),
                     (2000.0, 0.05, 1.0)]:
        t, steps = 179.0, 200_000
        dt = t / steps
        numeric = sum(ac.q_at(q0, a, b, (i + 0.5) * dt) for i in range(steps)) * dt
        assert math.isclose(ac.cum(q0, a, b, t), numeric, rel_tol=1e-6)


def test_eur_with_terminal_switch_and_floor():
    # Switch where the local nominal decline shallows to a_term, exponential
    # tail to the floor; independently reproduced by numeric integration.
    q0, a0, b, a_term, floor = 5000.0, 0.05, 0.9, 0.006, 30.0
    eur = ac.eur_with_terminal(q0, a0, b, a_term, floor=floor)
    t_sw = (a0 / a_term - 1) / (b * a0)
    q_sw = ac.q_at(q0, a0, b, t_sw)
    t2 = math.log(q_sw / floor) / a_term
    steps = 400_000
    total_t = t_sw + t2
    dt = total_t / steps

    def q(t):
        return (ac.q_at(q0, a0, b, t) if t < t_sw
                else q_sw * math.exp(-a_term * (t - t_sw)))

    numeric = sum(q((i + 0.5) * dt) for i in range(steps)) * dt
    assert math.isclose(eur, numeric, rel_tol=1e-5)


# ── engine-constant drift ─────────────────────────────────────────────────────

def test_engine_constants_match_config():
    from server.valuation.config import ECON
    assert ac.ENGINE_TERMINAL_DI_ANNUAL_NOMINAL == ECON.terminal_di_annual
    assert ac.ENGINE_HORIZON_MONTHS == ECON.horizon_months


def test_api_formatting():
    assert ac.format_api10("42227410930000") == "42-227-41093"
    assert ac.format_api10("4222741093") == "42-227-41093"
    assert ac.format_api10("41093") is None       # never fabricate digits
    assert ac.format_api10("") is None


# ── end to end over a synthetic _aries fixture ───────────────────────────────

def _write_fixture(root: Path):
    tables = root / "tables"
    tables.mkdir(parents=True)
    (root / "manifest.json").write_text(json.dumps(
        {"database": {"file": "t.accdb", "size_bytes": 1, "sha256": "ab" * 32}}))
    tables.joinpath("AC_PROPERTY.csv").write_text(
        "PROPNUM,LEASE,WELLNUM,API,RSV_CAT\n"
        "P1,ALPHA,1H,42227410930000,1PDP\n"
        "P2,BRAVO,2H,42227410940000,1PDP\n"
        "P3,NOAPI,3H,,1PDP\n")
    econ = [
        # P1: the proven shape, both streams
        "P1,4,10,BASE,CUMS,100.0 200.0 0 0 0 50.0",
        "P1,4,20,BASE,START,01/2025",
        "P1,4,30,BASE,OIL,5278.048 X B/M 7.000000 EXP B/0.9000 38.887800",
        'P1,4,40,BASE,"""",X 30.00000 B/M X YRS EXP 7.000000',
        "P1,4,50,BASE,START,01/2025",
        "P1,4,60,BASE,GAS,16049.072 X M/M 7.000000 EXP B/0.9000 41.921296",
        'P1,4,70,BASE,"""",X 1.00000 M/M X YRS EXP 7.000000',
        "P1,2,80,BASE,SHRINK,0.65",
        "P1,4,90,BASE,NGL/GAS,0.10 X B/M TO LIFE LOG TIME",
        # P2: untranslatable oil (type-curve lookup)
        "P2,4,10,BASE,START,07/2026",
        "P2,4,20,BASE,OIL,LOOKUP TC_PROD @M.GEOZONE",
        # P3: fine curve, but no API
        "P3,4,10,BASE,START,01/2025",
        "P3,4,20,BASE,OIL,1000 X B/M 7.000000 EXP B/0.9000 40.0",
        'P3,4,30,BASE,"""",X 30.00000 B/M X YRS EXP 7.000000',
    ]
    tables.joinpath("AC_ECONOMIC.csv").write_text(
        "PROPNUM,SECTION,SEQUENCE,QUALIFIER,KEYWORD,EXPRESSION\n" + "\n".join(econ) + "\n")


def test_cli_end_to_end(tmp_path):
    _write_fixture(tmp_path / "_aries")
    out = tmp_path / "payload.json"
    proc = subprocess.run(
        [sys.executable, str(_SCRIPT), str(tmp_path / "_aries"), "--payload", str(out)],
        capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(out.read_text())

    # P1 translated on both streams; P2 refused (lookup); P3 refused (no API)
    assert len(payload["entries"]) == 1
    e = payload["entries"][0]
    assert e["wells"] == ["42-227-41093"]
    assert e["anchor_month"] == "2025-01"
    assert math.isclose(e["oil"]["qi"], 5278.048)
    assert e["oil"]["b"] == 0.9
    assert math.isclose(e["oil"]["di"], ac.a_mo_from_eff(0.388878, 0.9), rel_tol=1e-4)
    assert e["gas"]["qi"] == 16049.072
    # rationale carries the verbatim line and the attribution
    assert "5278.048 X B/M 7.000000 EXP B/0.9000 38.887800" in e["rationale"]
    assert "adopted verbatim" in e["rationale"]

    reasons = {(x["well"], x["stream"]): x["reason"] for x in payload["report"]["refusals"]}
    assert any(k[0] == "BRAVO 2H" and "unrecognized main-line shape" in v
               for k, v in reasons.items())
    assert any(k[0] == "NOAPI 3H" and "no API" in v for k, v in reasons.items())

    # the not-modeled constructs surface in the printed report
    assert "NGL yield" in proc.stdout
    assert "SHRINK 0.65" in proc.stdout
    assert "NOT TRANSLATED" in proc.stdout


def test_cli_tieout_flags_translation_health(tmp_path):
    _write_fixture(tmp_path / "_aries")
    # Answer key built with the same conventions -> residual ~0; life omitted
    # so the tail runs to the floor (matching eur_with_terminal exactly).
    a0 = ac.a_mo_from_eff(0.388878, 0.9)
    eur = ac.eur_with_terminal(5278.048, a0, 0.9, ac.a_mo_from_eff(0.07, 0.0), floor=30.0)
    key = {"42-227-41093": {"ult_oil": 100_000 + eur}}
    (tmp_path / "oneliner.json").write_text(json.dumps(key))
    proc = subprocess.run(
        [sys.executable, str(_SCRIPT), str(tmp_path / "_aries"),
         "--payload", str(tmp_path / "p.json"), "--tieout", str(tmp_path / "oneliner.json")],
        capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    assert "mean |err| 0.000%" in proc.stdout
