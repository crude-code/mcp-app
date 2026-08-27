#!/usr/bin/env python3
"""Pack extraction.json into a persist kit and upload it.

Run this after writing extraction.json. Normal use: call the
dataroom_save_extraction tool first (it returns a one-time upload URL),
then let this script move the bytes — the kit never enters the chat:

    python3 persist_pack.py extraction.json --upload "<upload_url>"
    python3 persist_pack.py extraction.json --upload "<url>" --with-production

It POSTs the kit, compares the server's `stored` counts against the local
`expected_stored`, and prints a one-line verdict:
  {"saved": true, "verified": true, "extraction_id": ..., "label": ...}
verified=false means the server stored fewer rows than packed — mint a fresh
URL with the returned extraction_id and re-upload. A connection error means
the sandbox can't reach the upload host: the printed hint explains the
network-allowlist fix; relay it to the user.

Without --upload it prints the full kit JSON (extraction / revenue_csv /
production_csv / sources / counts / expected_stored) for inspection and
tests. Stdlib only — works in the sandbox.

Why production is omitted by default: for wells with APIs in states the
platform ingests, monthly production is already in the platform database —
persisting the seller's copy adds nothing. Pass --with-production when wells
are name-only, in a state the platform doesn't cover, or the sheet carries
NGL detail worth keeping.
"""
import argparse
import csv
import io
import json
import sys
import urllib.error
import urllib.request

# Must match server/extraction_transport.py exactly (drift-tested server-side).
PRODUCTION_HEADER = [
    "well_api", "month", "oil_bbl", "gas_mcf", "water_bbl", "ngl_bbl",
    "days_on", "src", "row", "notes",
]
REVENUE_HEADER = [
    "well_api", "well_identifier", "prod_date", "check_date", "product_raw",
    "product", "volume", "volume_unit", "price", "gross_revenue", "taxes",
    "deductions", "net_revenue", "owner_decimal", "interest_type", "operator",
    "src", "row", "notes",
]

ENTITY_LISTS = [
    "wells", "tracts", "interests", "production_history",
    "revenue_observations", "expenses", "division_orders", "documents",
]


def _split_locator(locator):
    """'sheet:Monthly;row:247' -> ('sheet:Monthly;row:{n}', '247');
    'page:1' -> ('page:{n}', '1'); no trailing digits -> (locator, '')."""
    if not locator:
        return None, ""
    i = len(locator)
    while i > 0 and locator[i - 1].isdigit():
        i -= 1
    if i == len(locator):                      # no trailing digit run
        return locator, ""
    return locator[:i] + "{n}", locator[i:]


def _fmt(value):
    if value is None:
        return ""
    if isinstance(value, float):
        return str(int(value)) if value.is_integer() else repr(value)
    return str(value)


def _pack_table(rows, header, legend, legend_index, entity):
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(header)
    for n, rec in enumerate(rows):
        prov = rec.get("provenance") or {}
        source_file = prov.get("source_file")
        if not source_file:
            sys.exit(f"error: {entity}[{n}] has no provenance.source_file — "
                     "fix extraction.json before packing (never fabricate).")
        template, row_no = _split_locator(prov.get("source_locator"))
        key = (source_file, template)
        if key not in legend_index:
            legend_index[key] = str(len(legend_index) + 1)
            legend[legend_index[key]] = [source_file, template]
        cells = [_fmt(rec.get(col)) for col in header[:-3]]
        cells += [legend_index[key], row_no, _fmt(prov.get("notes"))]
        writer.writerow(cells)
    return buf.getvalue()


def _post_kit(url, kit):
    """POST the transport fields to the one-time upload URL; return the
    server's JSON response. Raises urllib errors for the caller to explain."""
    body = json.dumps(
        {k: kit[k] for k in ("extraction", "revenue_csv", "production_csv", "sources")},
        separators=(",", ":"),
    ).encode()
    req = urllib.request.Request(
        url, data=body, method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=180) as resp:
        return json.loads(resp.read().decode())


def _upload_and_verify(url, kit):
    try:
        result = _post_kit(url, kit)
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:2000]
        try:
            detail = json.loads(detail).get("error", detail)
        except ValueError:
            pass
        print(json.dumps({"saved": False, "status": e.code, "error": detail}))
        return 1
    except (urllib.error.URLError, OSError) as e:
        print(json.dumps({
            "saved": False,
            "error": f"could not reach the upload host: {e}",
            "hint": ("The sandbox's network allowlist is likely missing the upload "
                     "host. Tell the user to add it under Claude's network egress "
                     "settings, then retry in a new chat. Do not fall back to "
                     "pasting the kit into chat."),
        }))
        return 1

    verified = result.get("stored") == kit["expected_stored"]
    print(json.dumps({
        "saved": bool(result.get("saved")),
        "verified": verified,
        "extraction_id": result.get("extraction_id"),
        "label": result.get("label"),
        "stored": result.get("stored"),
        "expected_stored": kit["expected_stored"],
    }))
    return 0 if result.get("saved") and verified else 1


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("path", nargs="?", default="extraction.json")
    ap.add_argument("--with-production", action="store_true",
                    help="pack production_history instead of omitting it")
    ap.add_argument("--upload", metavar="URL", default=None,
                    help="POST the kit to this one-time upload URL (from "
                         "dataroom_save_extraction) instead of printing it")
    args = ap.parse_args()

    with open(args.path) as f:
        ext = json.load(f)

    counts = {key: len(ext.get(key) or []) for key in ENTITY_LISTS}
    legend, legend_index = {}, {}

    revenue_rows = ext.get("revenue_observations") or []
    revenue_csv = _pack_table(revenue_rows, REVENUE_HEADER, legend,
                              legend_index, "revenue_observations") if revenue_rows else None

    production_rows = ext.get("production_history") or []
    production_csv = None
    if production_rows and args.with_production:
        production_csv = _pack_table(production_rows, PRODUCTION_HEADER, legend,
                                     legend_index, "production_history")

    slim = dict(ext)
    slim.pop("_comment", None)
    slim["revenue_observations"] = []
    slim["production_history"] = []
    if production_rows and not args.with_production:
        note = (f"[persist] production_history ({len(production_rows)} rows) not "
                "persisted — reconstructable from public state data by API.")
        slim["extraction_notes"] = ((slim.get("extraction_notes") or "").rstrip()
                                    + (" " if slim.get("extraction_notes") else "") + note)

    expected = dict(counts)
    expected["production_history"] = len(production_rows) if production_csv else 0

    kit = {
        "extraction": slim,
        "revenue_csv": revenue_csv,
        "production_csv": production_csv,
        "sources": legend,
        "counts": counts,
        "expected_stored": expected,
    }
    if args.upload:
        sys.exit(_upload_and_verify(args.upload, kit))
    print(json.dumps(kit, separators=(",", ":")))


if __name__ == "__main__":
    main()
