"""Deterministic rollups for the ARIES explorer viewer.

Input: the `_aries/` directory written by aries_triage.py. Every number on
the viewer comes from here — property rollups, qualifier counts, assumption
clusters, forecast-source mix, referential-integrity checks — so no rollup
is ever model arithmetic. Unknown keywords and expressions pass through
verbatim; nothing is invented to make a line decode.

Usage:
  python3 aries_payload.py _aries --facts
      Print the computed-facts digest (read this, then write notes.json).
  python3 aries_payload.py _aries [--qualifier BASE] [--notes notes.json] > payload.json
      Emit the viewer payload (paste into AriesViewer.jsx's DATA).
"""

import argparse
import csv
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

PROP_CAP = 400       # manifest rows shipped to the viewer; the rest are counted
CLUSTER_CAP = 80     # assumption clusters shipped
LOOKUP_CAP = 12      # lookup tables shipped
LOOKUP_ROW_CAP = 24  # data rows per lookup shipped

SECTION_NAMES = {
    1: "Miscellaneous", 2: "Input settings", 3: "(reserved)",
    4: "Production & forecasts", 5: "Prices", 6: "Expenses",
    7: "Ownership", 8: "Investments", 9: "Overlays",
}
KEYWORD_LABELS = {
    "PRI/OIL": "Oil price", "PRI/GAS": "Gas price",
    "PRI/CND": "Condensate price", "PRI/NGL": "NGL price",
    "PAJ/OIL": "Oil price differential", "PAJ/GAS": "Gas price differential",
    "PAJ/CND": "Condensate differential", "PAJ/NGL": "NGL differential",
    "OPC/T": "Fixed operating cost", "OPC/OIL": "Variable opex (oil)",
    "OPC/GAS": "Variable opex (gas)",
    "STX/OIL": "Severance tax (oil)", "STX/GAS": "Severance tax (gas)",
    "STX/CND": "Severance tax (condensate)", "ATX": "Ad valorem tax",
    "OH/T": "Overhead", "GA/T": "G&A",
    "NET": "Net revenue interest", "WI": "Working interest",
    "LSE/WI": "Lease working interest", "OWN/WI": "Owned working interest",
    "ROY/OIL": "Oil royalty", "ROY/GAS": "Gas royalty",
    "ORR/OIL": "Overriding royalty (oil)", "ORR/GAS": "Overriding royalty (gas)",
    "LSE/NPI": "Net profits interest",
    "OPC/WTR": "Variable opex (water)", "STX/NGL": "Severance tax (NGL)",
    "NGL/GAS": "NGL yield (per gas)", "CND/GAS": "Condensate yield (per gas)",
    "SIDEFILE": "Side file (external econ lines)", "LOOKUP": "Lookup",
    "SALV": "Salvage", "ABDN": "Abandonment",
    "SHRINK": "Gas shrinkage", "OPNET": "Operator net %",
    "ELOSS": "Economic limit", "BTU": "BTU factor", "LIFE": "Life",
    "MAJOR": "Major phase", "TAXP": "Tax plan", "RISK": "Risk factor",
    "BOOK": "Book economics", "START": "Forecast start",
    "CUMS": "Prior cumulatives", "CAPITAL": "Investment",
    "OIL": "Oil forecast", "GAS": "Gas forecast", "WTR": "Water forecast",
    "CND": "Condensate forecast", "NGL": "NGL forecast",
    '"': "″ continuation of previous line",
}
PHASE_KEYWORDS = {"OIL", "GAS", "WTR", "CND", "NGL", "OWG"}
RESCAT_ORDER = ["PDP", "PDNP", "PDSI", "PSI", "PBP", "PUD"]  # then others, alpha
ESCALATION_METHODS = {"PC", "PC/M", "PC/Q", "PC/S", "PC/Y", "PC/B",
                      "PE", "PE/Y", "$E", "$E/Q", "$E/Y"}
SIDEFILE_CAP = 8         # side files shipped to the viewer
SIDEFILE_LINE_CAP = 40   # lines per side file shipped


def to_int(v, default=None):
    try:
        return int(float(str(v).strip() or "x"))
    except (TypeError, ValueError):
        return default


