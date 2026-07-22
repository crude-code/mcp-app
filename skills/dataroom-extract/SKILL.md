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
- **Then a viewer:** a self-contained React artifact that displays the extraction (see *The viewer artifact*). **`DataroomViewer.jsx`** is the finished, frozen component — you paste the extraction in, you don't rebuild it.

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
6. **Persist it** — call the `save_dataroom_extraction` MCP tool with the full
   extraction and a short `label` (the deal/teaser title). Do this every run,
   right after the file is written, even for a partial extraction — the stored
   copy is what makes the deal traceable later. Keep the returned
   `extraction_id`: if the extraction is corrected after user review, re-call
   the tool with that same `extraction_id` so the stored copy is updated in
   place, not duplicated. If the save returns an error, tell the user and keep
   going — never block the extraction or the viewer on persistence.
7. **Produce the viewer** — paste the extraction into the bundled component (see
   *The viewer artifact*). Do this every run, even when a valuation follows.

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

**No database here.** Unlike the server pipeline, you have **no access to the Energy Insights well database** in this sandbox. Leave `Well.public_well_object` null. When the room gives only a well **name**, leave `api` null and say so in `notes` / `extraction_notes` — a later server step resolves APIs against public data. (MCP tools remain available — persisting via `save_dataroom_extraction` is expected; it's the well-database *lookup* you don't have.)

**API formatting.** When the room states an API, normalize to `SS-CCC-WWWWW` (10 digits, two dashes; strip a 14-digit API to its first 10). Never fabricate digits to reach that shape.

## The viewer artifact

Once `extraction.json` is written, give the user a viewer so they can see the
package at a glance and trust every number back to its file. **`DataroomViewer.jsx`**
(bundled here) is the finished, frozen component — you do **not** build, redesign,
or adapt it. To produce the viewer:

1. Open `DataroomViewer.jsx`.
2. Paste this room's `extraction.json` into the one marked `const EXTRACTION = {}`.
3. Ship that as the artifact. That's the whole job.

The component re-derives the entire view from the schema, so it already handles
everything that varies room to room — **don't reinvent any of it:**
- **Spine** — wells if present, else tracts (minerals/royalty rooms). Automatic.
- **Prominence** — a well with `production_history` leads with its decline curve;
  otherwise a field summary. Automatic.
- **Presence** — every section renders only when its data exists; null fields are
  omitted. Automatic.
- **Trust** — provenance on every record, `extraction_notes` as the data-quality
  banner, and **nothing derived** (every number is a field shown as-is) are baked
  into the component, not your responsibility to re-enforce each run.

So there are no per-room layout decisions to make and nothing to overfit to: same
component, just this room's data. Deps are `react` + `recharts` + `lucide-react`
(the claude.ai Artifact runtime) — don't add others.

## When the dataroom feeds a valuation

Often the room isn't the end goal — the user wants to **value** the interest. The
dataroom is the input that makes that possible: the `wells` and the `interests`
decimal are exactly what `forecast_wells` / `run_valuation` need. In that case:

1. Extract → write `extraction.json` → persist (`save_dataroom_extraction`).
2. **Show the viewer first** — it's the confirm-before-you-value step. The user
   eyeballs what came out of the room (which wells, what interest decimal, what the
   production looks like) and confirms it's right before any money number is built.
3. Then proceed into the valuation flow (`forecast_wells` → assumptions grid →
   `run_valuation`), carrying the wells and the interest from the extraction.

**Build the viewer every time you process a dataroom**, whether or not a valuation
follows. It's the deliverable that makes the extraction auditable — not an optional
extra to skip when the goal is downstream.

## Hard rules

- **Never fabricate.** Missing → null. Unknown → null. Can't verify it → leave null and explain in `extraction_notes`.
- **Never guess an API.** Name-only well → `api: null`.
- **No OCR.** Image-only PDFs are flagged by triage (`pdf_extractable: false`) — note them in `extraction_notes`; don't invent their contents.
- **No `.accdb` (Aries) parsing** — note and move on.
- **The dataroom is read-only.**
- **Partial-and-honest beats complete-and-invented.** Low on budget? Write what you have with honest `extraction_notes`.
