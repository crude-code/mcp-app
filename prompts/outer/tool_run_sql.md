Queries the Crude Code oil & gas warehouse via SELECT. Read-only, single
statement, no DDL/DML. **The complete schema reference — every table,
column, join key, and unit caveat — is in the Database Schema section at
the end of this description.** It is the only schema documentation you
receive; do not guess column semantics that are defined there.

This is your primary exploration tool. Use it liberally to ground
questions, sanity-check numbers, and frame a thesis before you build a
deliverable or value a deal. Fully-qualify across schemas, or pass `schema=`
to switch the default.

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
For a deal valuation, fetch `get_skill("well-forecasting")` and follow it:
you read the wells' histories here with `run_sql`, assert each well's
decline parameters via `forecast_wells`, then `run_valuation(run_id,
params)` — its response carries both the deal `data` and the frozen
deal-sheet template to build the artifact from. You do the analysis; there
is no analyst agent to delegate to.