def to_float(v):
    try:
        return float(str(v).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def to_month(v) -> str | None:
    """Lenient date -> 'YYYY-MM' for START expressions ('01/2025',
    'MM/DD/YYYY', 'YYYY-MM-…'). Unparseable -> None (never guess)."""
    s = str(v or "").strip()
    m = re.match(r"^(\d{4})-(\d{2})", s)
    if m:
        return f"{m.group(1)}-{m.group(2)}"
    m = re.match(r"^(\d{1,2})/(\d{4})$", s)
    if m:
        return f"{int(m.group(2)):04d}-{int(m.group(1)):02d}"
    m = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{2,4})", s)
    if m:
        mo, yr = int(m.group(1)), int(m.group(3))
        yr = yr + (2000 if yr < 50 else 1900) if yr < 100 else yr
        return f"{yr:04d}-{mo:02d}"
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


def rescat_sort_key(rescat: str):
    r = (rescat or "UNSPEC").upper()
    base = r.lstrip("0123456789")  # shops prefix categories ("1PDP", "3PUD")
    return ((RESCAT_ORDER.index(base), r) if base in RESCAT_ORDER
            else (len(RESCAT_ORDER), r))


# ── economics decode ─────────────────────────────────────────────────────────

def decode_net(expression: str):
    """Decode a section-7 NET shortcut line: word 0 is the WORKING interest,
    word 1 the NRI (per-phase NRIs may follow); a `%` unit token means every
    value is a percentage (÷100). Anything after the unit besides a plain
    escalation pair (e.g. `PC 0`) is an interest schedule — a reversion
    trigger or stepped interest — returned verbatim, never interpreted.
    Returns (wi, nri, schedule)."""
    words = expression.split()
    if not words:
        return None, None, None
    unit_idx = next((i for i, w in enumerate(words)
                     if w.upper() in ("%", "FRAC")), None)
    scale = 100.0 if unit_idx is not None and words[unit_idx] == "%" else 1.0
    nums = words[:unit_idx] if unit_idx is not None else words
    wi = to_float(nums[0]) if nums else None
    nri = to_float(nums[1]) if len(nums) > 1 else None
    wi = round(wi / scale, 10) if wi is not None else None
    nri = round(nri / scale, 10) if nri is not None else None
    tail = words[unit_idx + 1:] if unit_idx is not None else []
    benign = (not tail) or (len(tail) == 2 and tail[0].upper() in ESCALATION_METHODS)
    return wi, nri, (None if benign else " ".join(tail))


def forecast_source(econ_rows: list[dict], fcst_segments: int) -> str:
    """Name where this property's forecast comes from — never guesses:
    reports every distinct mechanism seen in section 4 plus AC_FCST."""
    sources = []
    if fcst_segments:
        sources.append(f"decline segments ({fcst_segments})")
    for r in econ_rows:
        if to_int(r.get("SECTION")) != 4:
            continue
        kw = (r.get("KEYWORD") or "").upper()
        expr = (r.get("EXPRESSION") or "").strip()
        words = expr.split()
        if kw == "LOOKUP" or (words and words[0].upper() == "LOOKUP"):
            name = words[1] if kw != "LOOKUP" and len(words) > 1 else (words[0] if kw == "LOOKUP" else "?")
            src = f"type curve {name}"
            if src not in sources:
                sources.append(src)
        elif kw in ("LOAD", "LOADXL") or (words and words[0].upper() in ("LOAD", "LOADXL")):
            if "history load" not in sources:
                sources.append("history load")
        elif kw in PHASE_KEYWORDS and words and to_float(words[0]) is not None:
            if "rate lines" not in sources:
                sources.append("rate lines")
    if fcst_segments and "rate lines" in sources:
        # AC_FCST is ARIES's store of the same forecast the section-4 rate
        # lines express — one forecast, two storages; don't double-report.
        sources.remove("rate lines")
        sources[0] = f"decline segments ({fcst_segments}; also as econ rate lines)"
    return " + ".join(sources) if sources else "none"


