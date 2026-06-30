# Widget palette

The widget vocabulary YOU use when authoring a briefing spec for `run_data_analysis`. Five widget types — pick the simplest shape that answers the question.

## `commentary`
Your prose voice. One or two short paragraphs, ≤80 words each.
Args: `text` (required), `tone="neutral|bullish|bearish|warning"` (optional).

## `callout`
A labelled stat. Two flavors:
- **By code:** `callout("WTI Crude", code="WTI_USD")` — server fills value/delta/sparkline from `market.spot_prices`. Codes: `WTI_USD`, `BRENT_CRUDE_USD`, `NATURAL_GAS_USD`.
- **By query:** `callout("Permian rigs", query="SELECT count(*) AS count FROM ...", value_template="{count} rigs")` — query must return one row; `value_template` is a Python f-string-style template referencing column names.

## `line_chart`
Time series. `line_chart(label, query=...)`. Query must alias columns as `x` and `y` (single-series), or use multiple keys + a `series` list (multi-series, max 4).

## `bar_chart`
Rankings as bars. Same shape as `line_chart`. Add `orientation="horizontal"` for long category labels.

## `table`
Rows + columns. MUST supply `columns` array (`{key, label, align}`). `query` returns rows whose keys match column `key`s.

## When to use what

- Short factual question — one `callout`.
- Trend question — `callout` snapshot row + `line_chart`.
- Ranking question — `callout` row + `table` (or `bar_chart` if visual impact matters).
- Investigative — `commentary` thesis → chart → table → `commentary` closer.

## Layouts

Section `layout` is one of:
- `full-width` — widgets stacked, each full-width.
- `3-col` — three widgets side-by-side. Intended for callout rows.
- `2-col` — two widgets side-by-side.

## Canvas constraints

Both render inline in the chat thread, in an iframe that is **~736px
wide**. After wrapper padding the content area is **~640px**. Per-widget
widths work out to:

- `full-width` — ~640px
- `2-col` — ~315px each
- `3-col` — ~205px each

Pick a layout that fits the widget's content shape:

- **`callout`** — fine at any width. `3-col` rows of callouts are the
  intended use.
- **`line_chart`** — 1-2 series fit in `2-col`; 3+ series need
  `full-width` to stay legible.
- **`bar_chart`** — horizontal orientation needs `full-width` or `2-col`;
  vertical bars work in `2-col`. `3-col` is too narrow for any bar chart
  with category labels.
- **`table`** — ≤3 columns OK at `2-col`; 4+ columns or long string
  values (operator names, headlines) need `full-width`. Never put a
  table in `3-col`.
- **`commentary`** — anywhere.

When in doubt, prefer wider. A `full-width` table beats a squeezed
`2-col` table that wraps every cell.

## Bucketing for chart queries

Keep each chart's row count low (target 30–100, hard cap 200):
- < 90 days of daily data → daily rows
- 90 days – 2 years → weekly via `date_trunc('week', ...)`
- 2+ years → monthly via `date_trunc('month', ...)`

## Budget

Per briefing: ≤5 sections, ≤8 widgets total, ≤150 words across all
`commentary` widgets. Short and opinionated beats comprehensive.
