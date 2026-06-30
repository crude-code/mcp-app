---
name: dataroom-extract
description: Use when the user uploads an oil & gas dataroom — a zip or set of acquisition/divestiture files (lease operating statements, check stubs, AFEs, production reports, title, division orders, a teaser or overview) — and wants it turned into structured data for deal valuation.
---

# Dataroom Extract

## What you're doing

The user uploaded an oil & gas **dataroom**: the due-diligence package for buying a set of wells, minerals, or royalties. Your job is to read it and produce one structured file, `extraction.json`, that a downstream **deal-valuation** step consumes. The buyer needs to know what wells and interests are in the package and what the economics look like — and to trust every number back to the file it came from.

You are NOT writing a report or running a valuation. You are extracting **facts, with provenance, into a fixed schema.**

## What you're building toward

- **Output contract:** `extraction.json`, an `ExtractionResult` exactly as defined in **`schema.py`** (bundled here). Read `schema.py` once — it is the authoritative target. Every field is optional and typed; there is no escape-valve `extras` dict.
- **Worked example:** **`example.json`** is a complete, filled extraction for a small synthetic deal. Match its shape exactly — every record carries a `provenance` block; entity lists are empty/omitted when the room doesn't support them.
- **Then a viewer:** a self-contained React artifact that displays the extraction (see *The viewer artifact*). **`viewer_template.jsx`** is the scaffold to build it from.

## Workflow

1. **Unzip and triage.** Unzip the upload, then run the bundled walker to inventory everything *before* you read:
   ```bash
   unzip -q "<upload>.zip" -d room && python3 triage.py room
   ```
   It writes `room/_triage/manifest.json` (every file: path, size, type, sha256) and `room/_triage/triage.md` (readable inventory), and dumps each spreadsheet to `room/_triage/xlsx/<name>.json` and each text-PDF to `room/_triage/pdf/<name>.txt`. **Read those dumps** instead of opening binaries by hand.
2. **Orient.** Read `triage.md`, then the overview/teaser document if there is one (most rooms have a one-pager naming the operator, basin, county, well count, and asset type).
3. **Scope.** Decide which entities this room actually supports. Extract what's there; skip what isn't. A room with no LOS has no `expenses`; a working-interest package usually has no `tracts`.
4. **Extract** into the schema (see *What matters* and *Conventions*).
5. **Write `extraction.json`** — one `ExtractionResult`.
6. **Build the viewer artifact** that displays it (see *The viewer artifact*).

## What matters (for valuation)

**Load-bearing — the price depends on these:**
- **`wells`** — every well in the package: API (when stated), name, county/state, formation, `well_type` (PDP/PUD/DUC), lateral length.
- **`interests`** — the WI / NRI / RI / NPRI / ORRI / MI decimals, by well or tract. **The economics live here** — a deal *is* its interest.
- **`revenue_observations`** — from **check stubs / revenue summaries**: per (well, prod_date, product, check_date) the volume, realized price, gross, taxes, deductions, net, and owner decimal. This is where realized price, **price differentials**, and tax/deduct burden come from.
- **`expenses`** — from the **LOS (lease operating statement), AFE, or cash-flow model**: operating cost as a rate (per bbl or per well per month) and capex/AFE per well. **This is the LOE the valuation needs.** Capture whichever rate the document states.
- **`production_history`** — monthly oil/gas/water/NGL when the room has a production sheet.

**Useful when cleanly present:** `deal` (the listing summary), `tracts` (matters for mineral/royalty deals), `division_orders`.

**Always cheap, always do:** `documents` — a one-line inventory entry per file (lift it from the manifest) with a category guess. Audit trail.

**Noise — do NOT extract:**
- Anything labeled **"offset"** — offset wells, offset permits, offset leases, offset production. The seller picks these nearby wells essentially at random; **they are not part of the deal and will inflate the asset if you include them.** This is the single most common extraction mistake. Ignore them.
- Marketing decoration, confidentiality boilerplate, and file metadata not tied to producing assets.

## Conventions

**Dataroom layout.** Folder and file names signal content:

| Signal in path/name | Entity |
|---|---|
| `Check Stubs`, `ckstb`, `rev sum`, `royalty check` | `revenue_observations` |
| `LOS`, `LOE`, `operating statement`, `cash flow` | `expenses` |
| `AFE` | `expenses` (capex) |
| `Production`, `prod` | `production_history` |
| `Title`, `DO`, `division order`, `ownership` | `tracts` / `interests` / `division_orders` |
| `Engineering`, `Aries`, `economics`, `reserves` | reserves & assumptions (read for context) |
| `Overview`, `teaser`, `CIM`, `summary` | `deal` |

