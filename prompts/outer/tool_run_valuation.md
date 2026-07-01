Run economics on the wells you've already forecast and build the deal sheet. Call
this AFTER `forecast_wells` — pass the same `run_id` it returned. `forecast_wells`
mints the `run_id` on the first call; thread that exact id into every later call.
`run_valuation` reads whatever forecast stages exist under the run, applies the
cashflow model, and returns risked PV plus the data to build an interactive
deal-sheet artifact from — see "Returns" below.

## REQUIRED: show the assumptions and get a yes before you run

A valuation is only as good as its inputs, and most of them have house defaults the
user never sees. Do NOT call `run_valuation` straight away. First:

1. **Resolve every input to an explicit value.** For each assumption below, use the
   user's number if they gave one, otherwise the house default from the **House
   defaults** table at the bottom of this doc. Compute the deal-specific pieces too
   (well counts by status from your `forecast_wells` result; the net capex check).
   For **price**, the house default is now the **live NYMEX strip** (oil + gas),
   not a flat number — show the price row as "NYMEX strip (most recent settle)"
   unless the user explicitly asks for a flat deck. Differentials still apply on
   top of the strip (realized = strip − diff).
2. **Show the assumptions grid in chat** (format below) and ask the user to confirm
   or change anything. Use plain-English labels — never the raw field names.
3. **Wait for the user.** If they change a value, re-show the affected row.
4. **Then call `run_valuation`, passing every value you showed — explicitly — in
   `params`.** Don't omit a field and let the engine re-default it; what you showed
   must be byte-for-byte what runs. (Passing a value equal to the house default is
   fine and expected.)

### The assumptions grid

A markdown table, one row per assumption, columns **Assumption · Value · Source**
(`Source` = "you" if the user supplied it, "house default" otherwise). Below the
table, always show:

- **Well counts by status** — e.g. `8 wells: 8 PUD (new drills), 0 PDP, 0 DUC`.
- **Capex check** — the full derivation so a unit error is obvious:
  `$9.93M / well × 8 new wells × 4.33% WI = $3.44M net`.

> **⚠ Zero-cost trap.** Drilling capex and operating cost both default to **$0**.
> If the deal has any non-producing wells (DUC/PUD) and capex is still $0, you are
> modeling **free wells** — PV will be wildly overstated. Call this out in plain
> language ("no drilling cost is modeled — set capex or PV is meaningless") and make
> the user choose a number before running.

### Capex basis — the one input that bites

`capex_per_well_usd` is the **gross, 100%, cost to drill + complete ONE single well**.
The engine multiplies it by the working interest itself. So:

- Do **NOT** pass a pad / multi-well AFE total. A 4-well-pad AFE of $39.73M is
  **$9.93M per well** ($39.73M ÷ 4) — pass the per-well number.
- Do **NOT** pre-multiply by WI. The engine does that. Pass the gross figure.

## `run_valuation(run_id, params)`

- `run_id: str` (REQUIRED) — the exact `run_id` returned by your `forecast_wells`
  call for THIS deal. Not a name you make up; copy it verbatim.

- `params: dict` (REQUIRED) — the authoritative deal terms. Every economic number
  comes from here. The shape is strict; fields are at the **top level of `params`**
  unless stated otherwise:

  - `interest_type`: `"wi"` or `"minerals"` — **a top-level string**, NOT nested
    inside `interest`. wi = pays costs; minerals = revenue × decimal only.
  - `interest`: an **object** (REQUIRED):
    - if `interest_type == "wi"`: `{"wi_pct": <0..1>, "nri_pct": <0..1>}`
    - if `interest_type == "minerals"`: `{"decimal": <0..1>}`
    - optional `"by_api"`: per-well overrides keyed by well API — each value is
      `{"wi_pct", "nri_pct"}` (wi) or a bare decimal (minerals). A well not listed
      uses the blanket interest above.
  - `asset_list`: an **object** (REQUIRED — not a list, not a string) with exactly
    ONE of:
    - `{"well_apis": ["<well_api>", ...]}` — explicit API list, or
    - `{"filter_sql": "<WHERE clause on public.wells>"}` — scope-by-criteria.
  - `economics_overrides`: an **object**. After the user confirms the grid, pass
    every assumption here explicitly (omit only `interest`/`asset_list`, which live
    above). Keys: `effective_date`, `price_deck` (defaults to the **live NYMEX
    strip** — `{"type":"strip"}`; pass `{"type":"flat","oil_usd_bbl","gas_usd_mmbtu"}`
    only to override with a flat deck), `oil_diff`, `gas_diff`, `discount_rates`
    (`{"PDP"?,"DUC"?,"PUD"?}` decimals), `forecast_horizon` (int months),
    `tax_pct`, `gpt_pct`, `opex_per_bbl_usd`, `opex_per_well_per_month_usd`,
    `capex_per_well_usd`, `months_to_first_prod` (`{"DUC"?,"PUD"?}` ints).

