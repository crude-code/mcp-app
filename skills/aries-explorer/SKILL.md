---
name: aries-explorer
description: Use when the user uploads an ARIES database (.accdb / .mdb — Halliburton/Landmark reserves & economics software) or asks what's inside one. Read it with the bundled scripts, understand the properties, forecasts, and economic assumptions it carries, and build the explorer artifact so they can see the database. Standalone — not the dataroom flow and not a valuation.
---

# ARIES Explorer

## What you're doing

The user has an **ARIES database** — the Microsoft Access `.accdb`/`.mdb`
file behind an engineering shop's reserves and economics runs. It holds a
property list, production history, decline forecasts, and per-property
economic assumptions, all in ARIES's own table grammar. Your job is to
**read it, understand it, and show it**: open the binary with the bundled
scripts, decode what the database author set up, and build the explorer
artifact — the database's cover page.

This is NOT the dataroom flow and NOT a valuation. `dataroom-extract` is
for a document package headed to a bid; this is one database, read on its
own. The forecasts and economics inside are **the database author's
claims** — you are displaying them, never adopting them. If the user asks
what the assets are *worth*, that is the valuation flow
(`get_skill("well-forecasting")` → `forecast_wells`), which builds its own
forecasts from public data and never takes ARIES parameters as inputs.

## What you need

**Code execution is a hard requirement.** An Access file is binary — there
is no by-hand fallback. With no code execution available, say so honestly,
explain that reading an ARIES database needs the sandbox, and suggest the
user ask their engineer for CSV/Excel exports instead. Never pretend to
read the binary.

**`ARIES.md` (bundled) is the reference** — the complete table map, the
AC_ECONOMIC line grammar, units, escalation codes, stream numbers. Read it
before reading any dump; go back to it whenever a keyword or unit is
unfamiliar. Never guess at ARIES semantics the reference doesn't cover —
show the line verbatim instead.

## What you're building toward

One artifact, with **all arithmetic done by the bundled scripts — never by
you**:

1. **`aries_triage.py`** opens the database (it resolves its own reader:
   mdb-tools if installed, else `pip install access_parser`), inventories
   every table, and dumps the load-bearing ones to `_aries/tables/*.csv`.
2. **`aries_payload.py`** decodes the dumps — qualifiers, reserve
   categories, forecast sources, assumption clusters, lookup tables,
   integrity checks — and emits the payload plus a `--facts` digest.
3. **`notes.json`** — the judgment layer: 3–8 short observations written
   by you AFTER reading the digest.
4. **`AriesViewer.jsx`** is the finished, frozen viewer (you do not build,
   redesign, or adapt it); fill `DATA`/`TITLE`/`TLDR`. A worked payload is
   in **`example.json`**.

## Workflow

1. **Get the file into the sandbox.** If it arrived zipped, unzip it. An
   ARIES "database" is the single `.accdb`/`.mdb` file; sidecar `.laccdb`
   lock files are noise. Sidecar *exports* (a oneliner XLSX, a reserves &
   economics report PDF) often travel with it — skim them for context and
   cross-checks, but the database is the record you decode.
2. **Triage:**
   ```bash
   python3 aries_triage.py "<file>.accdb"
   ```
   If it exits asking for a backend, run `pip install access_parser` and
   retry. A connection/proxy failure on pip means the sandbox can't reach
   PyPI — tell the user, don't improvise a parser.
3. **Orient.** Read `_aries/triage.md`, then `_aries/manifest.json` if you
   need detail. What kind of database is this — how many properties, which
   core tables exist, how much production history, any warnings?
4. **Read the dumps frugally.** `_aries/tables/AC_PROPERTY.csv` end to end
   (it's the spine); a few properties' worth of `AC_ECONOMIC.csv` to see
   the house style; `ARLOOKUP.csv` template lines. The payload script does
   the systematic decode — your reading is for judgment, not transcription.
5. **Run the facts pass:**
   ```bash
   python3 aries_payload.py _aries --facts
   ```
   Read the digest: which qualifier was decoded (re-run with
   `--qualifier X` if the user cares about a different scenario), the
   reserve-category mix, where forecasts come from, the assumption
   clusters, what the integrity checks found.
6. **Write `notes.json`** — `{"notes": ["...", ...]}` — per the doctrine
   below, using only numbers from the digest.
7. **Emit the payload and build the artifact:**
   ```bash
   python3 aries_payload.py _aries --notes notes.json > payload.json
   ```
   Fill `AriesViewer.jsx`'s three slots: paste `payload.json` into `DATA`,
   write `TITLE` (deal or database name — "Bison IV ARIES database") and
   `TLDR` (1–2 sentences: what this database is and what to look at
   first). Ship it as the artifact. The only dependency is `react` — don't
   add others.

## Reading an ARIES database — doctrine

- **The qualifier is the scenario.** Every AC_ECONOMIC line belongs to a
  QUALIFIER; decoding mixes scenarios if you ignore it. The payload script
  decodes one (BASE by default) and lists the rest — say which one the
  viewer shows, and offer the others if several look substantive.
- **RESCAT is the author's claim, not a fact.** PDP/PUD/4LOC labels are
  how the engineer categorized the cases. Display them as given.
- **Forecasts live in three places**: explicit decline segments
  (`AC_FCST`), type-curve lookups (`LOOKUP` lines into `ARLOOKUP`), and
  rate lines in section 4. The payload names each property's source —
  "none" on a case that should have one is worth a note.
- **The `$/M` trap**: in section 5 it's dollars per MCF; in section 6 it's
  dollars per month. Same token, section decides. The reference's unit
  tables are the authority.
- **Ditto lines (`"`)** continue the previous keyword — multi-segment
  forecasts and stepped schedules read as one logical line.
- **`@M.field` references** resolve against that property's AC_PROPERTY
  row (e.g. `@M.LATERAL*3.6` scales a type curve by lateral length). Show
  them verbatim; the resolution is ARIES's job, not yours.
- **PROPNUM is ARIES-internal; API is the join to the world.** Wells with
  no API stay unresolved — never fabricate one, never join on a name
  without saying so.
- **Interest decimals are copied, never rounded** — same rule as every
  other Crude Code skill.

## Notes doctrine

3–8 plain-English notes, each one sentence or two, numbers from the digest
only:

- Lead with **what the database is**: the asset story in one line (basin,
  operator, case mix — "41 Haynesville cases: 28 PDP with history through
  2025-11, 13 PUDs on the TC_PROD type curve").
- Say **which scenario is decoded** and what the others are, when there is
  more than one qualifier.
- Surface **anything the integrity checks flagged**, in plain terms.
- Note what a reader should know before trusting the display: forecasts
  with no source, properties without APIs, price decks that look stale,
  a truncated dump.
- Frame observations about the author's assumptions neutrally — "flat
  $58.50 oil with no escalation" is a fact; "too optimistic" is a
  conclusion you don't draw here.

## Hard rules

- **Never fabricate.** Can't read a table or decode a line → say so; the
  module just doesn't render.
- **All arithmetic in the scripts.** If a number isn't in the digest or
  the payload, it doesn't go in a note.
- **Unknown keywords pass through verbatim** — never invent a decode.
- **Never guess an API** or an identity join.
- **The database is read-only.** Never write into the .accdb.
- **No persistence lane in this skill** — nothing is uploaded or stored;
  the database and everything derived from it stay in the chat.
- **Never adopt the database's forecasts or economics as your own** — not
  into a valuation, not into an answer about what something is worth.
  Offer the valuation flow separately if the user asks; it starts from
  public data, not from this file.
