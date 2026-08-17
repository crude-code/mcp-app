#!/usr/bin/env python3
"""Assemble the viewer display payload from extraction.json.

Run this after writing extraction.json, before building the viewer artifact:

    python3 viewer_payload.py extraction.json > viewer_payload.json

The output is the ONLY thing pasted into DataroomViewer.jsx's `DATA` slot —
never the raw extraction. The raw extraction (with its 100s–1000s of
revenue/production rows) is persisted via persist_pack.py; the viewer shows
the curated cover page and this script computes every derived number on it
deterministically, so no rollup is ever model-arithmetic:

  - LTM net revenue, per well and package: `net_revenue` summed from
    `revenue_observations` over the trailing 12 months ending at the latest
    prod month present. Pre-opex, net to the extracted interest.
  - Revenue share: well LTM / package LTM.
  - WI/NRI/RI/NPRI/ORRI per well or tract: summed across that record's
    interest rows (a split interest sums; the normal case is one row each),
    shown as percent at full stated precision — royalty decimals are only
    ever rounded for display, in the viewer.
  - Manifest groups: wells by `well_type` (PDP / SI / DUC / PUD / PA).
  - Document folders: files grouped by their last two path segments.

Rows join revenue to wells by API, falling back to a case-insensitive match
of `well_identifier` against the well name when either side lacks an API.
Anything absent in the extraction is null/[] in the payload and the viewer
hides that module. Stdlib only — works in the sandbox.
"""
import argparse
import json
import posixpath
import sys

# Manifest group order + labels, by Well.well_type.
STATUS_ORDER = ["PDP", "SI", "DUC", "PUD", "PA"]
STATUS_LABELS = {
    "PDP": "Producing",
    "SI": "Shut-in",
    "DUC": "Drilled, uncompleted",
    "PUD": "Undrilled",
    "PA": "Plugged & abandoned",
}

DEAL_FIELDS = [
    "title", "seller", "broker", "process_type", "category", "asset_type",
    "basin", "state", "county", "formation", "effective_date", "bid_due_date",
    "summary", "current_net_boed",
]


def _month(datestr):
    """'2025-06-01' | '2025-06' -> '2025-06'; None -> None."""
    return datestr[:7] if datestr and len(datestr) >= 7 else None


def _month_index(month):
    y, m = month.split("-")
    return int(y) * 12 + int(m)


def _round(value, digits=2):
    return None if value is None else round(value, digits)


def _pct(decimal):
    """Interest decimal -> percent, rounded to 8 decimals of the underlying
    decimal (0.0059439 -> 0.59439). The rounding exists only to suppress
    float-summation noise (0.15 + 0.06 -> 21.000000000000004); it must stay
    well past any stated decimal, because a royalty decimal's trailing digits
    are load-bearing — round percent to 4 and 0.00170514 becomes 0.001705."""
    return None if decimal is None else round(decimal * 100, 6)


def _well_key(api, name):
    if api:
        return ("api", api)
    return ("name", (name or "").casefold()) if name else None


def _tract_key(name):
    return ("tract", name.casefold()) if name else None


def _interest_key(interest):
    """Interests hang off a well API or, in minerals/royalty rooms, a tract
    name. Keying on the API alone drops every tract-keyed row on the floor."""
    return (_well_key(interest.get("well_api"), None)
            or _tract_key(interest.get("tract_name")))


def _ltm_by_well(revenue_rows):
    """Trailing-12 net revenue keyed by well: window ends at the latest
    prod month present anywhere in revenue_observations. Returns
    (per_well_key, window) — ({}, None) when there is no dated revenue."""
    months = {m for r in revenue_rows if (m := _month(r.get("prod_date")))}
    if not months:
        return {}, None
    end = max(months)
    start_index = _month_index(end) - 11
    per_well = {}
    for r in revenue_rows:
        m = _month(r.get("prod_date"))
        if not m or not (start_index <= _month_index(m) <= _month_index(end)):
            continue
        key = _well_key(r.get("well_api"), r.get("well_identifier"))
        if key is None or r.get("net_revenue") is None:
            continue
        per_well[key] = per_well.get(key, 0.0) + r["net_revenue"]
    start = f"{start_index // 12:04d}-{start_index % 12 or 12:02d}"
    if start_index % 12 == 0:  # December: 12*y + 12 -> year y, month 12
        start = f"{start_index // 12 - 1:04d}-12"
    return per_well, {"start": start, "end": end}


