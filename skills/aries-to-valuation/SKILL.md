---
name: aries-to-valuation
description: Use when the user explicitly asks to value the forecasts inside an ARIES database (.accdb/.mdb) — "what do the seller's curves say this is worth", "run their forecasts through our economics". Translates the section-4 decline curves into deal_forecast_wells assertions with full attribution, then the normal valuation flow runs unchanged. The deliverable is "seller's curves, Crude Code economics" — not a replay of their model and not our independent view.
---

# ARIES → Valuation

## What you're doing

The user has an ARIES database (already read via `aries-explorer`) and has
**explicitly asked to value the curves inside it**. This skill translates
the section-4 decline forecasts into `deal_forecast_wells` assertions —
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
   A well missing from `public.wells` cannot enter a run (`deal_forecast_wells`
   bounces it) — remove its entry, and tell the user which wells fell out
   and why. Never fabricate or force an API.
4. **Tie out against the oneliner when the room has one.** Extract per-well
   ultimates into `oneliner.json` —
   `{"<api>": {"ult_oil": bbl, "ult_gas": mcf, "life_yrs": yrs,
   "eff_offset_months": n}}`. **Get the life anchoring right**: the
   oneliner's LIFE column is measured from the EFFECTIVE date, so
   `eff_offset_months` = months from the forecast `START` to the effective
   date (START 01/2025, effective 08/2026 → 19). Then:
   ```bash
   python3 aries_curves.py _aries --qualifier <Q> --tieout oneliner.json
   ```
   Residuals beyond ~0.1% on capped wells: **check the life anchoring
   first** — a wrong offset or a misread life moves the shortest-lived
   wells the most (in either direction) while long-lived wells still round
   to 0.000%, which looks exactly like "a few wells failed." The per-well
   `[cap ...]` annotations make the caps auditable. Only after anchoring is
   ruled out, treat the residual as a broken translation: stop and
   investigate; never value on top of an unexplained residual. (Without
   `life_yrs` the comparison overshoots by the seller's econ-limit
   truncation — explained, not wrong.)
5. **Commit — machine-copied, never retyped.** Hand-typed parameters have
   corrupted in transit before (garbled digits inside rationale strings,
   qi values drifting). Print the entries with code execution —
   ```bash
   python3 -c "import json; print(json.dumps(json.load(open('forecast_payload.json'))['entries']))"
   ```
   — and paste that output verbatim as `deal_forecast_wells`' `forecasts`
   argument. You may drop wells (step 3); you may not edit numbers or
   rationale text. Read the echo. Expect stale-anchor warnings when the
   ARIES `START` predates recent actuals — that is the seller's timing,
   and the user must see it, not have it smoothed over.
6. **Verify the commit deterministically.** Mint
   `export_data(kind="parameters", run_id=...)`, curl the CSV in the
   sandbox, and diff the committed/asserted `qi`/`di`/`b` and anchor per
   well against `forecast_payload.json` in code — any drift means a
   transcription error: re-commit the affected wells straight from the
   payload and verify again. Do not proceed to valuation on an unverified
   commit.
7. **Confirm before valuing.** Present the assumptions grid as usual, PLUS
   the report's not-modeled items, each as a user decision:
   - **NGL yield** (bbl/mcf per well) — the engine has no NGL stream;
     revenue is understated by roughly that share of the deck.
   - **Shrink** — the engine models wellhead gas; realization rides the
     BTU factor and differentials (`gas_btu_factor` override is the lever).
   - **Water opex** (`OPC/WTR`) — not modeled; an `economics_overrides`
     opex adjustment is the blunt instrument if the user wants it.
   - **Tail policy** — the report quantifies ARIES-tail vs engine-tail
     volumes per stream; surface the package-level difference.
8. **Value:** `deal_valuation` as normal. The deal sheet's `TLDR` must lead
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
  `deal_valuation` — the coverage report is not optional reading.
- **Never present the output as what the seller's model said.** Their
  prices, costs, ownership, and econ-limit life were not used.
- **Never guess an API**; off-warehouse wells are reported, not forced.
- All arithmetic in the scripts; conversions never done by hand.
