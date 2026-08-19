---
name: statement-checkup
description: Use when an individual mineral or royalty owner uploads a revenue statement (a royalty check stub / check detail) and wants help understanding it — "I'm a mineral owner and I need help understanding my revenue statement." A plain-English health check of one check: which wells it covers, statement volumes vs publicly reported production, where the money went, and anything worth asking the operator about. Not a valuation and not a dataroom.
---

# Statement Checkup

## What you're doing

The user is an **individual mineral or royalty owner** — usually not an oil &
gas professional — holding a revenue statement (the detail pages behind a
royalty check) that they find hard to read. Your job is a **health check**:
read the statement, verify it against public data, explain where the money
went, and surface anything worth a question to the operator — all in plain
English.

This is NOT the dataroom flow and NOT a valuation. `dataroom-extract` is for
an acquisition package headed to a bid; this is one owner's check. If the
user later asks what their interest is *worth*, that's a follow-up — offer
the valuation flow then, never as part of the checkup.

## Who you're writing for

- **Plain English, dollars first.** "Fees for moving gas took $47.77 out of
  your check," not "post-production cost burden of 101% of gas revenue."
  Define each term of art inline, once ("severance tax — the state's tax on
  produced minerals").
- **Reassure where things are normal.** Most statements are normal, and the
  owner can't tell — saying "this part checks out, and here's how I checked"
  is half the product's value.
- **Questions, never accusations.** A negative gas line is a fact about the
  statement; whether it's *proper* depends on lease language you can't see.
  Frame every issue as a question for the operator, never as a claim of
  underpayment.

## What you're building toward

Three small JSON files and one artifact, with **all arithmetic done by the
bundled script — never by you**:

1. **`statement.json`** — the extraction (schema below; worked synthetic
   example in **`example.json`**).
2. **`public.json`** — state-reported volumes + benchmark prices, pulled with
   `run_sql`.
3. **`findings.json`** — the judgment layer: findings, questions, notes —
   written by you AFTER reading the script's `--facts` digest.
4. **`checkup_payload.py`** ties the extraction out against the statement's
   own printed totals and computes every rollup; its output fills
   **`StatementCheckup.jsx`** (the finished, frozen viewer — you do not
   build, redesign, or adapt it) as `DATA`/`TITLE`/`TLDR`.

## Workflow

1. **Read the statement.** Revenue statements are short (a few pages);
   read the upload directly in chat. Note the reporting platform
   (EnergyLink, Enverus, operator-native) — the layout varies, the content
   doesn't: properties × products × line items, then a check summary.
2. **Extract `statement.json`.** One entry per property; under it one entry
   per (product, production month); under that every line item with its
   amount **signed exactly as printed** (charges negative). **The trap that
   ruins extractions:** statements show two parallel sets of columns — the
   whole well ("Property Values", 8/8ths) and your share ("Owner Share").
   `property_volume`/`property_value` come from the first; `owner_volume`/
   `revenue`/`lines[].amount` from the second. Never mix them. Copy interest
   decimals with **every digit stated**. Capture the statement's own printed
   totals (`stated_net`, `stated_total`, the summary block) — they're what
   the script ties out against.
3. **Resolve the wells** with `run_sql`. Statements name wells, not APIs:
   ```sql
   SELECT well_api, well_name, operator, formation, first_prod_date, lateral_length_ft
   FROM public.wells
   WHERE state = 'CO' AND county = 'WELD' AND well_name ILIKE '%WHITETAIL FED%33-9%'
   ```
   Search by the name's distinctive tokens plus county/state; statements
   abbreviate, so loosen the pattern before concluding a well isn't there.
   The hits should account for the statement's property list — say which
   wells resolved and which didn't. **Never guess an API**; an unresolved
   well just gets no public columns.
4. **Pull public data** for the statement's production months (plus a month
   or two after, for the trend read):
   ```sql
   SELECT w.well_name, p.prod_date, p.oil_bbl, p.gas_mcf
   FROM public.production p JOIN public.wells w USING (well_api)
   WHERE p.well_api = ANY(ARRAY['05-123-52659', '...'])
     AND p.prod_date >= 'YYYY-MM-01'
   ```
   ```sql
   SELECT date_trunc('month', price_date)::date AS mo,
          round(avg(wti), 2) AS wti, round(avg(henry_hub), 2) AS henry_hub
   FROM market.spot_prices
   WHERE price_date >= 'YYYY-MM-01' AND price_date < 'YYYY-MM-01'
   GROUP BY 1
   ```
   Write `public.json`: `{"wells": [{property_id, well_api, well_name,
   formation, first_prod, lateral_ft, monthly: [{month: "YYYY-MM", oil_bbl,
   gas_mcf}]}], "benchmarks": [{month, wti, henry_hub}], "source_note": "..."}`.
   The `property_id` keys the join back to the statement — set it yourself,
   explicitly; the script does no fuzzy matching.
5. **Run the facts pass:**
   ```bash
   python3 checkup_payload.py statement.json --public public.json --facts
   ```
   Read the digest. If the tie-out fails, recheck your extraction against
   the statement first; a statement that genuinely doesn't reproduce its own
   totals is itself a finding.
6. **Write `findings.json`** — `{"findings": [{severity, title, body}, ...],
   "questions": ["..."], "notes": "..."}` — per the doctrine below, using
   only numbers from the digest.