Complete example — copy this shape exactly:

```json
{
  "interest_type": "minerals",
  "interest": {"decimal": 0.0125},
  "asset_list": {"well_apis": ["30-015-36916", "30-015-36932"]},
  "economics_overrides": {"effective_date": "2026-07-01", "oil_diff": 2.50}
}
```

A working-interest deal instead looks like:

```json
{
  "interest_type": "wi",
  "interest": {"wi_pct": 0.75, "nri_pct": 0.5625},
  "asset_list": {"filter_sql": "operator = 'EOG' AND county = 'REEVES'"},
  "economics_overrides": {}
}
```

### Returns

`{"surface": "deal_sheet_artifact", "run_id", "data": {"facts", "production", "economics"}}`.

- `data.facts` — exec summary: `deal_type`, `interest`, `operator`, `area`.
- `data.production` — net monthly oil/gas/cashflow series over the deal's active
  window, or `null` when the deal has no active status yet to show.
- `data.economics.npv_at_centers` — the blended bottom line. `.total` is the
  headline PV; `.by_status` breaks it out by PDP/DUC/PUD. Narrate the result in
  chat from these numbers.

**Build a claude.ai artifact from `data`** — a single React component using only
`react`, `recharts`, and `lucide-react` (no other dependencies; this runs in the
claude.ai artifact sandbox, not your own app). Show the facts, the
production/forecast chart when `data.production` isn't `null`, and the
economics. Use only what's in `data` — don't omit a field you were given, and
don't invent numbers that aren't there. There's no fixed layout to follow;
use your judgment on how to present it well.

On a malformed `params` the tool returns `{"error": "..."}` naming the exact field
that's wrong (e.g. `interest_type must be 'wi' or 'minerals'`, `asset_list must be an
object`). The shape above is authoritative — fix the named field and call again; do
NOT start renaming or re-nesting other keys at random.

## House defaults

These are the values the engine uses when the user gives no number. Resolve the grid
from this table; show the **Label**, never the field name. (Kept in sync with the
engine by `tests/test_valuation_defaults_drift.py`.)

<!-- ei:econ_defaults:start -->
| Field | Label (show this) | House default | Raw |
|-------|-------------------|---------------|-----|
| oil_price | Oil price | $70.00 / bbl | 70.0 |
| gas_price | Gas price | $3.50 / MMBtu | 3.5 |
| oil_diff | Oil differential (off the deck) | $0.00 / bbl | 0.0 |
| gas_diff | Gas differential (off the deck) | $0.00 / MMBtu | 0.0 |
| tax_pct | Severance / production tax | 7.5% | 0.075 |
| gpt_pct | Gathering, processing & transport | 5.0% | 0.05 |
| opex_per_bbl_usd | Operating cost (per bbl) | $0.00 | 0.0 |
| opex_per_well_per_month_usd | Operating cost (per well / month) | $0.00 | 0.0 |
| capex_per_well_usd | Drilling capex (gross, per new well) | $0.00 | 0.0 |
| horizon_months | Forecast horizon | 360 months (30 yr) | 360 |
| duc_months_to_first_prod | DUC online timing | +18 months | 18 |
| permit_months_to_first_prod | Permit online timing | +36 months | 36 |
| discount_rate_pdp | Discount rate — producing (PDP) | 15% | 0.15 |
| discount_rate_duc | Discount rate — DUC | 20% | 0.20 |
| discount_rate_pud | Discount rate — permit (PUD) | 25% | 0.25 |
| rate_spread | Discount-rate band (± around each center) | ±2.5% | 0.025 |
| deck_oil_flat | Risked-cube flat oil decks (after Strip) | $70 / $75 / $80 | 70,75,80 |
<!-- ei:econ_defaults:end -->
