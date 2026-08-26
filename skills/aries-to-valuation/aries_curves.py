"""Translate ARIES section-4 forecasts into forecast_wells assertions.

Reads the `_aries/` directory written by the aries-explorer skill's
aries_triage.py and emits, for the chosen scenario qualifier:

  - a proposed `forecast_wells` payload (entries with qi / di / b per stream,
    anchor_month, and a rationale carrying the verbatim ARIES lines), and
  - a coverage report — every well, stream, and construct that did or did not
    translate, plus the deck's NGL / shrink / water burden the Crude Code
    engine does not model. Nothing is dropped silently.

Conventions (empirically pinned — see ARIES.md "Decline conventions"):
  - A quoted decline D is the EFFECTIVE ANNUAL (secant) decline; the engine
    wants nominal MONTHLY: a = ((1-D)^(-b) - 1)/(12b), or -ln(1-D)/12 at b=0.
  - Rates are units/month (B/M, M/M) — the engine's qi unit exactly.
  - A limit "N EXP" ends the hyperbolic where effective annual decline
    shallows to N%; the ditto line is the exponential tail to a rate floor.
    The engine applies its OWN terminal policy instead (config
    terminal_di_annual, nominal), so the report quantifies the tail delta.

Only the proven line shape translates (hyperbolic main + terminal ditto);
anything else — LOOKUP type curves, LIST/LOAD, extra segments — is refused
per stream with the verbatim lines in the report. Never guessed.

Usage:
  python3 aries_curves.py _aries [--qualifier Q] [--payload forecast_payload.json]
  python3 aries_curves.py _aries --tieout oneliner.json
      oneliner.json: {"<api or propnum>": {"ult_oil": bbl, "ult_gas": mcf,
                                           "life_yrs": years-from-effective}}
      (extract it yourself from the room's oneliner; the script only does math)
"""

import argparse
import csv
import json
import math
import re
import sys
from collections import defaultdict
from pathlib import Path

ENGINE_TERMINAL_DI_ANNUAL_NOMINAL = 0.05   # config.ECON.terminal_di_annual
ENGINE_HORIZON_MONTHS = 360                # config.ECON.horizon_months

PHASE_UNITS = {"OIL": "B/M", "GAS": "M/M", "WTR": "B/M"}
ENGINE_STREAMS = ("OIL", "GAS")            # WTR translates for reporting only