def build(aries_dir: Path, qualifier_arg: str | None, notes: dict | None):
    manifest = json.loads((aries_dir / "manifest.json").read_text())
    tables_dir = aries_dir / "tables"
    props_rows = read_csv(tables_dir / "AC_PROPERTY.csv")
    econ_rows = read_csv(tables_dir / "AC_ECONOMIC.csv")
    lookup_rows = read_csv(tables_dir / "ARLOOKUP.csv")
    sidefile_rows = read_csv(tables_dir / "AR_SIDEFILE.csv")
    fcst_rows = read_csv(tables_dir / "AC_FCST.csv")
    proj_rows = read_csv(tables_dir / "PROJLIST.csv") or read_csv(tables_dir / "PROJECT.csv")
    cov_path = aries_dir / "production_coverage.json"
    coverage = json.loads(cov_path.read_text()) if cov_path.is_file() else {"properties": {}, "table_rows": 0}

    warnings = list(manifest.get("warnings", []))

    # ── properties ───────────────────────────────────────────────────────────
    props: dict[str, dict] = {}
    dup_propnums = []
    for r in props_rows:
        propnum = (r.get("PROPNUM") or "").strip()
        if not propnum:
            continue
        if propnum in props:
            dup_propnums.append(propnum)
            continue
        # Master-table columns are shop-configurable in ARIES — cover the
        # variants seen in the wild (RSV_CAT vs RESCAT, LATERAL_LENGTH vs
        # LATERAL, LEASE+WELLNUM vs CASE_NAME, bare 14-digit API).
        name = first_of(r, "CASE_NAME")
        if not name:
            lease, wellnum = first_of(r, "LEASE"), first_of(r, "WELLNUM")
            name = " ".join(x for x in (lease, wellnum) if x) or first_of(r, "WELL_ID")
        props[propnum] = {
            "propnum": propnum,
            "name": name or propnum,
            "rescat": (first_of(r, "RESCAT", "RSV_CAT") or "UNSPEC").upper(),
            "major": first_of(r, "MAJOR"),
            "state": first_of(r, "STATE"),
            "county": first_of(r, "COUNTY"),
            "operator": first_of(r, "OPERATOR"),
            "api": first_of(r, "API_10", "API"),
            "lateral_ft": to_int(first_of(r, "LATERAL", "LATERAL_LENGTH")),
            "wi": to_float(first_of(r, "WI")),
            "nri": to_float(first_of(r, "NRI")),
        }

    # ── qualifiers and the chosen scenario ───────────────────────────────────
    by_qualifier: dict[str, list[dict]] = defaultdict(list)
    for r in econ_rows:
        by_qualifier[(r.get("QUALIFIER") or "").strip() or "(blank)"].append(r)
    qualifiers = sorted(
        ({"name": q, "lines": len(rows),
          "properties": len({r.get("PROPNUM") for r in rows})}
         for q, rows in by_qualifier.items()),
        key=lambda x: (-x["properties"], x["name"]))
    if qualifier_arg:
        chosen = qualifier_arg
        if chosen not in by_qualifier:
            sys.exit(f"qualifier {chosen!r} not in this database; "
                     f"present: {sorted(by_qualifier)}")
    elif "BASE" in by_qualifier:
        chosen = "BASE"
    else:
        chosen = qualifiers[0]["name"] if qualifiers else None
    chosen_rows = by_qualifier.get(chosen, [])

    econ_by_prop: dict[str, list[dict]] = defaultdict(list)
    for r in chosen_rows:
        econ_by_prop[(r.get("PROPNUM") or "").strip()].append(r)
    for rows in econ_by_prop.values():
        rows.sort(key=lambda r: (to_int(r.get("SECTION"), 0) or 0,
                                 to_int(r.get("SEQUENCE"), 0) or 0))

    # AC_FCST rows can be stale fits from old scenario vintages (verified in
    # the wild: 2022 qualifiers in a 2026 database whose live forecast is
    # section-4 rate lines only) — count only segments in the chosen qualifier.
    fcst_by_prop = Counter(
        (r.get("PROPNUM") or "").strip() for r in fcst_rows
        if ((r.get("QUALIFIER") or "").strip() or "(blank)") == chosen)

    # ── assumption clusters: distinct (section, keyword, expression) ─────────
    clusters: dict[tuple, set] = defaultdict(set)
    unlabeled = Counter()
    for r in chosen_rows:
        section = to_int(r.get("SECTION"), 0) or 0
        kw = (r.get("KEYWORD") or "").strip()
        expr = " ".join((r.get("EXPRESSION") or "").split())
        # Per-well forecast bodies are not shared assumptions: skip ditto
        # continuations and section-4 phase rate lines (segment tails would
        # otherwise flood the clusters one well at a time). Yield lines
        # (NGL/GAS), START, and LOOKUP stay — those cluster meaningfully.
        if kw == '"' or (section == 4 and kw.upper() in PHASE_KEYWORDS):
            continue
        clusters[(section, kw, expr)].add((r.get("PROPNUM") or "").strip())
        if kw.upper() not in KEYWORD_LABELS:
            unlabeled[kw] += 1
    cluster_list = sorted(
        ({"section": s, "section_name": SECTION_NAMES.get(s, f"Section {s}"),
          "keyword": kw, "label": KEYWORD_LABELS.get(kw.upper()),
          "expression": expr, "properties": len(members)}
         for (s, kw, expr), members in clusters.items()),
        key=lambda c: (c["section"], -c["properties"], c["keyword"], c["expression"]))
    clusters_total = len(cluster_list)
    cluster_list = cluster_list[:CLUSTER_CAP]

    # ── per-property rollup rows ─────────────────────────────────────────────
    cov_props = coverage.get("properties", {})
    for propnum, p in props.items():
        cv = cov_props.get(propnum)
        p["prod_months"] = cv["months"] if cv else 0
        p["last_prod"] = cv["last"] if cv else None
        p["cum_oil"] = cv["cum_oil"] if cv else None
        p["cum_gas"] = cv["cum_gas"] if cv else None
        p["econ_lines"] = len(econ_by_prop.get(propnum, []))
        p["forecast"] = forecast_source(econ_by_prop.get(propnum, []),
                                        fcst_by_prop.get(propnum, 0))
        # The section-7 NET line is what an economics run actually uses;
        # master WI/NRI columns are metadata unless referenced via @M.
        # Carry both so the viewer can show a disagreement.
        for r in econ_by_prop.get(propnum, []):
            if (r.get("KEYWORD") or "").upper() == "NET":
                wi_e, nri_e, schedule = decode_net(r.get("EXPRESSION") or "")
                if wi_e is not None:
                    p["wi_econ"] = wi_e
                if nri_e is not None:
                    p["nri_econ"] = nri_e
                if schedule:
                    p["interest_schedule"] = schedule
                break

    prop_list = sorted(props.values(),
                       key=lambda p: (rescat_sort_key(p["rescat"]), p["name"]))
    prop_total = len(prop_list)
    prop_list = prop_list[:PROP_CAP]

    rescat_counter: dict[str, dict] = {}
    for p in props.values():
        c = rescat_counter.setdefault(p["rescat"], {"count": 0, "with_production": 0,
                                                    "with_forecast": 0})
        c["count"] += 1
        c["with_production"] += 1 if p["prod_months"] else 0
        c["with_forecast"] += 1 if p["forecast"] != "none" else 0
    rescat_rollup = [{"rescat": k, **v} for k, v in
                     sorted(rescat_counter.items(), key=lambda kv: rescat_sort_key(kv[0]))]

    # Mechanism-level mix: per-property detail like segment counts stays on
    # the property row; the mix would otherwise fragment into one bucket per
    # segment count.
    forecast_mix = [{"source": s, "count": n} for s, n in Counter(
        re.sub(r"\s*\([^)]*\)", "", p["forecast"]) for p in props.values()
    ).most_common()]

    # ── lookup tables (type curves, price decks, tax schedules) ──────────────
    by_lookup: dict[str, dict] = {}
    for r in lookup_rows:
        name = first_of(r, "NAME") or "?"
        lt = to_int(first_of(r, "LINETYPE"))
        seq = to_int(first_of(r, "SEQUENCE"), 0) or 0
        vars_ = [r.get(f"VAR{i}", "") for i in range(31)]
        while vars_ and not vars_[-1]:
            vars_.pop()
        lk = by_lookup.setdefault(name, {"name": name, "template": [],
                                         "headers": [], "rows": []})
        if lt == 0:
            lk["template"].append((seq, " ".join(v for v in vars_ if v)))
        elif lt == 1:
            lk["headers"].append((seq, vars_))
        elif lt == 3:
            lk["rows"].append((seq, vars_))
    lookups = []
    for lk in by_lookup.values():
        # SEQUENCE is the authoritative order. A lookup can carry several
        # LineType=1 rows — the first is the column header, later ones are
        # ARIES format rows (match-key/constant type codes); keep them apart
        # so the type codes never masquerade as column names.
        headers = [h for _, h in sorted(lk.pop("headers"), key=lambda x: x[0])]
        rows = [v for _, v in sorted(lk["rows"], key=lambda x: x[0])]
        lookups.append({
            "name": lk["name"],
            "template": [t for _, t in sorted(lk["template"], key=lambda x: x[0])],
            "header": headers[0] if headers else [],
            "header_extra": headers[1:],
            "rows": rows[:LOOKUP_ROW_CAP],
            "rows_total": len(rows),
        })
    lookups_total = len(lookups)
    lookups = lookups[:LOOKUP_CAP]

    # ── side files: external econ lines (prices usually live here) ───────────
    # A SIDEFILE keyword in the economics points at a named block of lines in
    # AR_SIDEFILE — same KEYWORD/EXPRESSION grammar, often the whole price
    # deck. Decode them; the filename alone hides the most load-bearing
    # assumption in the database.
    sidefile_refs: dict[str, set] = defaultdict(set)
    for r in chosen_rows:
        if (r.get("KEYWORD") or "").upper() == "SIDEFILE":
            words = (r.get("EXPRESSION") or "").split()
            if words:
                sidefile_refs[words[0].upper()].add((r.get("PROPNUM") or "").strip())
    by_sidefile: dict[str, list] = defaultdict(list)
    for r in sidefile_rows:
        by_sidefile[(first_of(r, "FILENAME") or "?").strip()].append(r)
    side_files = []
    for fname, rows in by_sidefile.items():
        rows.sort(key=lambda r: (to_int(r.get("SECTION"), 0) or 0,
                                 to_int(r.get("SEQUENCE"), 0) or 0))
        side_files.append({
            "name": fname,
            "referenced_by": len(sidefile_refs.get(fname.upper(), ())),
            "lines_total": len(rows),
            "lines": [{
                "section": to_int(r.get("SECTION"), 0) or 0,
                "keyword": (r.get("KEYWORD") or "").strip(),
                "label": KEYWORD_LABELS.get((r.get("KEYWORD") or "").strip().upper()),
                "expression": " ".join((r.get("EXPRESSION") or "").split()),
            } for r in rows[:SIDEFILE_LINE_CAP]],
        })
    side_files.sort(key=lambda s: (-s["referenced_by"], s["name"]))
    side_files_total = len(side_files)
    side_files = side_files[:SIDEFILE_CAP]

    # ── referential integrity — the tie-out analog for a database ───────────
    def check(label, bad: list, detail_ok: str):
        sample = ", ".join(sorted(set(bad))[:5])
        return {"label": label, "ok": not bad,
                "detail": detail_ok if not bad else
                f"{len(bad)} issue{'s' if len(bad) != 1 else ''}: {sample}"
                + (" …" if len(set(bad)) > 5 else "")}

    econ_orphans = [pn for pn in econ_by_prop if pn and pn not in props]
    no_econ = [p["name"] for p in props.values() if not p["econ_lines"]]
    no_fcst = [p["name"] for p in props.values() if p["forecast"] == "none"]
    cov_orphans = [pn for pn in cov_props if pn not in props]
    integrity = [
        check("Economics rows all reference a known property", econ_orphans,
              f"every {chosen or ''} PROPNUM resolves to AC_PROPERTY"),
        check(f"Every property has economics lines ({chosen})", no_econ,
              "all properties carry economics"),
        check("Every property has a forecast source", no_fcst,
              "all properties have a forecast"),
        check("PROPNUMs are unique in AC_PROPERTY", dup_propnums,
              "no duplicates"),
        check("Production history all maps to known properties", cov_orphans,
              "every producing PROPNUM resolves"),
    ]

    # Master WI/NRI vs the section-7 NET line — the NET line is what an
    # economics run uses; a disagreement means the database argues with
    # itself about the multiplier on every dollar. Only rendered when both
    # sides exist to compare (a trivially-green check teaches nothing).
    comparable, interest_mismatch = 0, []
    for p in props.values():
        pairs = [(p.get("wi"), p.get("wi_econ")), (p.get("nri"), p.get("nri_econ"))]
        pairs = [(m, e) for m, e in pairs if m is not None and e is not None]
        if pairs:
            comparable += 1
            if any(abs(m - e) > 1e-6 for m, e in pairs):
                interest_mismatch.append(p["name"])
    if comparable:
        integrity.append(check(
            "Master WI/NRI agrees with the section-7 NET line", interest_mismatch,
            f"master and NET interests match on all {comparable} comparable"
            f" propert{'y' if comparable == 1 else 'ies'}"))

    # Forecast START vs the last reported production month — actuals that
    # postdate the forecast start mean the run is stale relative to history.
    starts_seen, stale_fcst = 0, []
    for propnum, p in props.items():
        if not p.get("last_prod"):
            continue
        for r in econ_by_prop.get(propnum, []):
            if (to_int(r.get("SECTION")) == 4
                    and (r.get("KEYWORD") or "").upper() == "START"):
                words = (r.get("EXPRESSION") or "").split()
                start = to_month(words[0]) if words else None
                if start:
                    starts_seen += 1
                    if p["last_prod"] > start:
                        stale_fcst.append(
                            f"{p['name']} (START {start}, actuals thru {p['last_prod']})")
                break
    if starts_seen:
        integrity.append(check(
            "No actuals postdate the forecast START", stale_fcst,
            f"history ends at or before the forecast start on all {starts_seen}"
            f" dated propert{'y' if starts_seen == 1 else 'ies'}"))

    cov_firsts = [c["first"] for c in cov_props.values() if c.get("first")]
    cov_lasts = [c["last"] for c in cov_props.values() if c.get("last")]

    db = manifest.get("database", {})
    payload = {
        "database": {
            "file": db.get("file"), "size_bytes": db.get("size_bytes"),
            "backend": manifest.get("backend"),
            "schema_version": manifest.get("schema_version"),
            "table_count": len(manifest.get("tables", [])),
            "property_count": prop_total,
            "projects": sorted({first_of(r, "NAME", "PROJECT", "PROJNAME") or ""
                                for r in proj_rows} - {""})[:8],
        },
        "scenarios": {"chosen": chosen, "qualifiers": qualifiers},
        "rescat_rollup": rescat_rollup,
        "forecast_mix": forecast_mix,
        "coverage": {
            "properties_with_production": sum(1 for c in cov_props.values() if c["months"]),
            "first": min(cov_firsts) if cov_firsts else None,
            "last": max(cov_lasts) if cov_lasts else None,
            "history_rows": coverage.get("table_rows", 0),
        },
        "properties": prop_list,
        "properties_truncated": ({"shown": PROP_CAP, "total": prop_total}
                                 if prop_total > PROP_CAP else None),
        "assumptions": cluster_list,
        "assumptions_truncated": ({"shown": CLUSTER_CAP, "total": clusters_total}
                                  if clusters_total > CLUSTER_CAP else None),
        "lookups": lookups,
        "lookups_truncated": ({"shown": LOOKUP_CAP, "total": lookups_total}
                              if lookups_total > LOOKUP_CAP else None),
        "side_files": side_files,
        "side_files_truncated": ({"shown": SIDEFILE_CAP, "total": side_files_total}
                                 if side_files_total > SIDEFILE_CAP else None),
        "integrity": integrity,
        "inventory": [{"name": t["name"], "rows": t.get("rows"), "role": t["role"]}
                      for t in manifest.get("tables", [])],
        "notes": (notes or {}).get("notes", []),
        "warnings": warnings,
        "unlabeled_keywords": [f"{kw} ×{n}" for kw, n in unlabeled.most_common(15)],
    }
    return payload