INTEREST_FIELDS = (("wi_decimal", "wi"), ("nri_decimal", "nri"),
                   ("ri_decimal", "ri"), ("npri_decimal", "npri"),
                   ("orri_decimal", "orri"))


def _interest_totals(interests):
    """Summed interest decimals per well API *or* tract name, keyed by
    `_interest_key`, plus the reversion/caveat notes that ride on interest
    rows (e.g. a payout reversion). All five decimals are summed — an
    ORRI/NPRI package's economics live in the fields the WI/NRI/RI trio
    doesn't cover."""
    by_key = {}
    for i in interests:
        key = _interest_key(i)
        if key is None:
            continue
        slot = by_key.setdefault(key, {out: None for _, out in INTEREST_FIELDS})
        slot.setdefault("notes", [])
        for field, out in INTEREST_FIELDS:
            if i.get(field) is not None:
                slot[out] = (slot[out] or 0.0) + i[field]
        note = (i.get("provenance") or {}).get("notes")
        if note and note not in slot["notes"]:
            slot["notes"].append(note)
    return by_key


def _lookup(per_well, api, name):
    for key in (_well_key(api, None), _well_key(None, name)):
        if key and key in per_well:
            return per_well[key]
    return None


def build_manifest(wells, interest_by_key, revenue_rows):
    """Wells spine: manifest groups by well_type, rows sorted by LTM desc."""
    ltm, window = _ltm_by_well(revenue_rows)
    package_ltm = sum(ltm.values()) or None

    rows_by_status = {}
    for w in wells:
        ints = _lookup(interest_by_key, w.get("api"), None) or {}
        well_ltm = _lookup(ltm, w.get("api"), w.get("name"))
        share = (well_ltm / package_ltm * 100) if well_ltm is not None and package_ltm else None
        status = w.get("well_type") or "UNKNOWN"
        rows_by_status.setdefault(status, []).append({
            "api": w.get("api"),
            "name": w.get("name"),
            "operator": w.get("operator"),
            "formation": w.get("formation"),
            "basin": w.get("basin"),
            "county": w.get("county"),
            "state": w.get("state"),
            "wi_pct": _pct(ints.get("wi")),
            "nri_pct": _pct(ints.get("nri")),
            "ri_pct": _pct(ints.get("ri")),
            "npri_pct": _pct(ints.get("npri")),
            "orri_pct": _pct(ints.get("orri")),
            "lateral_ft": w.get("lateral_length_ft"),
            "first_prod": w.get("first_prod_date"),
            "ltm_net_revenue": _round(well_ltm),
            "revenue_share_pct": _round(share),
            "note": " ".join((ints.get("notes") or [])) or None,
        })

    order = {s: n for n, s in enumerate(STATUS_ORDER)}
    groups = []
    for status in sorted(rows_by_status, key=lambda s: (order.get(s, len(order)), s)):
        rows = rows_by_status[status]
        rows.sort(key=lambda r: (-(r["ltm_net_revenue"] or 0), r["name"] or ""))
        group_ltm = sum(r["ltm_net_revenue"] or 0 for r in rows) or None
        groups.append({
            "status": status,
            "label": STATUS_LABELS.get(status, status),
            "well_count": len(rows),
            "ltm_net_revenue": _round(group_ltm),
            "wells": rows,
        })
    return groups, window, _round(package_ltm)


