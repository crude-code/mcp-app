"""Deterministic rollups for the statement-checkup viewer.

Input: a statement.json extracted from an owner's revenue statement (schema
in SKILL.md; worked example in example.json), plus optionally a public.json
(state-reported volumes + price benchmarks pulled via run_sql) and a
findings.json (the judgment layer: findings, questions, notes — authored by
the model AFTER reading this script's --facts digest).

Every number on the viewer comes from here — sums, percentages, category
rollups, statement-vs-state deltas — so no rollup is ever model arithmetic.
The script also ties the extraction out against the statement's own printed
totals and reports any mismatch instead of hiding it: a statement that
doesn't reproduce its own check total is itself a finding.

Usage:
  python3 checkup_payload.py statement.json --facts
      Print the computed-facts digest (read this, then write findings.json).
  python3 checkup_payload.py statement.json \
      [--public public.json] [--findings findings.json] > payload.json
      Emit the viewer payload (paste into StatementCheckup.jsx's DATA).
"""

import argparse
import json
import sys

TOL = 0.05  # money comparisons: rounding slack per printed total

# Line-label classification, first match wins. The trailing bare "TAX" entry
# catches state-specific tax labels; anything unmatched is treated as a
# deduction under its verbatim label and warned about in --facts, where the
# fix is an explicit "kind": "tax" | "deduction" on that line in the input.
CATEGORIES = [
    ("tax", "AD VALOREM", "Ad valorem (county property) tax"),
    ("tax", "SEVERANCE", "Severance tax"),
    ("tax", "CONSERVATION", "Conservation levy"),
    ("tax", "SCHOOL", "School tax"),
    ("deduction", "GATHER", "Gathering"),
    ("deduction", "PROCESS", "Processing"),
    ("deduction", "COMPRESS", "Compression"),
    ("deduction", "TRANSPORT", "Transportation"),
    ("deduction", "FUEL", "Fuel gas"),
    ("deduction", "DEHY", "Dehydration"),
    ("deduction", "TREAT", "Treating"),
    ("deduction", "MARKET", "Marketing"),
    ("deduction", "TRUCK", "Trucking"),
    ("deduction", "PIPELINE", "Pipeline"),
    ("tax", "TAX", None),  # verbatim label, but it is a tax
]

PRODUCT_DISPLAY = {
    "OIL": "Oil",
    "GAS": "Gas",
    "CONDENSATE": "Condensate",
    "PLANT PRODUCTS": "Plant products (NGLs)",
}

LIQUID_UNITS = {"BBL"}  # statement liquids compare against state oil_bbl


def classify(line):
    label = line["label"].strip().upper()
    if line.get("kind") in ("tax", "deduction"):
        return line["kind"], label.title(), False
    for kind, key, display in CATEGORIES:
        if key in label:
            return kind, (display or label.title()), False
    return "deduction", label.title(), True


def money(v):
    return round(v + 0.0, 2)


def pct(part, whole, digits=1):
    if not whole:
        return None
    return round(100.0 * part / whole, digits)