7. **Emit the payload and build the artifact:**
   ```bash
   python3 checkup_payload.py statement.json --public public.json --findings findings.json > payload.json
   ```
   Fill `StatementCheckup.jsx`'s three slots: paste `payload.json` into
   `DATA`, write `TITLE` (operator + production month — "Bison IV — November
   2025 check") and `TLDR` (1–2 sentences: the overall verdict in plain
   English, leading with what's fine and naming what needs a look). Ship it
   as the artifact. The only dependency is `react` — don't add others.

**No code execution available?** Fall back honestly: do the same rollups by
hand, verify the tie-outs explicitly (line items → product net → property
total → check total; gross − taxes − deductions = net), build `DATA` in the
same shape, and say in `notes` that rollups were computed by hand.

## `statement.json` schema

```
statement:   kind, platform, operator, owner_name, owner_number,
             check_number, check_date ("YYYY-MM-DD"), check_amount,
             interest_type_guess, units_note
summary:     gross, taxes, deductions, non_revenue_deductions, net
             (the statement's own printed summary, signed as printed;
              omit the block if the statement has none)
properties:  [{property_id, well_name, state, county, stated_total,
              products: [{product ("OIL"|"GAS"|"CONDENSATE"|"PLANT PRODUCTS"|verbatim),
                          prod_month ("YYYY-MM"), unit ("BBL"|"MCF"|"GAL"),
                          price, property_volume, property_value,
                          owner_interest, distribution_interest,
                          owner_volume, revenue, stated_net,
                          lines: [{label (verbatim), amount (signed as printed),
                                   kind (optional "tax"|"deduction" — only when
                                   the label is ambiguous)}]}]}]
```

Missing → omit the key. The script classifies line labels itself (gathering,
processing, severance, ad valorem, ...) and warns in `--facts` about labels
it can't place — fix those with an explicit `kind`, don't rename the label.

## Doctrine — what normal looks like

- **Liquids volumes** (oil + condensate vs the state's oil, which includes
  condensate): per-well gaps of ±10% are normal sales-vs-production timing —
  the statement pays on barrels *sold*, the state records barrels *produced*.
  The pad-level total usually lands within a few percent.
- **Gas volumes**: statement gas 10–40% *below* the state's wellhead number
  is normal **when the statement also pays plant products** — the gap is
  plant shrink (the NGLs they're paid for separately) plus fuel. Explain the
  connection; don't alarm. Statement gas *above* the state number, below it
  by >40%, or below it with **no** NGL line → worth asking.
- **Prices**: DJ/Rockies oil realizes about WTI −$2–6; regional gas below
  Henry Hub is normal basis (Rockies often 10–25% under, plus BTU
  adjustment either way); condensate ≈ WTI −$8–15; NGLs per gallon × 42 ≈
  25–40% of WTI. Outside those bands → a question, not a conclusion.
- **Taxes**: expect roughly (of gross) CO 4–6%, TX 5–9%, WY 10–13%,
  ND 10–11%, NM 8–9%, OK 7–8% — severance + ad valorem combined, rough
  bands. Far outside → look closer.
- **Deductions**: anywhere from 0% (a no-deductions lease, or an oil-only
  well) to ~15% of gross (gas/NGL-heavy production). Over ~20%, or **any
  product netting negative**, is always a finding — deductibility turns on
  the lease's language, which you can't see, so it pairs with a question.
- **Decimals**: one owner in one unit usually shows one decimal on every
  line. Different decimals across wells can be legitimate (different
  tracts). `owner_interest ≠ distribution_interest` means suspense or an
  adjustment — worth knowing.
- **Young wells decline.** Check `first_prod_date`: wells in their first
  1–2 years decline steeply, so set the expectation — with the actual
  next-month state volumes you already pulled — that smaller future checks
  are geology, not a payment problem.
- **Negative volumes or amounts** on otherwise-normal lines are usually
  prior-period true-ups (price revisions, re-allocations) — explain as such.

## Findings doctrine

4–8 findings, each `{severity, title, body}`:

- `attention` — needs a look: negative product nets, tie-out failures,
  decimal drift, out-of-band deductions or prices. **Every attention
  finding pairs with an entry in `questions`** — specific enough to send
  as-is ("Does my lease permit deducting post-production costs...?").
- `info` — worth knowing: the shrink explanation, the decline expectation,
  anything true that a first-time reader would misread as a problem.
- `good` — checks that passed: volumes tie to state records, prices in
  band, decimal consistent. Say *how* it was checked in one clause.

Titles are plain and verb-y ("Gas earned less than it cost to move"), bodies
1–3 sentences with the dollars in them. Numbers in findings come from the
`--facts` digest — never computed in your head.

## Hard rules

- **Never fabricate.** Can't read a page or a number → say so; missing data
  → the module just doesn't render.
- **Property Values vs Owner Share — never mix the columns.**
- **Interest decimals are copied, never rounded.**
- **Never allege underpayment** from a variance the doctrine calls normal;
  lease-dependent items are framed as questions to the operator.
- **Never guess an API.**
- **All arithmetic in the script.** If a number isn't in the digest or the
  payload, it doesn't go in a finding.
- **This is informational, not legal, tax, or investment advice** — the
  viewer's footer says so; don't undercut it by giving legal conclusions.
- **The statement stays in the chat.** No persistence lane in this skill —
  don't upload or store the owner's statement anywhere.