def build_tracts(tracts, interest_by_key):
    """Tracts spine (minerals/royalty rooms): one flat table.

    `royalty_pct` is the lease's royalty rate; the `*_pct` columns are the
    owner's own decimals, summed from the interest rows that name this tract.
    Without that join a minerals room whose interests are tract-keyed shows no
    interest anywhere in the viewer — and the interest *is* the deal."""
    out = []
    for t in tracts:
        ints = interest_by_key.get(_tract_key(t.get("name"))) or {}
        out.append({
            "name": t.get("name"),
            "legal_description": t.get("legal_description"),
            "county": t.get("county"),
            "state": t.get("state"),
            "gross_acres": t.get("gross_acres"),
            "nma": t.get("nma"),
            "nra": t.get("nra"),
            "royalty_pct": _pct(t.get("royalty_decimal")),
            "ri_pct": _pct(ints.get("ri")),
            "nri_pct": _pct(ints.get("nri")),
            "npri_pct": _pct(ints.get("npri")),
            "orri_pct": _pct(ints.get("orri")),
            "operator": t.get("operator"),
            "lessee": t.get("lessee"),
        })
    return out


def build_documents(documents):
    """Files grouped by their last TWO path segments, largest folder first.
    One segment loses the context in nested rooms — operator/year/month
    trees collapse into folders literally named "2025"."""
    groups = {}
    for d in documents:
        parent = posixpath.dirname(d.get("path") or "")
        grandparent = posixpath.basename(posixpath.dirname(parent))
        base = posixpath.basename(parent)
        folder = (f"{grandparent}/{base}" if grandparent and base
                  else base or "(root)")
        g = groups.setdefault(folder, {"files": [], "categories": []})
        g["files"].append(posixpath.basename(d.get("path") or "") or d.get("path"))
        cat = d.get("category")
        if cat and cat not in g["categories"]:
            g["categories"].append(cat)
    out = []
    for folder in sorted(groups, key=lambda f: (-len(groups[f]["files"]), f)):
        g = groups[folder]
        out.append({
            "folder": folder,
            "count": len(g["files"]),
            "categories": ", ".join(sorted(g["categories"])),
            "files": sorted(g["files"]),
        })
    return out


def build_payload(ext):
    deal_in = ext.get("deal") or {}
    wells = ext.get("wells") or []
    interests = ext.get("interests") or []
    revenue = ext.get("revenue_observations") or []
    documents = ext.get("documents") or []
    tracts = ext.get("tracts") or []

    interest_by_key = _interest_totals(interests)
    manifest, window, package_ltm = build_manifest(wells, interest_by_key, revenue)

    wi_values = [r["wi_pct"] for g in manifest for r in g["wells"] if r["wi_pct"] is not None]
    stats = {
        "well_count": len(wells) or deal_in.get("well_count"),
        "tract_count": len(tracts) or None,
        "doc_count": len(documents) or None,
        "net_boed": deal_in.get("current_net_boed"),
        "seller_pv10_mm": deal_in.get("pv10_mid_mm"),
        "ltm_net_revenue": package_ltm,
        "ltm_net_revenue_mo": _round(package_ltm / 12) if package_ltm else None,
        "avg_wi_pct": _round(sum(wi_values) / len(wi_values), 3) if wi_values else None,
        "wi_min_pct": _round(min(wi_values), 3) if wi_values else None,
        "wi_max_pct": _round(max(wi_values), 3) if wi_values else None,
    }

    return {
        "deal": {k: deal_in.get(k) for k in DEAL_FIELDS},
        "stats": stats,
        "flags": ext.get("flags") or [],
        "notes": ext.get("extraction_notes"),
        "ltm_window": window,
        "manifest": manifest,
        "tracts": build_tracts(tracts, interest_by_key),
        "documents": build_documents(documents),
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("path", nargs="?", default="extraction.json")
    args = ap.parse_args()
    with open(args.path) as f:
        ext = json.load(f)
    json.dump(build_payload(ext), sys.stdout, separators=(",", ":"))
    print()


if __name__ == "__main__":
    main()