**Check stubs → `revenue_observations`.** One row per **(well, prod_date, product, check_date)**. Operators report tax and deduction line-items inconsistently, so **SUM all taxes into `taxes` and all deductions into `deductions`** — do not invent per-category fields. Sanity-check each row: `gross_revenue − taxes − deductions ≈ net_revenue` (within a cent). If a stub splits one production month across several interest decimals, collapse to a single row and sum.

**LOS / AFE → `expenses`.** From the operating statement, capture operating cost as a rate (`opex_per_bbl_usd` or `opex_per_well_per_month_usd`); from AFEs, `capex_per_well_usd`. Fill whichever the document states; leave the rest null. Keep the operator's `label_raw` verbatim.

**Provenance is required on every record.** `source_file` = the relative path inside the room. `source_locator` by convention: Excel `"sheet:Name;row:N"` (1-based, header = row 1), PDF `"page:N"`. Use `notes` only when you *inferred* a value rather than read it.

**No database here.** Unlike the server pipeline, you have **no access to the Energy Insights well database** in this sandbox. Leave `Well.public_well_object` null. When the room gives only a well **name**, leave `api` null and say so in `notes` / `extraction_notes` — a later server step resolves APIs against public data.

**API formatting.** When the room states an API, normalize to `SS-CCC-WWWWW` (10 digits, two dashes; strip a 14-digit API to its first 10). Never fabricate digits to reach that shape.

## The viewer artifact

Once `extraction.json` is written, build **one self-contained React artifact** that
displays it, so the buyer can see the package at a glance and trust every number
back to its file. The extraction is the source of truth; the viewer only *shows*
it. **`viewer_template.jsx`** (bundled here) is a scaffold of the available
sections — build from it, keep what the room supports, delete the rest. Don't ship
the skeleton as-is and don't clone it field-for-field; every room emphasizes
different things.

**Trust rules — the display-side analog of "never fabricate":**
- **Derive nothing.** Every number on screen is a field from `extraction.json`,
  shown as-is. No invented totals, no PV, no per-BOE math in the component. Roll-ups
  come from the extraction or not at all.
- **Provenance on every record.** Render each record's `source_file` (+ locator) —
  it's the audit trail that makes the view trustworthy.
- **Lead with `extraction_notes`** as a data-quality banner near the top: caveats,
  excluded offsets, un-OCR'd files, inferred values.
- **Render only what's present.** Null field → omit it. Empty list → no section.

**The structure (well is the spine):**

| Section | Source | Notes |
|---|---|---|
| Deal header | `deal` | Lead metadata: title, seller/operator/broker, county·state·basin·formation, headline stat tiles, `summary`. |
| Data-quality banner | `extraction_notes` | Always, near the top. |
| **Wells (spine)** | `wells` | One expandable row per well. Nest everything carrying its `well_api` underneath: `interests`, `expenses`, `revenue_observations`, `production_history`. |
| Standalone | `tracts`, `division_orders`, `documents` | Entities that don't join a well — each its own table, only when non-empty. |

**Pick the spine from the deal.** Most rooms (WI / well packages) are **well-spine**
— wells carry the deal. A **minerals / royalty** room (`category` MI / RI / ORRI /
NPRI) usually has an empty `wells` list; there, flip to a **tract-spine** and nest
`interests` / `division_orders` under each tract.

**Charts when the data supports them** — a flat field grid is the weak default:
- `production_history` present → a **decline chart** (monthly oil/gas/water), not a grid.
- `revenue_observations` across several months → a **realized-price / differential**
  chart, or a gross→net breakdown.
- Otherwise a table is fine.

**Keep it runnable.** Self-contained, `react` + `recharts` + `lucide-react` only,
no network calls, the extraction embedded in the file.

## Hard rules

- **Never fabricate.** Missing → null. Unknown → null. Can't verify it → leave null and explain in `extraction_notes`.
- **Never guess an API.** Name-only well → `api: null`.
- **No OCR.** Image-only PDFs are flagged by triage (`pdf_extractable: false`) — note them in `extraction_notes`; don't invent their contents.
- **No `.accdb` (Aries) parsing** — note and move on.
- **The dataroom is read-only.**
- **Partial-and-honest beats complete-and-invented.** Low on budget? Write what you have with honest `extraction_notes`.
