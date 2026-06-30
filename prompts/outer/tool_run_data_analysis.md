Publish a finished briefing you have already authored. YOU do the analysis with
run_sql, then hand this tool the complete briefing spec; the server validates it,
runs every widget's SQL to fill in the data, persists it, and renders it inline in
this chat. It returns a compact summary (headline, tldr, stripped sections) you
narrate from — the bulky chart/table data is fetched separately by the renderer.

This is a publishing step, not an investigator. There is no agent behind it and it
adds no analysis of its own — if you have not explored with run_sql yet, do that
first. Use it when the user wants a deliverable (a briefing/report/"show me X
across…") or the answer needs more than one chart or table.

Pass `spec`: a JSON object with
- `kind`: "briefing" (required, literally this string)
- `headline`: one-line title (required)
- `tldr`: one-sentence takeaway (required)
- `sections`: non-empty list of `{label, layout, widgets}` where `layout` is
  "full-width" | "2-col" | "3-col" and `widgets` is a non-empty list.

Widget types (`type`): `commentary` ({text, tone?}), `callout`
({label, code? | query?, value_template?}), `line_chart` / `bar_chart`
({label, query, series?}), `table` ({columns:[{key,label,align?}], query}).
Chart/table `query` strings are re-run server-side under the SQL guard at render
time — alias time-series columns as `x`/`y` (or use a `series` list), and bucket
to keep each query under 200 rows. Budget: ≤5 sections, ≤8 widgets.

If validation fails, the tool returns `{error, details}` (bad shape) or
`{error, widgets:[…]}` (a query failed to plan) in this same turn — fix the spec
and call run_data_analysis again. Nothing is consumed on failure.
