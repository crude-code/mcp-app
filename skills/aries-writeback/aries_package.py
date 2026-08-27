"""Build an ARIES import package (zip of CSVs) from Crude Code forecasts.

The reverse of aries-to-valuation's translator: takes decline curves in the
engine's own terms (qi units/month, di nominal MONTHLY, b) and emits ARIES
section-4 rate lines under a NEW qualifier, as CSV rows an engineer appends
to their own copy of the database (MS Access import, or any ARIES text
import their build offers). Conversions use the pinned conventions from the
explorer's ARIES.md — a quoted ARIES decline is EFFECTIVE ANNUAL (secant):

    D = 1 - (1 + 12*b*a)^(-1/b)      (b > 0;  D = 1 - e^(-12a) at b = 0)

Input `curves.json`:
  {
    "qualifier": "CC2608",              # NEW qualifier — never an existing one
    "wells": [{
      "api": "42-227-41093",            # required
      "propnum": "WA7J0J6TB6",          # their PROPNUM when known (see --aries-dir)
      "name": "SHOOTER 2646WA",         # display, for the crosswalk
      "anchor_month": "2026-08",        # -> START MM/YYYY
      "cums": {"oil_bbl": 293746, "gas_mcf": 450892},   # optional -> CUMS (thousands)
      "oil": {"qi": 5278.0, "di": 0.0516, "b": 0.9},     # engine terms; null to skip
      "gas": {"qi": 16049.0, "di": 0.0584, "b": 0.9}
    }]
  }

`--aries-dir _aries` (the explorer's triage output for the TARGET database)
fills missing propnum/name/cums by API and refuses a qualifier that already
exists there. Wells whose PROPNUM stays unknown are still emitted — the
README tells the engineer to fill PROPNUM by joining on API first.

Usage:
  python3 aries_package.py curves.json [--aries-dir _aries] [--out aries_import_package.zip]
"""

import argparse
import csv
import io
import json
import math
import re
import sys
import zipfile
from pathlib import Path

# Engine tail policy, expressed in ARIES terms (pinned in tests against
# server config): terminal switch at ECON.terminal_di_annual NOMINAL annual.
ENGINE_TERMINAL_DI_ANNUAL_NOMINAL = 0.05
DEFAULT_FLOORS = {"oil": 30.0, "gas": 100.0}   # B/M, M/M — visible, editable
PHASES = (("oil", "OIL", "B/M"), ("gas", "GAS", "M/M"))
ECON_COLUMNS = ["PROPNUM", "SECTION", "SEQUENCE", "QUALIFIER", "KEYWORD", "EXPRESSION"]


def eff_annual_from_nominal_monthly(a: float, b: float) -> float:
    """Nominal monthly decline -> ARIES quoted effective annual (secant)."""
    if b < 1e-9:
        return 1.0 - math.exp(-12.0 * a)
    return 1.0 - (1.0 + 12.0 * b * a) ** (-1.0 / b)


def month_to_aries(anchor: str) -> str:
    m = re.match(r"^(\d{4})-(\d{2})$", anchor or "")
    if not m:
        raise ValueError(f"anchor_month must be YYYY-MM; got {anchor!r}")
    return f"{int(m.group(2)):02d}/{m.group(1)}"


def phase_lines(params: dict, unit: str, floor: float) -> tuple[str, str]:
    """Main hyperbolic line + terminal ditto in the proven shape."""
    qi, a, b = float(params["qi"]), float(params["di"]), float(params["b"])
    if not (qi > 0 and 0 < a < 1 and 0 <= b <= 2):
        raise ValueError(f"parameters out of range: {params}")
    D = eff_annual_from_nominal_monthly(a, b)
    D_term = eff_annual_from_nominal_monthly(ENGINE_TERMINAL_DI_ANNUAL_NOMINAL / 12.0, 0.0)
    main = f"{qi:.3f} X {unit} {D_term*100:.6f} EXP B/{b:.4f} {D*100:.6f}"
    ditto = f"X {floor:.5f} {unit} X YRS EXP {D_term*100:.6f}"
    return main, ditto


def load_aries_context(aries_dir: Path):
    props, quals = {}, set()
    prop_csv = aries_dir / "tables" / "AC_PROPERTY.csv"
    if prop_csv.is_file():
        for r in csv.DictReader(open(prop_csv, newline="", encoding="utf-8")):
            row = {k.strip().upper(): (v or "").strip() for k, v in r.items() if k}
            raw = row.get("API_10") or row.get("API") or ""
            digits = re.sub(r"\D", "", raw)[:10]
            if len(digits) == 10:
                api = f"{digits[:2]}-{digits[2:5]}-{digits[5:]}"
                name = (row.get("CASE_NAME")
                        or " ".join(x for x in (row.get("LEASE"), row.get("WELLNUM")) if x))
                props[api] = {"propnum": row.get("PROPNUM"), "name": name}
    econ_csv = aries_dir / "tables" / "AC_ECONOMIC.csv"
    if econ_csv.is_file():
        for r in csv.DictReader(open(econ_csv, newline="", encoding="utf-8")):
            q = (r.get("QUALIFIER") or "").strip()
            if q:
                quals.add(q)
    return props, quals