def facts_digest(payload):
    out = []
    db = payload["database"]
    out.append("== DATABASE ==")
    out.append(f"{db['file']}  {db['size_bytes']:,} bytes  backend {db['backend']}"
               f"  tables {db['table_count']}  properties {db['property_count']}"
               + (f"  schema {db['schema_version']}" if db.get("schema_version") else ""))
    if db.get("projects"):
        out.append("projects: " + ", ".join(db["projects"]))
    sc = payload["scenarios"]
    out.append(f"== QUALIFIERS (decoding {sc['chosen']!r}; re-run with --qualifier to switch) ==")
    for q in sc["qualifiers"]:
        out.append(f"  {q['name']}: {q['lines']} lines over {q['properties']} properties")
    out.append("== RESCAT ==")
    for r in payload["rescat_rollup"]:
        out.append(f"  {r['rescat']}: {r['count']} properties"
                   f"  ({r['with_production']} with production, {r['with_forecast']} with forecast)")
    out.append("== FORECAST SOURCES ==")
    for f in payload["forecast_mix"]:
        out.append(f"  {f['source']}: {f['count']}")
    cov = payload["coverage"]
    out.append(f"== PRODUCTION COVERAGE ==  {cov['properties_with_production']} properties,"
               f" {cov['first']} → {cov['last']}, {cov['history_rows']:,} AC_PRODUCT rows")
    out.append("== ASSUMPTION CLUSTERS (top 25 by property count) ==")
    for c in sorted(payload["assumptions"], key=lambda c: -c["properties"])[:25]:
        label = c["label"] or c["keyword"]
        out.append(f"  [s{c['section']} {c['keyword']}] {label}: {c['expression']}"
                   f"  ({c['properties']} props)")
    if payload["lookups"]:
        out.append("== LOOKUP TABLES ==")
        for lk in payload["lookups"]:
            out.append(f"  {lk['name']}: {lk['rows_total']} data rows,"
                       f" {len(lk['template'])} template lines,"
                       f" header {lk['header'] or '—'}")
    if payload["side_files"]:
        out.append("== SIDE FILES (external econ lines — prices usually live here) ==")
        for sf in payload["side_files"]:
            out.append(f"  {sf['name']} — referenced by {sf['referenced_by']}"
                       f" properties, {sf['lines_total']} lines")
            for ln in sf["lines"][:8]:
                out.append(f"    [s{ln['section']} {ln['keyword']}] {ln['expression']}")
            if sf["lines_total"] > 8:
                out.append(f"    … {sf['lines_total'] - 8} more (all in the payload)")
    schedules = [p for p in payload["properties"] if p.get("interest_schedule")]
    if schedules:
        out.append("== INTEREST SCHEDULES / REVERSIONS (NET-line tails, verbatim) ==")
        for p in schedules:
            out.append(f"  {p['name']}: {p['interest_schedule']}")
    out.append("== INTEGRITY ==")
    for c in payload["integrity"]:
        out.append(f"  [{'ok' if c['ok'] else 'LOOK'}] {c['label']} — {c['detail']}")
    if payload["unlabeled_keywords"]:
        out.append("== KEYWORDS WITHOUT A LABEL (decoded verbatim, fine — just know them) ==")
        out.append("  " + ", ".join(payload["unlabeled_keywords"]))
    if payload["warnings"]:
        out.append("== WARNINGS (from triage) ==")
        out.extend(f"  {w}" for w in payload["warnings"])
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("aries_dir", help="the _aries directory written by aries_triage.py")
    ap.add_argument("--qualifier", help="scenario qualifier to decode (default: BASE, "
                                        "else the most widely used)")
    ap.add_argument("--notes", help="notes.json — {\"notes\": [\"...\"]} written by you "
                                    "after reading --facts")
    ap.add_argument("--facts", action="store_true",
                    help="print the computed-facts digest instead of the payload")
    args = ap.parse_args()

    aries_dir = Path(args.aries_dir)
    if not (aries_dir / "manifest.json").is_file():
        sys.exit(f"no manifest.json in {aries_dir} — run aries_triage.py first")
    notes = json.load(open(args.notes)) if args.notes else None
    payload = build(aries_dir, args.qualifier, notes)

    if args.facts:
        print(facts_digest(payload))
    else:
        payload.pop("warnings", None)
        payload.pop("unlabeled_keywords", None)
        json.dump(payload, sys.stdout, indent=1)
        print()


if __name__ == "__main__":
    main()