def to_float(v):
    try:
        return float(str(v).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def to_month(v):
    s = str(v or "").strip()
    m = re.match(r"^(\d{1,2})/(\d{4})$", s)
    if m:
        return f"{int(m.group(2)):04d}-{int(m.group(1)):02d}"
    m = re.match(r"^(\d{4})-(\d{2})", s)
    if m:
        return f"{m.group(1)}-{m.group(2)}"
    return None


def read_csv(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return [{k.strip().upper(): (v or "").strip() for k, v in row.items() if k}
                for row in csv.DictReader(f)]


def first_of(row: dict, *keys):
    for k in keys:
        v = row.get(k)
        if v not in (None, ""):
            return v
    return None


def format_api10(raw: str) -> str | None:
    """14- or 10-digit ARIES API -> SS-CCC-WWWWW. Never fabricates digits."""
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) == 14:
        digits = digits[:10]
    if len(digits) != 10:
        return None
    return f"{digits[:2]}-{digits[2:5]}-{digits[5:]}"


# ── decline math (pinned conventions) ────────────────────────────────────────

def a_mo_from_eff(D: float, b: float) -> float:
    """Effective annual decline -> nominal monthly."""
    if b < 1e-9:
        return -math.log(1.0 - D) / 12.0
    return ((1.0 - D) ** (-b) - 1.0) / (12.0 * b)


def q_at(q0, a, b, t):
    if b < 1e-9:
        return q0 * math.exp(-a * t)
    return q0 * (1.0 + b * a * t) ** (-1.0 / b)


def cum(q0, a, b, t):
    """Continuous integral of the curve over [0, t] months."""
    if t <= 0:
        return 0.0
    if b < 1e-9:
        return (q0 / a) * (1.0 - math.exp(-a * t))
    if abs(b - 1.0) < 1e-9:
        return (q0 / a) * math.log(1.0 + a * t)
    return q0 / (a * (1.0 - b)) * (1.0 - (1.0 + b * a * t) ** (1.0 - 1.0 / b))


def eur_with_terminal(qi, a0, b, a_term, *, floor=None, t_cap=None):
    """Forecast volume: hyperbolic until the local nominal decline shallows
    to a_term, then exponential at a_term to the rate floor and/or time cap."""
    t_sw = max(0.0, (a0 / a_term - 1.0) / (b * a0)) if b > 1e-9 and a0 > a_term else 0.0
    if t_cap is not None and t_sw >= t_cap:
        return cum(qi, a0, b, t_cap)
    q_sw = q_at(qi, a0, b, t_sw)
    t2 = math.inf
    if floor is not None and q_sw > floor:
        t2 = math.log(q_sw / floor) / a_term
    elif floor is not None:
        t2 = 0.0
    if t_cap is not None:
        t2 = min(t2, t_cap - t_sw)
    if not math.isfinite(t2):
        raise ValueError("unbounded tail: need a floor or a time cap")
    return cum(qi, a0, b, t_sw) + cum(q_sw, a_term, 0.0, t2)


# ── section-4 parsing (strict: proven shapes only) ───────────────────────────

MAIN_RE = re.compile(
    r"^(?P<qi>[\d.]+)\s+X\s+(?P<unit>[BM]/M)\s+(?P<limit>[\d.]+)\s+EXP\s+"
    r"B/(?P<b>[\d.]+)\s+(?P<D>[\d.]+)$")
DITTO_RE = re.compile(
    r"^X\s+(?P<floor>[\d.]+)\s+(?P<unit>[BM]/M)\s+X\s+YRS\s+EXP\s+(?P<D2>[\d.]+)$")


def parse_phase(main: str, dittos: list[str]):
    """Return (curve dict, None) or (None, refusal reason)."""
    m = MAIN_RE.match(" ".join(main.split()))
    if not m:
        return None, f"unrecognized main-line shape: `{main}`"
    if len(dittos) != 1:
        return None, (f"{len(dittos)} continuation lines (only main + one "
                      f"terminal ditto translates): " +
                      "; ".join(f"`{d}`" for d in dittos or ["<none>"]))
    d = DITTO_RE.match(" ".join(dittos[0].split()))
    if not d:
        return None, f"unrecognized continuation shape: `{dittos[0]}`"
    D = float(m.group("D")) / 100.0
    limit_D = float(m.group("limit")) / 100.0
    D2 = float(d.group("D2")) / 100.0
    if abs(D2 - limit_D) > 1e-9:
        return None, (f"terminal ditto D {D2*100:g}% differs from the main "
                      f"line's limit {limit_D*100:g}% — not the proven shape")
    if not (0.0 < D < 1.0):
        return None, f"effective annual decline {D*100:g}% outside (0, 100)"
    b = float(m.group("b"))
    return {
        "qi": float(m.group("qi")),
        "b": b,
        "eff_annual_decline": D,
        "di_nominal_monthly": a_mo_from_eff(D, b),
        "aries_terminal_eff_annual": limit_D,
        "aries_floor": float(d.group("floor")),
        "unit": m.group("unit"),
        "lines": [main, dittos[0]],
    }, None


def build(aries_dir: Path, qualifier_arg: str | None):
    econ = read_csv(aries_dir / "tables" / "AC_ECONOMIC.csv")
    props = {(r.get("PROPNUM") or "").strip(): r
             for r in read_csv(aries_dir / "tables" / "AC_PROPERTY.csv")}
    manifest = json.loads((aries_dir / "manifest.json").read_text())

    qualifiers = sorted({(r.get("QUALIFIER") or "").strip() or "(blank)" for r in econ})
    if qualifier_arg:
        chosen = qualifier_arg
        if chosen not in qualifiers:
            sys.exit(f"qualifier {chosen!r} not present; found: {qualifiers}")
    else:
        counts = defaultdict(set)
        for r in econ:
            counts[(r.get("QUALIFIER") or "").strip() or "(blank)"].add(r.get("PROPNUM"))
        chosen = "BASE" if "BASE" in counts else max(counts, key=lambda q: len(counts[q]))

    rows = sorted((r for r in econ
                   if ((r.get("QUALIFIER") or "").strip() or "(blank)") == chosen),
                  key=lambda r: (r.get("PROPNUM"), int(r.get("SEQUENCE") or 0)))

    wells: dict[str, dict] = {}
    for r in rows:
        pn = (r.get("PROPNUM") or "").strip()
        w = wells.setdefault(pn, {"propnum": pn, "phases": {}, "anchor": None,
                                  "cums": None, "shrink": None, "ngl_yield": None,
                                  "wtr_opex": None, "_open": None})
        kw = (r.get("KEYWORD") or "").strip().upper()
        expr = " ".join((r.get("EXPRESSION") or "").split())
        section = int(r.get("SECTION") or 0)
        if section == 4:
            if kw == "START":
                w["anchor"] = to_month(expr.split()[0]) if expr else None
            elif kw == "CUMS":
                v = [to_float(x) for x in expr.split()]
                w["cums"] = {"oil_bbl": (v[0] or 0) * 1000, "gas_mcf": (v[1] or 0) * 1000}
            elif kw in ("OIL", "GAS", "WTR"):
                w["phases"][kw] = {"main": expr, "dittos": [], "anchor": w["anchor"]}
                w["_open"] = kw
            elif kw == "NGL/GAS":
                w["ngl_yield"] = to_float(expr.split()[0]) if expr else None
            elif kw == '"' and w["_open"]:
                w["phases"][w["_open"]]["dittos"].append(expr)
            else:
                w["_open"] = None
        elif section == 2 and kw == "SHRINK":
            w["shrink"] = to_float(expr.split()[0]) if expr else None
        elif section == 6 and kw == "OPC/WTR":
            w["wtr_opex"] = to_float(expr.split()[0]) if expr else None

    a_term_engine = ENGINE_TERMINAL_DI_ANNUAL_NOMINAL / 12.0
    entries, report_wells, refusals = [], [], []
    for pn, w in sorted(wells.items()):
        prop = props.get(pn, {})
        name = (first_of(prop, "CASE_NAME")
                or " ".join(x for x in (first_of(prop, "LEASE"),
                                        first_of(prop, "WELLNUM")) if x) or pn)
        api = format_api10(first_of(prop, "API_10", "API") or "")
        rw = {"propnum": pn, "name": name, "api": api,
              "anchor": None, "streams": {}, "shrink": w["shrink"],
              "ngl_yield_bbl_per_mcf": w["ngl_yield"], "wtr_opex_per_bbl": w["wtr_opex"],
              "cums": w["cums"]}
        curves, verbatim, anchors = {}, [], set()
        for phase in ("OIL", "GAS", "WTR"):
            ph = w["phases"].get(phase)
            if not ph:
                continue
            curve, why = parse_phase(ph["main"], ph["dittos"])
            if why:
                refusals.append({"well": name, "api": api, "stream": phase,
                                 "reason": why})
                rw["streams"][phase] = {"translated": False, "reason": why}
                continue
            if curve["unit"] != PHASE_UNITS[phase]:
                refusals.append({"well": name, "api": api, "stream": phase,
                                 "reason": f"unexpected unit {curve['unit']}"})
                rw["streams"][phase] = {"translated": False,
                                        "reason": f"unexpected unit {curve['unit']}"}
                continue
            a0 = curve["di_nominal_monthly"]
            a_term_aries = a_mo_from_eff(curve["aries_terminal_eff_annual"], 0.0)
            eur_aries = eur_with_terminal(curve["qi"], a0, curve["b"], a_term_aries,
                                          floor=curve["aries_floor"])
            eur_engine = eur_with_terminal(curve["qi"], a0, curve["b"], a_term_engine,
                                           t_cap=ENGINE_HORIZON_MONTHS)
            rw["streams"][phase] = {
                "translated": True, "qi_per_month": curve["qi"], "b": curve["b"],
                "di_nominal_monthly": round(a0, 8),
                "aries_terminal_eff_annual": curve["aries_terminal_eff_annual"],
                "aries_floor": curve["aries_floor"],
                "eff_annual_decline_pct": round(curve["eff_annual_decline"] * 100, 4),
                "fcst_aries_terminal": round(eur_aries),
                "fcst_engine_terminal_360mo": round(eur_engine),
                "tail_delta_pct": round((eur_engine / eur_aries - 1) * 100, 2),
            }
            anchors.add(ph["anchor"])
            if phase in ENGINE_STREAMS:
                curves[phase.lower()] = {"qi": round(curve["qi"], 3),
                                         "di": round(a0, 6), "b": curve["b"]}
                verbatim.append(f"{phase} {curve['lines'][0]} / \" {curve['lines'][1]}")
        rw["anchor"] = sorted(a for a in anchors if a)[0] if anchors - {None} else None
        report_wells.append(rw)

        if not curves or not api or not rw["anchor"]:
            if not api:
                refusals.append({"well": name, "api": None, "stream": "*",
                                 "reason": "no API in AC_PROPERTY — cannot enter a run"})
            continue
        entries.append({
            "wells": [api],
            "oil": curves.get("oil"),
            "gas": curves.get("gas"),
            "anchor_month": rw["anchor"],
            "rationale": (
                f"Seller's ARIES curve adopted verbatim at the user's request "
                f"(qualifier {chosen}, db {manifest['database']['sha256'][:12]}, "
                f"{name}): " + " | ".join(verbatim) +
                ". Declines converted effective-annual -> nominal-monthly per the "
                "pinned ARIES conventions; the engine applies its own terminal "
                "and horizon. Not an independent forecast."),
        })

    return {
        "source": "aries", "qualifier": chosen, "qualifiers_present": qualifiers,
        "database": manifest["database"], "entries": entries,
        "report": {"wells": report_wells, "refusals": refusals,
                   "engine_terminal_di_annual_nominal": ENGINE_TERMINAL_DI_ANNUAL_NOMINAL,
                   "engine_horizon_months": ENGINE_HORIZON_MONTHS},
    }


# ── report / tie-out rendering ───────────────────────────────────────────────

def fmt_report(payload):
    r, out = payload["report"], []
    out.append(f"== TRANSLATION — qualifier {payload['qualifier']} "
               f"(present: {', '.join(payload['qualifiers_present'])}) ==")
    out.append(f"{len(payload['entries'])} of {len(r['wells'])} wells translated "
               f"into forecast_wells entries")
    out.append("")
    for w in r["wells"]:
        line = f"  {w['name']}  api={w['api'] or 'NONE'}  anchor={w['anchor']}"
        out.append(line)
        for ph, s in w["streams"].items():
            if s.get("translated"):
                out.append(f"    {ph}: qi {s['qi_per_month']:,.0f}/mo  b {s['b']}"
                           f"  di {s['di_nominal_monthly']} nominal-monthly"
                           f" ({s['eff_annual_decline_pct']}% eff-annual)"
                           f"  fcst {s['fcst_aries_terminal']:,} (ARIES tail)"
                           f" vs {s['fcst_engine_terminal_360mo']:,} (engine tail,"
                           f" {s['tail_delta_pct']:+.1f}%)")
            else:
                out.append(f"    {ph}: NOT TRANSLATED — {s['reason']}")
        extras = []
        if w["shrink"] is not None and w["shrink"] < 1:
            extras.append(f"SHRINK {w['shrink']:g} (engine models wellhead gas; "
                          f"realization rides BTU/diffs)")
        if w["ngl_yield_bbl_per_mcf"]:
            extras.append(f"NGL yield {w['ngl_yield_bbl_per_mcf']:g} bbl/mcf — "
                          f"NOT modeled by the engine")
        if w["wtr_opex_per_bbl"]:
            extras.append(f"OPC/WTR ${w['wtr_opex_per_bbl']:g}/bbl water — "
                          f"NOT modeled; consider an opex override")
        for e in extras:
            out.append(f"    note: {e}")
    if r["refusals"]:
        out.append("")
        out.append("== NOT TRANSLATED (verbatim reasons — relay these, never guess) ==")
        for x in r["refusals"]:
            out.append(f"  {x['well']} [{x['stream']}]: {x['reason']}")
    out.append("")
    out.append(f"== TAIL POLICY == ARIES ends each curve at its own econ limit; the "
               f"engine runs {r['engine_horizon_months']} months with a "
               f"{r['engine_terminal_di_annual_nominal']:.0%} nominal-annual terminal. "
               f"The per-stream 'fcst' pair above quantifies that difference — "
               f"surface it with the assumptions grid.")
    return "\n".join(out)


def fmt_tieout(payload, oneliner):
    out, errs = [], []
    out.append("== ONELINER TIE-OUT (curve math check: forecast + CUMS vs the "
               "seller's ULTIMATE, truncated at their stated life) ==")
    for w in payload["report"]["wells"]:
        k = oneliner.get(w["api"] or "") or oneliner.get(w["propnum"]) or {}
        if not k or not w["cums"]:
            continue
        for ph, ult_key, cum_key in (("OIL", "ult_oil", "oil_bbl"),
                                     ("GAS", "ult_gas", "gas_mcf")):
            s = w["streams"].get(ph)
            ult = k.get(ult_key)
            if not (s and s.get("translated") and ult):
                continue
            a0 = s["di_nominal_monthly"]
            a_term = a_mo_from_eff(s["aries_terminal_eff_annual"], 0.0)
            t_cap = k.get("life_yrs")
            t_cap = (k.get("eff_offset_months", 0) + t_cap * 12) if t_cap else None
            fcst = eur_with_terminal(s["qi_per_month"], a0, s["b"], a_term,
                                     floor=s["aries_floor"], t_cap=t_cap)
            err = (w["cums"][cum_key] + fcst) / ult - 1
            errs.append(abs(err))
            out.append(f"  {w['name']} {ph}: {w['cums'][cum_key] + fcst:,.0f} "
                       f"vs oneliner {ult:,.0f}  ({err*100:+.3f}%)")
    if errs:
        out.append(f"  -> mean |err| {sum(errs)/len(errs)*100:.3f}%  "
                   f"worst {max(errs)*100:.3f}%  (n={len(errs)})")
        out.append("  Residuals beyond ~0.1% mean the translation is wrong — stop "
                   "and investigate before valuing. Without life_yrs, expect "
                   "overshoot equal to the seller's econ-limit truncation.")
    else:
        out.append("  nothing comparable (need api/propnum keys with ult_oil/ult_gas)")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("aries_dir")
    ap.add_argument("--qualifier")
    ap.add_argument("--payload", default="forecast_payload.json",
                    help="where to write the proposed forecast_wells payload")
    ap.add_argument("--tieout", help="oneliner.json for the EUR tie-out")
    args = ap.parse_args()

    aries_dir = Path(args.aries_dir)
    if not (aries_dir / "tables" / "AC_ECONOMIC.csv").is_file():
        sys.exit(f"no AC_ECONOMIC dump in {aries_dir} — run aries_triage.py "
                 f"(aries-explorer skill) first")
    payload = build(aries_dir, args.qualifier)
    Path(args.payload).write_text(json.dumps(payload, indent=1))
    print(fmt_report(payload))
    print(f"\npayload -> {args.payload} ({len(payload['entries'])} entries)")
    if args.tieout:
        print()
        print(fmt_tieout(payload, json.load(open(args.tieout))))


if __name__ == "__main__":
    main()
