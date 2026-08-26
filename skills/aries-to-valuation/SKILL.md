---
name: aries-to-valuation
description: Use when the user explicitly asks to value the forecasts inside an ARIES database (.accdb/.mdb) — "what do the seller's curves say this is worth", "run their forecasts through our economics". Translates the section-4 decline curves into forecast_wells assertions with full attribution, then the normal valuation flow runs unchanged. The deliverable is "seller's curves, Crude Code economics" — not a replay of their model and not our independent view.
---

# ARIES → Valuation

## What you're doing

The user has an ARIES database (already read via `aries-explorer`) and has
**explicitly asked to value the curves inside it**. This skill translates
the section-4 decline forecasts into `forecast_wells` assertions —
adopted-with-attribution, every rationale carrying the verbatim ARIES line —
and the normal valuation flow runs unchanged from there.

The result is a **third number** with its own name: *the seller's curves
under Crude Code economics*. It is not a replay (their prices, costs, and
econ-limit life are never used) and it is not our view (no independent
forecast was made). Say this plainly, label the deal sheet with it, and
offer the natural comparison — our own `well-forecasting` pass on the same
wells — as the follow-up.

**Routing:** reading/exploring the database → `aries-explorer`. An
independent valuation → `well-forecasting`. This skill only when the user
asks for the database's own curves in a valuation, in their own words.

## What you need

- **Code execution** (hard requirement, same as the explorer).
- **The `_aries/` directory** from the explorer's `aries_triage.py`. If it
  isn't in the sandbox yet, fetch `aries-explorer` and run triage first.
- The translation math rides on the **pinned conventions** in the
  explorer's `ARIES.md` (declines are effective-annual; the engine wants
  nominal-monthly). `aries_curves.py` implements them — verified against a
  real database's own oneliner to ≤0.013% per stream. Never convert by hand.

## Workflow

1. **Confirm the lane.** The user asked to value the seller's curves —
   restate what that means (their volumes, our prices/costs/discounting)
   in one sentence before starting.
2. **Translate:**
   ```bash
   python3 aries_curves.py _aries --qualifier <Q>
   ```
   (qualifier defaults to BASE, else the most-used; say which was decoded).
   This writes `forecast_payload.json` and prints the coverage report.
   **Read the whole report** — it is the contract of what did and did not
   translate.
3. **Resolve the wells.** Check every payload API against the warehouse:
   ```sql
   SELECT well_api, well_name, operator FROM public.wells
   WHERE well_api = ANY(ARRAY['42-227-41093', ...])
   ```
   A well missing from `public.wells` cannot enter a run (`forecast_wells`
   bounces it) — remove its entry, and tell the user which wells fell out
   and why. Never fabricate or force an API.
4. **Tie out against the oneliner when the room has one.** Extract per-well
   ultimates into `oneliner.json` —
   `{"<api>": {"ult_oil": bbl, "ult_gas": mcf, "life_yrs": yrs,
   "eff_offset_months": months from forecast START to the effective date}}` —
   then:
   ```bash
   python3 aries_curves.py _aries --qualifier <Q> --tieout oneliner.json
   ```
   Mean residual beyond ~0.1% means the translation is wrong — **stop and
   investigate; do not value on top of a broken translation.** (Without
   `life_yrs` the comparison overshoots by the seller's econ-limit
   truncation — that residual is explained, not wrong.)
5. **Commit:** call `forecast_wells` with the payload's entries verbatim.
   Do not edit translated parameters; you may only drop wells (step 3).
   Read the echo. Expect stale-anchor warnings when the ARIES `START`
   predates recent actuals — that is the seller's timing, and the user
   must see it, not have it smoothed over.
6. **Confirm before valuing.** Present the assumptions grid as usual, PLUS
   the report's not-modeled items, each as a user decision:
   - **NGL yield** (bbl/mcf per well) — the engine has no NGL stream;
     revenue is understated by roughly that share of the deck.
   - **Shrink** — the engine models wellhead gas; realization rides the
     BTU factor and differentials (`gas_btu_factor` override is the lever).
   - **Water opex** (`OPC/WTR`) — not modeled; an `economics_overrides`
     opex adjustment is the blunt instrument if the user wants it.
   - **Tail policy** — the report quantifies ARIES-tail vs engine-tail
     volumes per stream; surface the package-level difference.
7. **Value:** `run_valuation` as normal. The deal sheet's `TLDR` must lead
   with the label: *"Seller's ARIES curves (qualifier <Q>) under Crude Code
   economics."* Then offer the comparison: an independent
   `well-forecasting` pass on the same wells, same economics — that
   two-run diff is usually what the user actually wants.

## Hard rules

- **Explicit request only.** Nobody gets seller curves valued by default.
- **Never edit a translated parameter; never approximate an untranslatable
  curve.** A stream that doesn't match the proven line shape is refused
  with its verbatim lines in the report — relay it, don't guess it.
- **Rationales keep the verbatim ARIES lines and the attribution.** They
  are the never-adopt boundary made visible in the deal sheet's evidence.
- **Nothing silent.** Every refused well or stream, every unmodeled
  construct (NGL, shrink, water, tail policy), reaches the user before
  `run_valuation` — the coverage report is not optional reading.
- **Never present the output as what the seller's model said.** Their
  prices, costs, ownership, and econ-limit life were not used.
- **Never guess an API**; off-warehouse wells are reported, not forced.
- All arithmetic in the scripts; conversions never done by hand.
