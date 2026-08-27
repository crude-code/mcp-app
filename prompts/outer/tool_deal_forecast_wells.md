Commit production forecasts you have engineered. You assert the decline
parameters; the server validates sanity bounds, saves, and echoes the
consequences of what you committed. It never chooses a parameter — the
judgment is yours. **Before your first forecast on a deal, call
`get_skill("well-forecasting")` and follow it** — it is the procedure this
tool assumes (reading the history, striking contamination, sourcing b from
the population, the uptime factor, timing for undrilled wells). Pull the
evidence yourself with `run_sql` (its docstring carries the schema).

Pass `forecasts`: a list of entries, each one well or one cohort:

```json
{
  "wells": ["05-123-45678"],
  "oil":  {"qi": 4300, "di": 0.056, "b": 1.1},
  "gas":  {"qi": 11800, "di": 0.050, "b": 1.2},
  "anchor_month": "2026-05",
  "uptime_factor": 0.96,
  "struck_months": ["2025-11", "2026-02"],
  "rationale": "…",
  "analog_cohort": {
    "curve_label": "Wolfcamp A · 10,000 ft",
    "criteria": "Wolfcamp A · 8–12k ft lateral · first prod 2019+ · within 3 mi",
    "kept": ["42-389-…", "42-389-…"],
    "excluded": [{"api": "42-389-…", "reason": "different formation"}]
  }
}
```

Each entry is also one **evidence unit** on the deal sheet `deal_valuation`
builds: an individual well becomes a history-vs-curve panel, a cohort
becomes one summed panel, and entries carrying an `analog_cohort` become a
type-curve panel showing the cohort behind the curve. Triage accordingly —
wells that carry the value get individual entries; the low-value tail
aggregates (per the skill).

- `wells` — one API = individual forecast. Several APIs = a **cohort**: the
  parameters describe the group's summed stream; the server splits volumes
  back to members pro-rata on trailing-12 production (echoed as `shares`).
  Every member needs trailing-12 production on each asserted stream, or the
  entry bounces naming the dry well.
- `oil` / `gas` — per-stream parameters, exactly `{qi, di, b}`. `qi` is the
  rate AT the anchor month in units/month (bbl or mcf) — a trendline value,
  never peak-anything, never a single raw reported month. `di` is the
  nominal MONTHLY decline at the anchor (0 < di < 1). `b` is the Arps
  exponent (0–2). Set a stream to `null` to not forecast it — it then
  contributes zero revenue (the echo warns if it recently produced).
  Bounds are sanity rails, not judgment: anything inside them commits, and
  the echo is where a bad-but-legal number gets caught.
- `anchor_month` — required, `"YYYY-MM"`. For a producing well: the month
  qi applies (your last clean signal — it may sit before the last reported
  month, and must not be in the future). For a well with no production
  (DUC / permit): the **asserted first-production month** — timing is your
  call too; source it per the skill (deal-stated schedule → operator's
  permit-to-first-prod cadence via `run_sql` → default norms). The server
  places the drilling AFE at that month for DUC/permit wells.
- `uptime_factor` — optional, 0.5–1.0 (default 1.0). The server commits the
  curve × factor so booked volumes are expected REPORTED volumes while your
  qi stays an honest capacity trendline. Compute it per the skill.
- `struck_months` — optional audit list of months you struck.
- `rationale` — required. The six-question record per the skill, written so
  another engineer could disagree with a specific line.
- `analog_cohort` — optional, and REQUIRED in spirit whenever the analog
  method carried the parameters (any undrilled location; a young producer
  forecast from its population): the structured record of the cohort
  judgment. `curve_label` (entries sharing a label share one type curve —
  give every permit on the same curve the same label), `criteria` (the
  filter in plain terms), `kept` (analog APIs whose production informed the
  curve — each must exist and have reported production), optional
  `excluded` (`[{api, reason}]` — candidates you rejected and why; the
  reasons are the evidence), optional `normalization` (`"per_1000ft"`
  default, `"absolute"` if you prefer raw rates). Display-only: it never
  changes the math, but the server hydrates it (real series, laterals,
  locations) into the deal sheet's evidence module, so a hallucinated API
  bounces the call.

**Validation is all-or-nothing per call**: any violation returns
`{"error": "validation_failed", "violations": [...]}` with every problem
listed and NOTHING saved — fix them all and resend. A valid call returns:

```json
{"run_id": "…", "committed": [ per entry:
   {"wells": [...], "anchor_month": "2026-05", "undrilled": false,
    "oil": {"next_12_cum": …, "next_24_cum": …, "trailing_12_actual": …,
            "next12_over_trailing12": …, "eff_annual_decline_yr1": …,
            "eff_annual_decline_yr5": …, "eur": …, "cum_to_date": …,
            "eur_remaining": …, "eur_per_ft": …,
            "terminal_switch": {"months_from_anchor": …, "date": "YYYY-MM"}},
    "gas": {…}, "shares": {…}, "warnings": [ … ]}],
 "wells_committed": n, "wells_in_run": n,
 "by_status": {"PDP": n, "DUC": n, "PUD": n}}
```

The echo speaks in future volumes — interrogate it per the skill's question
6 (next-12 vs trailing, year-1/year-5 effective decline, EUR/ft vs the
offset family, where the terminal switch lands, whether the run-out EUR is
believable). **Commits are cheap and overwritable**: re-committing a well
replaces just that well's forecast, so assert → check → revise → commit
final is the intended rhythm. Undrilled entries echo `online_month` and no
trailing comparison.

Omit `run_id` on the first call (it mints one); pass the same `run_id` to
add or revise wells on the deal, and carry it into `deal_valuation`.
`by_status` gives the well counts the valuation's assumptions grid needs.