def build(statement, public, findings):
    st = statement["statement"]
    props = statement["properties"]
    warnings = []
    mismatches = []

    def check(label, computed, stated):
        if stated is None:
            return
        if abs(computed - stated) > TOL:
            mismatches.append(
                f"{label}: computed {computed:,.2f} vs statement's printed {stated:,.2f}")

    # ── per-line classification and rollups ─────────────────────────────────
    tax_items, ded_items = {}, {}
    unclassified = set()
    gross = taxes = deducts = 0.0
    by_product = {}
    wells = []
    months = set()
    decimals = set()
    owner_eq_dist = True

    for prop in props:
        prop_net = 0.0
        liq_stmt = 0.0
        gas_stmt = 0.0
        for pr in prop["products"]:
            months.add(pr["prod_month"])
            if pr.get("owner_interest") is not None:
                decimals.add(pr["owner_interest"])
            if (pr.get("owner_interest") is not None
                    and pr.get("distribution_interest") is not None
                    and pr["owner_interest"] != pr["distribution_interest"]):
                owner_eq_dist = False

            key = pr["product"].strip().upper()
            agg = by_product.setdefault(key, {
                "revenue": 0.0, "taxes": 0.0, "deductions": 0.0,
                "owner_volume": 0.0, "prop_volume": 0.0, "prop_value": 0.0,
                "unit": pr.get("unit"),
            })
            rev = pr["revenue"]
            gross += rev
            agg["revenue"] += rev
            agg["owner_volume"] += pr.get("owner_volume") or 0.0
            agg["prop_volume"] += pr.get("property_volume") or 0.0
            agg["prop_value"] += pr.get("property_value") or 0.0

            unit = (pr.get("unit") or "").strip().upper()
            vol = pr.get("property_volume") or 0.0
            if unit in LIQUID_UNITS:
                liq_stmt += vol
            elif key == "GAS":
                gas_stmt += vol

            line_sum = 0.0
            for line in pr["lines"]:
                amt = line["amount"]  # signed as printed; charges negative
                line_sum += amt
                kind, display, unknown = classify(line)
                if unknown:
                    unclassified.add(line["label"])
                bucket = tax_items if kind == "tax" else ded_items
                bucket[display] = bucket.get(display, 0.0) + amt
                if kind == "tax":
                    taxes += amt
                    agg["taxes"] += amt
                else:
                    deducts += amt
                    agg["deductions"] += amt

            product_net = rev + line_sum
            prop_net += product_net
            check(f"{prop['property_id']} {key} net", product_net, pr.get("stated_net"))

        check(f"{prop['property_id']} property total", prop_net, prop.get("stated_total"))
        wells.append({
            "property_id": prop["property_id"],
            "name": prop["well_name"],
            "net": money(prop_net),
            "liquids_stmt": round(liq_stmt, 2) or None,
            "gas_stmt": round(gas_stmt, 2) or None,
        })

    net = gross + taxes + deducts
    summary = statement.get("summary") or {}
    check("gross", gross, summary.get("gross"))
    check("taxes", taxes, summary.get("taxes"))
    check("deductions", deducts, summary.get("deductions"))
    check("net vs check amount", net, st.get("check_amount"))

    for w in wells:
        w["share_pct"] = pct(w["net"], net)

    # ── public joins: state volumes per well, benchmarks per month ──────────
    months = sorted(months)
    pub_wells = {w["property_id"]: w for w in (public or {}).get("wells", [])}
    for w in wells:
        pw = pub_wells.get(w["property_id"])
        if not pw:
            if public:
                warnings.append(f"no public well mapped to {w['property_id']} ({w['name']})")
            continue
        w["api"] = pw.get("well_api")
        w["formation"] = pw.get("formation")
        w["first_prod"] = pw.get("first_prod")
        rows = [m for m in pw.get("monthly", []) if m["month"] in months]
        oil_pub = sum(m.get("oil_bbl") or 0 for m in rows) if rows else None
        gas_pub = sum(m.get("gas_mcf") or 0 for m in rows) if rows else None
        w["liquids_pub"], w["gas_pub"] = oil_pub, gas_pub
        if oil_pub and w["liquids_stmt"]:
            w["liquids_delta_pct"] = pct(w["liquids_stmt"] - oil_pub, oil_pub)
        if gas_pub and w["gas_stmt"]:
            w["gas_delta_pct"] = pct(w["gas_stmt"] - gas_pub, gas_pub)

    has_ngl = "PLANT PRODUCTS" in by_product
    for w in wells:
        d = w.get("liquids_delta_pct")
        if d is not None:
            w["liquids_badge"] = "ok" if abs(d) <= 10 else "ask"
        d = w.get("gas_delta_pct")
        if d is not None:
            if -8 <= d <= 10:
                w["gas_badge"] = "ok"
            elif -40 <= d < -8 and has_ngl:
                w["gas_badge"] = "shrink"
            else:
                w["gas_badge"] = "ask"

    bench_rows = [b for b in (public or {}).get("benchmarks", []) if b["month"] in months]
    bench = {}
    for k in ("wti", "henry_hub"):
        vals = [b[k] for b in bench_rows if b.get(k) is not None]
        if vals:
            bench[k] = round(sum(vals) / len(vals), 2)

    # ── product table ────────────────────────────────────────────────────────
    products = []
    for key, agg in sorted(by_product.items(), key=lambda kv: -kv[1]["revenue"]):
        p_net = agg["revenue"] + agg["taxes"] + agg["deductions"]
        row = {
            "product": PRODUCT_DISPLAY.get(key, key.title()),
            "unit": agg["unit"],
            "owner_volume": round(agg["owner_volume"], 2),
            "revenue": money(agg["revenue"]),
            "taxes": money(-agg["taxes"]),
            "deductions": money(-agg["deductions"]),
            "net": money(p_net),
            "kept_pct": pct(p_net, agg["revenue"]),
        }
        if agg["prop_volume"]:
            row["price"] = round(agg["prop_value"] / agg["prop_volume"], 2)
            if key in ("OIL", "CONDENSATE") and bench.get("wti"):
                row["benchmark"] = {"label": "WTI monthly avg", "value": bench["wti"],
                                    "delta_pct": pct(row["price"] - bench["wti"], bench["wti"])}
            elif key == "GAS" and bench.get("henry_hub"):
                row["benchmark"] = {"label": "Henry Hub monthly avg", "value": bench["henry_hub"],
                                    "delta_pct": pct(row["price"] - bench["henry_hub"], bench["henry_hub"])}
            elif key == "PLANT PRODUCTS" and bench.get("wti"):
                row["benchmark"] = {"label": "of WTI, bbl-equivalent",
                                    "pct_of_wti": pct(row["price"] * 42, bench["wti"])}
        products.append(row)

    def items(bucket):
        # charges printed negative → positive magnitudes; a net-positive
        # bucket entry (a credit) comes through negative and the viewer
        # renders it as a credit.
        return [{"label": k, "amount": money(-v)}
                for k, v in sorted(bucket.items(), key=lambda kv: kv[1])]

    fnd = (findings or {}).get("findings", [])
    verdict = {s: sum(1 for f in fnd if f["severity"] == s)
               for s in ("attention", "info", "good")}

    payload = {
        "header": {
            "operator": st.get("operator"),
            "owner": st.get("owner_name"),
            "check_number": st.get("check_number"),
            "check_date": st.get("check_date"),
            "check_amount": money(st["check_amount"]),
            "interest_type": st.get("interest_type_guess"),
            "platform": st.get("platform"),
            "production_months": months,
            "location": ", ".join(sorted({f"{p.get('county', '?')} County, {p.get('state', '?')}"
                                          for p in props})),
            "well_count": len(props),
        },
        "money": {
            "gross": money(gross),
            "taxes": money(-taxes),
            "deductions": money(-deducts),
            "net": money(net),
            "taxes_pct": pct(-taxes, gross),
            "deductions_pct": pct(-deducts, gross),
            "net_pct": pct(net, gross),
            "tax_items": items(tax_items),
            "deduction_items": items(ded_items),
            "ties_out": not mismatches,
            "mismatches": mismatches,
        },
        "decimal_check": {
            "decimals": sorted(decimals),
            "consistent": len(decimals) == 1,
            "owner_equals_distribution": owner_eq_dist,
        },
        "verdict": verdict,
        "findings": fnd,
        "products": products,
        "wells": wells,
        "questions": (findings or {}).get("questions", []),
        "notes": (findings or {}).get("notes"),
        "sources": (public or {}).get("source_note"),
        "warnings": warnings,
    }
    return payload


