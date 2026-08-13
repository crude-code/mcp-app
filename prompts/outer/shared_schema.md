# Database Schema

All tables live on the Crude Code Postgres database.

## Allowed Schemas

<!-- cc:schemas:start -->
- `public` — well data (wells, production, operators)
- `market` — commodity prices, futures, news, weekly supply, STEO forecasts
- `financials` — SEC-derived operator financials (income, balance_sheet, cash_flow, reserves, operator_production)
- `features` — pre-computed development cohorts: pads/rows of co-developed wells with group rollups and parent/infill context (cohorts, subcohorts, well_assignments, parent_wells). The fastest path to "which pad is this well on" and "find analogous pads". DJ basin only today.
- `shapes` — PLSS geometry (townships, sections) and LandtracUnit polygons (landtrac_units, landtrac_unit_wells). **Exploration only** — `shapes.*` cannot appear in a `map` layer query, only in `run_sql`.
<!-- cc:schemas:end -->

Other schemas (`dataroom`, `platform`, etc.) are not accessible. Always qualify tables with the schema prefix (`market.spot_prices`, not `spot_prices`).

## public.wells
Master well table. One row per well.
```
well_api: text PK          -- API number
well_name: text            -- Operator's well/lease name (e.g. "MOJACK 14-2HZ"); may be NULL
state: text
county: text
basin: text
operator: text
well_status: text          -- PRODUCING, PERMITTED, DUC
trajectory: text
formation: text            -- Target formation
section: text
township: text
range: text
spud_date: date
completion_date: date
first_prod_date: date
tvd_ft: integer            -- True vertical depth (feet)
md_ft: integer             -- Measured depth (feet)
lateral_length_ft: integer -- Lateral length (feet)
perf_interval_ft: integer  -- Perforated interval (feet)
total_fluid_bbl: integer   -- Total frac fluid (barrels)
total_proppant_lbs: integer -- Total proppant (pounds)
frac_stages: integer
geom: geometry             -- PostGIS point geometry
```

## public.production
Monthly production volumes. Join to wells on well_api.
```
well_api: text PK
prod_date: date PK         -- First of month
prod_month: integer        -- Per-well counter: 1 = the well's first producing month. NOT a calendar index — filter calendar time with prod_date
oil_bbl: integer           -- Oil (barrels)
gas_mcf: integer           -- Gas (mcf)
boe: integer               -- Barrels of oil equivalent
```

**The well identifier column is `well_api`** — on both `public.wells` and
`public.production`. It is never `api`, `uwi`, or `well_id`. (`api_uwi` exists
only on `shapes.landtrac_unit_wells`, the Landtrac bridge — it joins to
`public.wells(well_api)`.) When in doubt, the column is `well_api`.

**Query patterns that beat the 5-second cap.** `public.production` is ~12M
rows and `public.wells` ~220K; two natural first queries time out every
time, and both have a fast form:

- **Never join `production` against a broad well filter** (a basin, an
  operator, a status). `wells JOIN production WHERE basin = …` aggregates
  millions of rows and dies. Narrow first — a CTE selecting the specific
  `well_api`s (a spatial hit list, a `LIMIT`ed top-N), then join production
  to the CTE. For operator-level production trends, skip the join entirely:
  `financials.operator_production` is already aggregated.
- **Spatial filters need a bounding-box prefilter.** `ST_DWithin` on
  `geom::geography` alone cannot use the spatial index (it's on the
  geometry) — ~60s. Pair it with an indexed box, expanded ~0.025° per mile
  of radius, and it drops under a second:

      FROM public.wells w,
           (SELECT geom FROM public.wells WHERE well_api = '…') s
      WHERE w.geom && ST_Expand(s.geom, <radius_mi> * 0.025)
        AND ST_DWithin(w.geom::geography, s.geom::geography, <radius_mi> * 1609)

## features.well_assignments
The bridge into the cohort layer: which development cohort (pad/row) each
well belongs to. DJ basin only today — a well with no row here is either
outside the DJ or unassigned.
```
well_api: text             -- joins public.wells / public.production
unit_id: text
cohort_id: text            -- joins features.cohorts
subcohort_id: text         -- joins features.subcohorts
```