def build(spec: dict, aries_props: dict, existing_qualifiers: set):
    qualifier = (spec.get("qualifier") or "").strip()
    if not re.match(r"^[A-Za-z0-9_]{1,10}$", qualifier):
        sys.exit("qualifier must be 1-10 alphanumeric/underscore characters")
    if qualifier.upper() in {q.upper() for q in existing_qualifiers}:
        sys.exit(f"qualifier {qualifier!r} already exists in the target database — "
                 f"pick a NEW one; this package must never overwrite existing lines")

    econ_rows, crosswalk, notes = [], [], []
    for w in spec.get("wells", []):
        api = w.get("api")
        if not api:
            sys.exit(f"well without api: {w}")
        ctx = aries_props.get(api, {})
        propnum = w.get("propnum") or ctx.get("propnum") or f"API:{api}"
        name = w.get("name") or ctx.get("name") or api
        if propnum.startswith("API:"):
            notes.append(f"{name} ({api}): PROPNUM unknown — fill it by joining "
                         f"on API in the target database before importing")
        crosswalk.append({"API": api, "PROPNUM": propnum, "WELL": name,
                          "PROPNUM_KNOWN": "no" if propnum.startswith("API:") else "yes"})

        seq = 10
        def add(section, keyword, expression):
            nonlocal seq
            econ_rows.append({"PROPNUM": propnum, "SECTION": section, "SEQUENCE": seq,
                              "QUALIFIER": qualifier, "KEYWORD": keyword,
                              "EXPRESSION": expression})
            seq += 2

        cums = w.get("cums") or {}
        if cums.get("oil_bbl") is not None or cums.get("gas_mcf") is not None:
            add(4, "CUMS", f"{(cums.get('oil_bbl') or 0)/1000:.3f} "
                           f"{(cums.get('gas_mcf') or 0)/1000:.3f} 0.0 0.0 0.0 0.0")
        start = month_to_aries(w["anchor_month"])
        wrote_stream = False
        for key, keyword, unit in PHASES:
            params = w.get(key)
            if not params:
                continue
            main, ditto = phase_lines(params, unit, float(
                (w.get("floors") or {}).get(key, DEFAULT_FLOORS[key])))
            add(4, "START", start)
            add(4, keyword, main)
            add(4, '"', ditto)
            wrote_stream = True
        if not wrote_stream:
            sys.exit(f"{name} ({api}): no oil or gas parameters — nothing to export")
    return qualifier, econ_rows, crosswalk, notes


def render_readme(qualifier, econ_rows, crosswalk, notes):
    unknown = [c for c in crosswalk if c["PROPNUM_KNOWN"] == "no"]
    lines = [
        "# ARIES import package — Crude Code forecasts",
        "",
        f"Forecast lines for {len(crosswalk)} wells under NEW qualifier "
        f"`{qualifier}` ({len(econ_rows)} AC_ECONOMIC rows). Nothing in this "
        "package modifies existing data: the qualifier is new, so your current "
        "scenarios are untouched until you point one at it.",
        "",
        "Declines are quoted as ARIES effective-annual; qi values are "
        "units/month at the START month. The terminal segment reflects the "
        "Crude Code engine's tail policy "
        f"({ENGINE_TERMINAL_DI_ANNUAL_NOMINAL:.0%} nominal annual); rate "
        f"floors default to {DEFAULT_FLOORS['oil']:g} B/M oil / "
        f"{DEFAULT_FLOORS['gas']:g} M/M gas — edit them to your convention.",
        "",
        "## Import steps (work on a COPY of your database)",
        "",
        "1. Copy your `.accdb`; open the copy in Microsoft Access.",
        "2. External Data -> Text File -> `AC_ECONOMIC.csv` -> **Append** to "
        "`AC_ECONOMIC` (first row is column names; columns map by name: "
        + ", ".join(ECON_COLUMNS) + ").",
        "3. Verify the appended row count matches this package "
        f"({len(econ_rows)} rows).",
        "4. In ARIES, add a scenario (or edit one) whose section-4 qualifier "
        f"list starts with `{qualifier}` — that scenario now runs these "
        "forecasts; your originals remain under their own qualifiers.",
    ]
    if unknown:
        lines += [
            "",
            "## Before importing — fill unknown PROPNUMs",
            "",
            f"{len(unknown)} well(s) could not be matched to your database's "
            "PROPNUM and carry a placeholder (`API:<api>`). Use "
            "`crosswalk.csv` to join on API against your `AC_PROPERTY` "
            "(API/API_10 column) and replace the placeholders in "
            "`AC_ECONOMIC.csv` first — rows with a placeholder PROPNUM will "
            "not attach to a property.",
        ]
    if notes:
        lines += ["", "## Notes", ""] + [f"- {n}" for n in notes]
    lines += ["", "Generated by Crude Code `aries-writeback`. Informational — "
                  "review every line before relying on it."]
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("curves", help="curves.json (schema in the module docstring)")
    ap.add_argument("--aries-dir", help="the target database's _aries triage dir "
                                        "(fills propnum/name by API; guards the qualifier)")
    ap.add_argument("--out", default="aries_import_package.zip")
    args = ap.parse_args()

    spec = json.load(open(args.curves))
    aries_props, existing_quals = ({}, set())
    if args.aries_dir:
        aries_props, existing_quals = load_aries_context(Path(args.aries_dir))
    qualifier, econ_rows, crosswalk, notes = build(spec, aries_props, existing_quals)

    def to_csv(rows, columns):
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=columns)
        w.writeheader()
        w.writerows(rows)
        return buf.getvalue()

    with zipfile.ZipFile(args.out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("AC_ECONOMIC.csv", to_csv(econ_rows, ECON_COLUMNS))
        z.writestr("crosswalk.csv", to_csv(crosswalk, ["API", "PROPNUM", "WELL",
                                                       "PROPNUM_KNOWN"]))
        z.writestr("README.md", render_readme(qualifier, econ_rows, crosswalk, notes))

    print(f"package -> {args.out}")
    print(f"  qualifier {qualifier} · {len(crosswalk)} wells · "
          f"{len(econ_rows)} AC_ECONOMIC rows")
    for n in notes:
        print(f"  NOTE: {n}")


if __name__ == "__main__":
    main()
