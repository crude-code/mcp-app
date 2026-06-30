Queries the Crude Code oil & gas warehouse via SELECT. Covers `public`
(wells, production), `market` (spot_prices, benchmark_prices, futures,
weekly_supply, news_feed, steo_forecasts), `financials` (operators,
income, balance_sheet, cash_flow, reserves, operator_production, facts,
operator_aliases), `shapes` (townships, sections, landtrac_units,
landtrac_unit_wells). Read-only, single statement, no DDL/DML.

This is your primary exploration tool. Use it liberally to ground
questions, sanity-check numbers, and frame a thesis before you publish a
briefing or value a deal. Fully-qualify across schemas, or pass `schema=`
to switch the default.

The well identifier column is **`well_api`** (text) on both `public.wells`
and `public.production` — never `api`, `uwi`, or `api_uwi` (`api_uwi` exists
only on `shapes.landtrac_unit_wells`). Join production to wells on `well_api`.

Caps: 50 rows / 50 KB / 5s. The cap is tight on purpose — chat-visible
results need to be presentable. Use `LIMIT` plus aggregation; don't
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

When the user wants a deliverable (multi-widget artifact, chart,
narrative): once you've explored and have a thesis, author the briefing
spec yourself and publish it with `run_data_analysis(spec)` — you write the
sections/widgets; each chart/table carries a SQL query the server re-runs.
For a deal valuation, call `forecast_wells(groups)` to classify and forecast
the wells, then call `run_valuation(run_id, params)`. There is no separate analyst
agent to delegate to — you do the analysis and hand over a finished spec.
