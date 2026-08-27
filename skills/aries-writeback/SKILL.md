---
name: aries-writeback
description: Use when the user wants Crude Code forecasts exported for ARIES — "send these curves back to ARIES", "give me an ARIES import package", "write our forecast into their deck". Builds a zip of CSVs (AC_ECONOMIC rows under a NEW qualifier, a PROPNUM crosswalk, and a step-by-step README) that an engineer appends to their own copy of the database. It never edits or produces a binary .accdb, and it never overwrites existing scenarios.
---

# ARIES Writeback

## What you're doing

The user has forecasts in Crude Code terms — usually the curves asserted in
this session's `deal_forecast_wells` run (their own independent forecast, or a
revised take on a seller's deck) — and wants them **in ARIES**. This skill
packages them as an **import package**: a zip of CSVs the target database's
engineer appends with ordinary MS Access import, under a **new qualifier**
so nothing existing is touched. Think of it as the reverse of
`aries-to-valuation`, with the same pinned conventions run backwards
(nominal-monthly → effective-annual).

This is v0 by design: **no binary is created or modified.** The deliverable
is rows plus instructions; the human does the import on a copy of their own
file. Say that plainly when handing it over.

## What you need

- **The curves, from this session.** You asserted them (or translated them)
  — you already hold `{qi, di, b}` per stream, the anchor, and the wells.
  Do not re-derive parameters from anywhere else.
- **Code execution** for the packaging script.
- **The target database's `_aries/` dir when available** (from the
  explorer's triage): it fills each well's PROPNUM by API and guards
  against reusing an existing qualifier. Without it, PROPNUMs the user
  can't supply ship as placeholders with join-on-API instructions.

## Workflow

1. **Write `curves.json`** (schema in `aries_package.py`'s docstring):
   qualifier (short, NEW — e.g. `CC2608`), and per well: `api`,
   `anchor_month`, `oil`/`gas` params exactly as committed via
   `deal_forecast_wells`, optional `cums` and `propnum`. Copy numbers verbatim —
   never round, never adjust.
2. **Build the package:**
   ```bash
   python3 aries_package.py curves.json --aries-dir _aries
   ```
   (`--aries-dir` whenever the target database was triaged this session.)
   Read the printed summary and notes.
3. **Hand the zip to the user** as a downloadable file, with a two-line
   explanation: it adds a new qualifier alongside their existing scenarios;
   the README inside walks their engineer through the Access append on a
   copy. Relay any PROPNUM-placeholder notes explicitly.
4. If the session also produced a valuation, remind the user which run the
   exported curves came from — the package and the deal sheet should tell
   the same story.

## Hard rules

- **New qualifier only, always.** The script refuses a qualifier that
  exists in the target database; never work around that.
- **Never edit parameters while packaging** — the zip carries exactly what
  was committed in the run. A change of mind means a new `deal_forecast_wells`
  pass first, then re-export.
- **Never fabricate a PROPNUM** — unknown ones ship as labeled
  placeholders with join instructions, and you tell the user.
- **All conversion in the script** (declines back to effective-annual per
  the pinned conventions in the explorer's ARIES.md) — never by hand.
- **Be honest about what this is**: an import package for their engineer
  to apply to a copy, not a modified database. If the user wants a
  ready-to-open `.accdb`, that's a server-side writer we haven't built —
  file it via `message_team` as a feature request.
