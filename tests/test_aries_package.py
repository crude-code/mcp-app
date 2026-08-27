"""aries-writeback packager: reverse conversion, round-trip, CLI, guards.

The load-bearing guarantee: a package we export, parsed back through the
FORWARD translator (aries-to-valuation's parser and effective->nominal
conversion), reproduces the engine parameters we started from. The two
skills implement the pinned conventions in opposite directions, so the
round-trip is an independent check, not a tautology.
"""

import importlib.util
import json
import math
import subprocess
import sys
import zipfile
from pathlib import Path

_SKILLS = Path(__file__).resolve().parent.parent / "skills"
_PACKAGE = _SKILLS / "aries-writeback" / "aries_package.py"
_CURVES = _SKILLS / "aries-to-valuation" / "aries_curves.py"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


pk = _load("aries_package", _PACKAGE)
fw = _load("aries_curves", _CURVES)


def test_reverse_conversion_inverts_forward():
    for a, b in [(0.006047557736236292, 0.0), (0.2014054590842716, 0.9),
                 (0.0516, 0.9), (0.03, 0.95), (0.08, 1.0)]:
        D = pk.eff_annual_from_nominal_monthly(a, b)
        assert math.isclose(fw.a_mo_from_eff(D, b), a, rel_tol=1e-12)


def test_engine_terminal_matches_config():
    from server.valuation.config import ECON
    assert pk.ENGINE_TERMINAL_DI_ANNUAL_NOMINAL == ECON.terminal_di_annual


def test_phase_lines_round_trip_through_forward_parser():
    params = {"qi": 5278.048, "di": 0.05163924, "b": 0.9}
    main, ditto = pk.phase_lines(params, "B/M", 30.0)
    curve, why = fw.parse_phase(main, [ditto])
    assert why is None, why
    assert math.isclose(curve["qi"], params["qi"], rel_tol=1e-9)
    assert curve["b"] == params["b"]
    assert math.isclose(curve["di_nominal_monthly"], params["di"], rel_tol=1e-6)


def _spec(qualifier="CC2608"):
    return {"qualifier": qualifier, "wells": [{
        "api": "42-227-41093", "propnum": "WA7J0J6TB6", "name": "TEST 1H",
        "anchor_month": "2026-08",
        "cums": {"oil_bbl": 293746, "gas_mcf": 450892},
        "oil": {"qi": 5278.048, "di": 0.05163924, "b": 0.9},
        "gas": {"qi": 16049.072, "di": 0.05840187, "b": 0.9},
    }, {
        "api": "42-227-41094", "anchor_month": "2026-09",
        "oil": {"qi": 900.0, "di": 0.03, "b": 0.85}, "gas": None,
    }]}


def test_cli_builds_importable_package(tmp_path):
    (tmp_path / "curves.json").write_text(json.dumps(_spec()))
    out = tmp_path / "pkg.zip"
    proc = subprocess.run(
        [sys.executable, str(_PACKAGE), str(tmp_path / "curves.json"), "--out", str(out)],
        capture_output=True, text=True, cwd=tmp_path)
    assert proc.returncode == 0, proc.stderr
    with zipfile.ZipFile(out) as z:
        names = set(z.namelist())
        assert names == {"AC_ECONOMIC.csv", "crosswalk.csv", "README.md"}
        econ = z.read("AC_ECONOMIC.csv").decode().splitlines()
        readme = z.read("README.md").decode()
        cross = z.read("crosswalk.csv").decode()

    assert econ[0] == "PROPNUM,SECTION,SEQUENCE,QUALIFIER,KEYWORD,EXPRESSION"
    # well 1: CUMS + (START, OIL, ditto) + (START, GAS, ditto); well 2: oil only
    assert sum(1 for r in econ[1:] if r.startswith("WA7J0J6TB6,")) == 7
    assert any(",CUMS," in r and "293.746 450.892" in r for r in econ)
    assert all(",CC2608," in r for r in econ[1:])
    # unknown propnum -> labeled placeholder, README carries the join guidance
    assert "API:42-227-41094" in cross
    assert "fill unknown PROPNUMs" in readme.lower() or "PROPNUM" in readme
    assert "Append" in readme

    # every emitted rate line survives the forward parser
    import csv as _csv
    by_prop: dict = {}
    for propnum, _s, _q, _qual, kw, expr in _csv.reader(econ[1:]):
        if kw in ("OIL", "GAS"):
            by_prop[(propnum, kw)] = {"main": expr, "dittos": []}
            last = (propnum, kw)
        elif kw == '"':
            by_prop[last]["dittos"].append(expr)
    assert by_prop
    for (_, kw), ph in by_prop.items():
        curve, why = fw.parse_phase(ph["main"], ph["dittos"])
        assert why is None, f"{kw}: {why} ({ph})"


def test_cli_refuses_existing_qualifier(tmp_path):
    aries = tmp_path / "_aries" / "tables"
    aries.mkdir(parents=True)
    aries.joinpath("AC_ECONOMIC.csv").write_text(
        "PROPNUM,SECTION,SEQUENCE,QUALIFIER,KEYWORD,EXPRESSION\n"
        "P1,4,10,CC2608,START,01/2025\n")
    aries.joinpath("AC_PROPERTY.csv").write_text("PROPNUM,API\nP1,42227410930000\n")
    (tmp_path / "curves.json").write_text(json.dumps(_spec("CC2608")))
    proc = subprocess.run(
        [sys.executable, str(_PACKAGE), str(tmp_path / "curves.json"),
         "--aries-dir", str(tmp_path / "_aries"), "--out", str(tmp_path / "x.zip")],
        capture_output=True, text=True)
    assert proc.returncode != 0
    assert "already exists" in proc.stderr


def test_aries_dir_fills_propnum_by_api(tmp_path):
    aries = tmp_path / "_aries" / "tables"
    aries.mkdir(parents=True)
    aries.joinpath("AC_ECONOMIC.csv").write_text(
        "PROPNUM,SECTION,SEQUENCE,QUALIFIER,KEYWORD,EXPRESSION\n")
    aries.joinpath("AC_PROPERTY.csv").write_text(
        "PROPNUM,LEASE,WELLNUM,API\nZZTOP,BRAVO,2H,42227410940000\n")
    (tmp_path / "curves.json").write_text(json.dumps(_spec()))
    out = tmp_path / "pkg.zip"
    proc = subprocess.run(
        [sys.executable, str(_PACKAGE), str(tmp_path / "curves.json"),
         "--aries-dir", str(tmp_path / "_aries"), "--out", str(out)],
        capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    with zipfile.ZipFile(out) as z:
        cross = z.read("crosswalk.csv").decode()
    assert "ZZTOP" in cross and "API:42-227-41094" not in cross