## features.cohorts
**The pad table.** Co-developed well groups — wells drilled and turned online
together (a pad, a row, a unit's development phase) — pre-computed with
group-level rollups. For "which pad is this well on", "read the pad as one
stream", or "find analogous pads nearby", join here via `well_assignments`
instead of re-deriving pads by operator/date clustering. One row per cohort:
- identity & timing — `cohort_id`, `unit_id`, `cohort_anchor_month`,
  `sub_seq`, `well_count`, `span_start`/`span_end`/`span_days`
- who & what — `primary_operator`, `operators[]`, `formations[]`
- geometry — `cohort_footprint_acres`, `geom_coverage_pct`,
  `modal_lateral_azimuth_deg`, `azimuth_dispersion_deg`,
  `median_lateral_length_ft` (+ `lateral_length_p10_ft`/`_p90_ft`)
- production rollups — `cum_oil_bbl`, `cum_gas_mcf`, `cum_boe`,
  `cum_boe_6mo`/`_12mo`/`_24mo`, `peak_month_boe`, `peak_month_date`,
  `months_online`, `latest_prod_month`, `recent_rate_boepd`
- parent / infill context — `is_infill`, `parent_count` (+ `_same_unit`,
  `_spatial_only`, `_horizontal`, `_vertical` variants),
  `earliest_parent_first_prod`, `years_since_nearest_parent`,
  `parent_cum_oil_at_anchor`, `parent_cum_boe_at_anchor`,
  `active_parent_count_at_anchor`, `parent_rate_boepd_at_anchor`

## features.subcohorts
A cohort sliced by formation, with completion-design stats — the analog
filters (lateral band, proppant/fluid per foot, stages, spacing) served
pre-computed. Columns: `subcohort_id`, `cohort_id`, `formation`,
`well_count`, spacing percentiles (`intra_spacing_p10/p50/p90_ft`), lateral
and design percentiles (`median_lateral_length_ft`,
`median_proppant_lbs_per_ft`, `median_fluid_bbl_per_ft`, `median_stages`,
`median_tvd_ft`, each with p10/p90), `completion_data_coverage_pct`, the
same production rollups as cohorts, and same-formation parent context
(`same_fm_parent_count`, `same_fm_parent_cum_oil_at_anchor`, …).

## features.parent_wells
Per-cohort parent list — the wells that pre-dated the cohort and bound its
infill behavior.
```
cohort_id: text            -- joins features.cohorts
parent_well_api: text      -- joins public.wells
formation: text
first_prod_date: date
months_before_cohort_anchor: integer
orientation: text
operator: text
relationship: text
distance_to_cohort_hull_ft: integer
```

## market.spot_prices
Daily WTI, Brent, and Henry Hub spot prices. **This is the only price history table to use.**
```
price_date: date PK
wti: numeric         -- $/bbl
brent: numeric       -- $/bbl
henry_hub: numeric   -- daily Henry Hub natural gas close ($/MMBtu)
```
Populated back to 1986. Some older rows may have NULL henry_hub or brent — filter with `WHERE <col> IS NOT NULL` when querying that commodity.

## market.benchmark_prices
Monthly benchmark price averages — WTI and Henry Hub. One row per month.
```
price_month: date PK   -- First of month
wti_price:   numeric   -- $/bbl
gas_price:   numeric   -- $/MMBtu (Henry Hub)
```
Different cadence from `market.spot_prices` (daily). Use `spot_prices` for daily closes, `benchmark_prices` for monthly averages.

## market.futures
Oil and gas forward price curves.
```
contract_month: date PK    -- Delivery month of the contract (first day of month)
trade_date:     date PK    -- Trading day the curve was observed
oil_price:      numeric    -- WTI settle for that contract on that day
gas_price:      numeric    -- Henry Hub settle for that contract on that day
```
Daily cadence on `trade_date`. Filter `contract_month >= (SELECT MAX(trade_date) FROM market.futures)` for forward contracts only.

## market.weekly_supply
EIA weekly U.S. petroleum supply data.
```
week_date: date PK
crude_stocks_mmbbl: numeric    -- Million barrels
stock_change_mmbbl: numeric    -- Week-over-week change
refinery_util_pct: numeric     -- Percent
refinery_inputs_mbpd: numeric  -- Thousand bbl/day
production_mbpd: numeric       -- U.S. field production
imports_mbpd: numeric
exports_mbpd: numeric
product_supplied_mbpd: numeric -- Petroleum products supplied
```

## market.steo_forecasts
EIA Short-Term Energy Outlook forecasts.
```
period: date PK
series_id: text PK         -- e.g. COPR_US, BREPUUS, WTIPUUS, NGHHUUS, PAPR_WORLD, PATC_WORLD, COPS_OPEC
value: numeric
unit: text
```

## market.news_feed
Curated oil & gas news with AI-generated insights.
```
id: integer PK
category: text             -- 'news', 'sec', 'public_data'
source: text               -- oilprice, rigzone, eia, worldoil, shalemag, boereport
title: text
url: text UNIQUE
summary: text
published_at: timestamptz
rank: integer              -- 1-5 (top curated stories), NULL if not ranked
insight: text              -- AI-generated one-liner
tags: text[]               -- topic tags
fetched_at: timestamptz
```

## financials.operators
Public-company operators tracked from SEC filings. ~70 rows (E&P, midstream, oilfield services).
```
cik: text PK              -- SEC Central Index Key
ticker: text              -- Stock ticker (e.g. EOG, FANG, COP)
entity_name: text         -- Filed legal entity name
```
Join to all other `financials.*` tables on `cik`. Most analyst questions are framed by ticker — join through this table to translate.

> **Note:** `financials.income`, `financials.balance_sheet`, `financials.cash_flow`, `financials.reserves`, and `financials.operator_production` are materialized views over `financials.facts`.

## financials.income
Income statement, one row per operator per fiscal period. PK `(cik, fiscal_year, fiscal_period)`. FY2009 → FY2026.
```
cik: text                  -- joins to financials.operators
period_end: date           -- last day of the fiscal period
fiscal_year: smallint
fiscal_period: text        -- 'FY' annual, 'Q1' / 'Q2' / 'Q3' quarterly
form: text                 -- SEC form ('10-K', '10-Q')
revenue: float
oil_gas_revenue: float     -- Combined oil+gas+NGL stream (where reported as one)
oil_revenue: float
gas_revenue: float
ngl_revenue: float
total_costs: float
operating_income: float
pretax_income: float
net_income: float
eps_diluted: float
eps_basic: float
dda: float                 -- Depreciation, depletion & amortization
interest_expense: float
income_tax: float
exploration_expense: float
```
All dollar fields are reported in the operator's filing units (typically USD millions). Filter `WHERE fiscal_period = 'FY'` for annual-only comparisons.

## financials.balance_sheet
Balance sheet. PK `(cik, fiscal_year, fiscal_period)`. FY2009 → FY2026.
```
cik, period_end, fiscal_year, fiscal_period, form
cash: float
current_assets: float
current_liabilities: float
total_assets: float
ppe_net: float             -- Property, plant & equipment net
accounts_receivable: float
accounts_payable: float
long_term_debt: float
short_term_debt: float
stockholders_equity: float
retained_earnings: float
goodwill: float
aro: float                 -- Asset retirement obligations
```

## financials.cash_flow
Cash flow statement. PK `(cik, fiscal_year, fiscal_period)`. FY2009 → FY2026.
```
cik, period_end, fiscal_year, fiscal_period, form
cfo: float                 -- Cash from operations
cfi: float                 -- Cash from investing
cff: float                 -- Cash from financing
total_capex: float
dividends_paid: float
share_buybacks: float
debt_issuance: float
debt_repayments: float
```
Free cash flow is not a stored column — compute as `cfo - total_capex`.

## financials.reserves
Proved reserves. PK `(cik, fiscal_year, fiscal_period)`. FY2009 → FY2026. Reserves are typically reported annually only — most rows have `fiscal_period = 'FY'`.
```
cik, period_end, fiscal_year, fiscal_period, form
proved_reserves_mcf: float    -- Total proved reserves, **mcf-equivalent units**
proved_developed: float       -- Proved developed
proved_undeveloped: float     -- Proved undeveloped
```
**Unit caveat:** `proved_reserves_mcf` is in mcf-equivalent (one column for the rolled-up reserve number). For Mboe, divide by ~6 (gas-to-oil energy equivalence) — but verify with the operator's 10-K when precision matters. Reserve roll-forward fields (extensions, revisions, purchases/sales) are not currently materialized.

## financials.operator_production
Operator-reported production volumes. PK `(cik, fiscal_year, fiscal_period)`. FY2009 → FY2026.
```
cik, period_end, fiscal_year, fiscal_period, form
oil_production_bbl: float    -- Oil (barrels — NOT thousands)
gas_production_mcf: float    -- Gas (mcf — NOT mmcf)
ngl_production_bbl: float    -- NGL (barrels)
```
**Unit caveat:** raw barrels and mcf, not thousands or millions. To get Mboe: `(oil_production_bbl + gas_production_mcf/6 + ngl_production_bbl) / 1000`.

## financials.operator_aliases
Maps state-reported operator names to SEC CIKs. Used to bridge `wells.operator` (free-text) to `financials.*` tables (CIK-keyed).
```
alias_name: text PK    -- normalized uppercase alias
cik:        text FK → financials.operators(cik)
source:     text       -- 'auto' (regenerated each EDGAR run) | 'manual' (curated)
added_at:   timestamptz
```

## shapes.townships
PLSS township polygons. One row per township.
```
id: integer PK
state_abbr:    varchar
township_no:   varchar
township_dir:  varchar       -- N / S
range_no:      varchar
range_dir:     varchar       -- E / W
meridian:      varchar
display_name:  varchar       -- e.g. "T3N R1W"
plss_id:       varchar
geom:          geometry      -- PostGIS polygon
```

## shapes.sections
PLSS section polygons. One row per section. Many sections per township.
```
id: integer PK
township_id:    integer FK → shapes.townships(id)
section_number: varchar
plss_id:        varchar
geom:           geometry     -- PostGIS polygon
```

## shapes.landtrac_units
LandtracUnit lease polygons. One row per unit.
```
unit_id:          text PK
unit_name:        text
state:            text
county:           text
area_acres:       numeric
instrument:       text          -- Lease instrument type
primary_interval: text          -- Target interval / formation
current_operator: text
env_basin:        text
env_play:         text
submission_date:  date
geom:             geometry      -- PostGIS polygon
```

## shapes.landtrac_unit_wells
Wells assigned to each LandtracUnit. Bridge table.
```
unit_id: text   -- joins to shapes.landtrac_units(unit_id)
api_uwi: text   -- joins to public.wells(well_api) — note the column name differs
```