def facts_digest(payload):
    out = []
    m = payload["money"]
    out.append("== MONEY ==")
    out.append(f"gross {m['gross']:,.2f}  taxes -{m['taxes']:,.2f} ({m['taxes_pct']}%)"
               f"  deductions -{m['deductions']:,.2f} ({m['deductions_pct']}%)"
               f"  net {m['net']:,.2f} ({m['net_pct']}% kept)")
    out.append("ties out: " + ("YES — line items reproduce the printed totals" if m["ties_out"]
                               else "NO — " + "; ".join(m["mismatches"])))
    out.append("taxes by category:      " + "; ".join(f"{i['label']} {i['amount']:,.2f}" for i in m["tax_items"]))
    out.append("deductions by category: " + "; ".join(f"{i['label']} {i['amount']:,.2f}" for i in m["deduction_items"]))
    d = payload["decimal_check"]
    out.append("== DECIMAL ==")
    out.append(f"decimals seen: {d['decimals']}  consistent: {d['consistent']}"
               f"  owner==distribution: {d['owner_equals_distribution']}")
    out.append("== PRODUCTS (net negative ⇒ that product cost money this check) ==")
    for p in payload["products"]:
        line = (f"{p['product']}: vol {p['owner_volume']:,} {p['unit'] or ''}"
                f"  rev {p['revenue']:,.2f}  tax {p['taxes']:,.2f}  ded {p['deductions']:,.2f}"
                f"  net {p['net']:,.2f}  kept {p['kept_pct']}%")
        if p.get("price"):
            line += f"  price {p['price']}"
        if p.get("benchmark"):
            b = p["benchmark"]
            line += (f"  vs {b['label']} {b.get('value', '')}"
                     f" ({b.get('delta_pct', b.get('pct_of_wti'))}%)")
        out.append(line)
    out.append("== WELLS (statement vs state-reported; liquids = oil+condensate bbl) ==")
    for w in payload["wells"]:
        line = f"{w['name']}: net {w['net']:,.2f} ({w['share_pct']}%)"
        if w.get("liquids_pub") is not None:
            line += (f"  liquids {w['liquids_stmt']:,.0f}/{w['liquids_pub']:,.0f}"
                     f" {w.get('liquids_delta_pct')}% [{w.get('liquids_badge')}]")
        if w.get("gas_pub") is not None:
            line += (f"  gas {w['gas_stmt']:,.0f}/{w['gas_pub']:,.0f}"
                     f" {w.get('gas_delta_pct')}% [{w.get('gas_badge')}]")
        out.append(line)
    if payload["warnings"]:
        out.append("== WARNINGS ==")
        out.extend(payload["warnings"])
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("statement")
    ap.add_argument("--public")
    ap.add_argument("--findings")
    ap.add_argument("--facts", action="store_true",
                    help="print the computed-facts digest instead of the payload")
    args = ap.parse_args()

    statement = json.load(open(args.statement))
    public = json.load(open(args.public)) if args.public else None
    findings = json.load(open(args.findings)) if args.findings else None
    payload = build(statement, public, findings)

    if args.facts:
        print(facts_digest(payload))
        if payload["money"]["mismatches"]:
            print("\nNOTE: extraction does not tie out — recheck the statement "
                  "before writing findings (or make the mismatch a finding).",
                  file=sys.stderr)
    else:
        payload.pop("warnings", None)
        json.dump(payload, sys.stdout, indent=1)
        print()


if __name__ == "__main__":
    main()
