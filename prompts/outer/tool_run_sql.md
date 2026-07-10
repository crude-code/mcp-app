Queries the Crude Code oil & gas warehouse via SELECT. Covers `public`
(wells, production), `market` (spot_prices, benchmark_prices, futures,
weekly_supply, news_feed, steo_forecasts), `financials` (operators,
income, balance_sheet, cash_flow, reserves, operator_production, facts,
operator_aliases), `shapes` (townships, sections, landtrac_units,
landtrac_unit_wells). Read-only, single statement, no DDL/DML.

This is your primary exploration tool. Use it liberally to ground
questions, sanity-check numbers, and frame a thesis before you build a
deliverable or value a deal. Fully-qualify across schemas, or pass `schema=`
to switch the default.

The well identifier column is **`well_api`** (text) on both `public.wells`
and `public.production` — never `api`, `uwi`, or `api_uwi` (`api_uwi` exists
only on `shapes.landtrac_unit_wells`). Join production to wells on `well_api`.

Caps: 200 rows / 100 KB / 5s. The cap exists because rows land in chat context — pre-aggregate (monthly, top-N) rather than paging through raw data. Use `LIMIT` plus aggregation; don't
SELECT * a table and skim. For ranking, ORDER BY + LIMIT 10. For
distributions, bucket and count.

Arguments:
- `sql: str` — the query.
- `schema: str = "public"` — default schema for unqualified names.

Returns `{rows: [...], count: int}` or `{error: "..."}`. Rows are JSON
objects keyed by column.

How to use the results in chat:
- Summarize the finding in one or two sentences. Cite the numbers.
- For ranking/list questions, format the rows as a markdown table.
- Don't paste raw JSON. The user reads your synthesis, not the dump.
- For follow-ups answerable from rows you already pulled, answer from
  context — don't re-call.

When the user wants a deliverable (a chart, a report, a document to keep):
explore until you have a thesis, pull the final series with focused,
pre-aggregated SELECTs, and build a claude.ai artifact from those rows.
For a deal valuation, call `forecast_wells(groups)` to classify and forecast
the wells, then `run_valuation(run_id, params)` — its response carries both
the deal `data` and the frozen deal-sheet template to build the artifact
from. You do the analysis; there is no analyst agent to delegate to.
