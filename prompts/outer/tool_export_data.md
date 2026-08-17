Hand the user a file of work you've already done — a CSV, or a zip of several.
Returns a download link — print it in chat and let them click it. Never fetch
the link yourself: the whole point is that the bytes go to the user's disk
instead of your context window.

**kind** — what to export:

- `bundle` — the generous default for a finished valuation: a zip carrying
  `wells_monthly.csv` (one row per well per month with volumes *and* every
  cashflow line item — gross_rev, net_rev, sev_tax, gpt, capex, opex,
  net_cashflow), `parameters.csv`, and a README explaining both. Offer this
  when the user wants the deal's numbers rather than one specific slice —
  they can keep whichever columns they need. Needs `run_id`; the run must
  have been through `run_valuation`.
- `volumes` — monthly oil and gas by well, over the run's full economic
  horizon (360 months by default). Gross physical volumes (`oil_bbl`,
  `gas_mcf`, before any interest) plus net volumes scaled by each well's
  revenue interest. One row per well per month. Needs `run_id`; the run must
  have been through `run_valuation`.
- `parameters` — the committed decline curves, one row per well per stream:
  qi (as committed *and* as asserted), Di, b, terminal decline, the terminal
  switch month, the anchor month, uptime factor, and the rationale. This is
  the reproducibility record for a forecast. Needs `run_id`; the run must
  have been through `forecast_wells`.
- `query` — a `run_sql` SELECT re-run at export scale (100,000 rows instead
  of the 200-row chat cap). Same guard stack, same schema allowlist. Needs
  `sql`. Use this for actual production history, well headers, anything the
  user wants to keep rather than read.

**When to offer it.** When the user says they want to keep, load, or work
with the data elsewhere — a database, a spreadsheet, their own model. Offer
once; don't push it. Analysis stays in chat, where you can interpret it.

**What it is not.** A recurring data feed. Each export is a file produced by
a session you did the work in, and the link expires. If a user wants
forecasts refreshed on a schedule across a large well set, that isn't a
bigger export — it's a different product, and the honest answer is that the
engineering has to happen per run. Say so plainly rather than working around
it.

Returns `{download_url, filename, kind, expires_in_hours}`. Give the user the
URL and tell them what's in the file and roughly how big it is. If the run
isn't far enough along to export (no forecast, no economics), the tool says
so — run the missing step first.
