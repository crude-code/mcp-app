# Crude Code — MCP Server & Renderer

Oil & gas data analytics platform. MCP server + spec-driven inline renderer.

## Architecture

**Outer Claude does the thinking; the server does deterministic work.** There are
no inner agents anymore — the managed-agents / inner-Opus / pip-package era was
removed in the rebuild. The one exception is `get_skill`: a static file bundle
(instructions + supporting files) Claude fetches and follows directly for
occasional, procedure-heavy tasks — not an agent, no code execution on the
server side. Outer Claude (in Claude Desktop / claude.ai) orchestrates
everything through a handful of MCP tools:

- It explores with `run_sql` (direct, capped SELECT access) right in the chat.
- When the chat becomes a deliverable, **Claude itself authors the briefing
  spec** and calls `run_data_analysis(spec)`; the server validates, hydrates
  (re-runs each widget's SQL), persists, and hands back a token + summary.
- For deals it calls `forecast_wells` → `run_valuation` → gets the data to build
  a deal-sheet artifact, with `export_valuation_xlsx` for a live Excel model.
- For geography it calls `map`.
- For a one-off packaged procedure (e.g. extracting a dataroom upload) it
  calls `get_skill(name)` to fetch the instructions and follows them directly.

Every tool is synchronous and server-side. The renderer fetches the finished,
hydrated spec **once** via `get_briefing_full(token)` and renders it inline — no
streaming, no event log, no polling.

### MCP Server (`server/mcp_server.py`)

FastMCP server that Claude Desktop / claude.ai connect to. Plain Python tools —
no agent in the loop. Runs on port 9000 (`/mcp` endpoint). Per-user auth: a
reverse proxy routes `https://<your-host>/<slug>/mcp` to the server with an
`X-User-Slug: <slug>` header; identity resolves via the Supabase `users` table
(`utils.platform.resolve_identity`).

Tools (all return JSON strings):

- **run_sql** — Outer Claude's exploration tool. Plain-English question →
  Claude writes a SELECT → `utils.sql_guard.run_guarded` with
  `EXPLORATION_SCHEMAS` and a 50-row / 50 KB / 5s cap. Returns `{rows, count}`
  or `{error}`. The tight cap is on purpose: results land in the visible chat
  thread, so keep it presentable and the context lean.
- **run_data_analysis** — Takes a Claude-authored briefing `spec` (headline,
  tldr, sections of widgets, each chart/table carrying a SQL string). The
  server (1) shape-validates via `utils.briefing_spec.validate_briefing_spec`,
  (2) dry-runs every widget query (`validate_widget_queries`) — on failure
  returns a structured `{widgets: [...]}` error in-turn so Claude fixes and
  re-calls (nothing is consumed), (3) hydrates (`hydrate_spec` re-runs each
  query under the guard), (4) mints an ephemeral handle token + saves a durable
  `platform.agent_results` row, (5) returns the compact summary Claude narrates
  from (`{surface, briefing_token, headline, tldr, sections, queries}` —
  sections stripped of bulky widget payloads). The renderer reads the full spec
  back via `get_briefing_full(token)`.
- **forecast_wells** — Well-classification + forecast. Takes `groups` (areas,
  each with `wells` and optional `analogs`) and an optional `run_id`. Classifies
  each well via `routing.py` (HISTORY / THIN_PEAKED / CLIMBING / NO_HISTORY) and
  blends analogs for wells lacking history. Returns `{run_id, by_status,
  spectrum, analogs_used}` per group, or `{analogs_required: [...]}` when an
  area needs analogs and none were supplied (Claude re-calls with analogs).
  Claude selects analogs itself via `run_sql` (same formation, comparable
  lateral, nearby, enough history).
- **run_valuation** — Takes `run_id` (from `forecast_wells`) and `params`
  (interest type + blanket numbers, optional `by_api` per-well overrides,
  optional `economics_overrides`). Runs econ on the forecast stage in the run
  record, assembles a slim artifact payload (`build_artifact_payload` in
  `server/valuation/artifact_payload.py` — exec facts, a net production
  series when the deal has one, and the blended NPV at price centers), and
  returns `{surface: "deal_sheet_artifact", run_id, data}`. Claude builds the
  deal-sheet artifact itself (react + recharts + lucide-react) from `data`,
  per the guardrail in `prompts/outer/tool_run_valuation.md` — no MCP-app
  render, no widget spec, no PV cube in the payload. See `server/valuation/`.
- **export_valuation_xlsx** — Renderer-only (`app`-scoped). Builds the live,
  editable Excel model for a completed run and returns `{filename,
  xlsx_base64}`. See `server/valuation/export_xlsx.py`.
- **map** — Takes a map `spec`, validates + mints a map handle, returns
  `{surface: "map", map_token}`. See `server/maps/`.
- **get_skill** — Takes an optional skill `name`. With no/unknown name,
  returns the catalog (`{available_skills: [{name, description}, ...]}`).
  With a valid name, returns the full bundle (`{name, description,
  instructions, files}`) via `server/skills.py`. Pure/static — no DB, no
  network. See `server/skills.py` and `skills/`.
- **get_map_full** — Renderer-only. Returns the full hydrated map spec.
- **get_briefing_full** — Renderer-only (`app`-scoped). Returns
  `{spec: <full hydrated spec>}` by ephemeral token from the in-memory
  `BriefingHandleStore`. Non-blocking: the spec is persisted synchronously
  before the token ever reaches Claude, so it's always present at read time.
- **get_briefing_by_run** — Renderer-only. Durable, never-blocking fetch by
  uuid `run_id` from `platform.agent_results` (`utils/agent_results.py` —
  survives restarts; used when a card is reopened after the 24h token TTL).
  User-scoped.

### MCP App (`renderer/`)

Inline React app rendered inside Claude Desktop. Single-pass build:
`dist/app.html`.

- Vite + React + TypeScript + Tailwind v4 + `vite-plugin-singlefile`
- Entry: `app.html` → `src/app-entry.tsx` → `EIApp`
- `@` path alias → `renderer/src/` in vite.config.ts
- Build: `cd renderer && npm run build` → `dist/app.html` (gated on `tsc -b` —
  vite alone does not type-check)

**Render flow:** `EIApp` parses `ontoolresult` payloads and dispatches on the
invoking tool name. A `TOOL_AGENTS` map gives `run_data_analysis` → "Data
Analyst", which renders `SpecSurface` — it calls `get_briefing_full(briefingToken)`
**once** on mount and renders the returned spec through `SpecRenderer` inside
`AgentChrome`. The `map` tool renders `MapView` (a MapLibre GL well/unit/PLSS
map). `run_valuation` has no `app=` config and never triggers an `ontoolresult`
render at all — Claude builds the deal-sheet as a claude.ai artifact directly
from the tool's `data` payload instead. There is no streaming/event-log path —
`SpecSurface`'s "working" state is just the brief moment before the single
fetch resolves.

**Component tree:**
- `src/EIApp.tsx` — app shell; routes tool results to `SpecSurface` or `MapView`.
- `src/components/SpecSurface.tsx` — fetches the spec via `get_briefing_full`
  once, renders `SpecRenderer` in `AgentChrome` (working → done → error states).
- `src/widgets.tsx` — briefing renderer: `BriefingHeader`, `CommentaryWidget`,
  `CalloutWidget`, `TableWidget`, `LineChartWidget`, `BarChartWidget`,
  `UnknownWidget`, `SpecSection`, `SpecRenderer`, and the `widgetRegistry`
  (`Record<string, FC<WidgetProps>>` — add new widget types here). Spec shape
  `{headline?, tldr?, sections: [{label?, layout, widgets: [...]}]}`.
  `SpecRenderer` special-cases `spec.layout === "deal_sheet"`: a self-contained
  widget that renders its own header/facts/sections full-bleed. When the spec
  carries an `advanced` block, `DealSheetSurface` adds a toggle between the
  compact `DealSheet` and `AdvancedView`.
- `src/components/DealSheet.tsx` — interactive risked deal sheet: facts grid,
  PDP/DUC/PUD status rows, deck/rate selectors indexing the PV cube, a recharts
  forecast chart (Production ↔ Net Cashflow toggle), and the "Download export"
  button wired to `export_valuation_xlsx`. **Unused** since `run_valuation`
  moved to a Claude-built artifact — kept pending cleanup, not wired to any
  tool result anymore.
- `src/components/AdvancedView.tsx` — "Behind the Valuation" tabs: `AssetPanel`,
  `ProductionPanel`, `EconPanel`. **Unused**, same reason as `DealSheet.tsx`.
- `src/components/valuationUI.tsx` — shared valuation primitives (`Segmented`,
  `fmtUSD`/`fmtDate`/`fmtCompact`, `LBL`).
- `src/components/AgentContainer.tsx` — agent chrome ("signal instrument":
  graphite faceplate, level meter, light content screen). Exports `AgentChrome`
  + `AgentWorkingBody`. All identity in `index.css` (`--ac-*`, `--font-chrome*`).
- `src/components/MapView.tsx` — MapLibre GL map surface.
- `src/types.ts` — cross-cutting types (`Agent`, `AgentState`).
- `src/ErrorBoundary.tsx` — top-level error boundary.
- `src/preview.tsx` + `preview.html` — **dev-only** harness (not bundled into
  `dist/`): renders the real components against captured fixtures with hot
  reload. See Testing → Frontend iteration.

**Filename convention:** `PascalCase.tsx` = one React component; `lowercase.tsx`/
`.ts` = module/barrel (`widgets.tsx`, `types.ts`, `valuationUI.tsx`);
`kebab-case.tsx` = entry bootstrap (`app-entry.tsx`).

**Styling convention:** Color, typography, and design tokens use inline
`style={{}}` with semantic CSS vars (`var(--bg-surface)`, `var(--text-primary)`,
`var(--content-accent)`, etc., in `src/index.css`). Layout (flex, grid, padding,
gap, sizing) uses Tailwind classes. Never use shadcn-style tokens like `bg-card`
or `text-foreground`. `index.css` is the single source of truth for all
chrome/content color, type, and surface identity. (Pure black/white depth
shadows stay inline by design; `MapView`'s cartographic ramps are data-viz
palettes, not design tokens.)

### Valuation engine (`server/valuation/`)

Server-side forecast + economics, invoked by the valuation tools (Claude never
authors this code). Pure, unit-tested modules:
- **`types.py`** — `DeclineCurve`, `Forecast`, `WellMeta`, `ForecastProvenance`.
- **`forecast.py`** — `fit_curve` (Arps, b fixed), `curve_rate`,
  `percentile_curves` (cohort median), `project` / `aggregate` (calendar-aware).
- **`casefile.py`** — `parse_case_file` / `CaseFile`: validate + type the JSON
  contract `run_valuation` sends (interest_type, blanket `interest` + optional
  `by_api` overrides, `asset_list` as `well_apis` XOR `filter_sql`,
  economics_overrides). The authoritative interest source.
- **`econ.py`** — `compute_gross_revenue`, `compute_net_cashflow` (WI vs
  minerals branch), `npv`, `resolve_well_interest`. Defaults from `config.ECON`.
- **`deal_sheet.py`** — pure assembly of the `deal_sheet` widget spec (no DB):
  exec facts (`roll_up_facts`), PDP/DUC/PUD buckets, the risked PV-by-status×
  deck×rate cube, and the net forecast production series
  (`build_production_series`). Consumed by the renderer's `DealSheet`.
- **`export_xlsx.py`** — deterministic Excel export. Regroups the persisted
  per-well schedule into static driver columns, **aggregates across statuses**,
  and writes a live **two-sheet** workbook: a **Summary** (deal facts +
  undiscounted totals roll-up) and a single editable **Cashflow** statement —
  scalar assumptions in an amber-highlighted input band on top, commodity
  prices inline as editable per-month columns, cashflow as Excel formulas, a
  cumulative-NCF column. **No discounting / no PV** — that's left to the user.
  Volumes frozen; price/cost/interest are editable named ranges. A reconcile
  oracle (`build_status_drivers` / `status_net_cashflow` / `npv_monthly` /
  `reconcile_total_pv`) validates the engine in tests (independent of the
  workbook).
- **`wells.py`** — `bulk_load_wells` / `bulk_load_production`: one query each.
- **`routing.py`** — per-well classification + analog blend (four states).
  Analog selection is Claude's job (`cohort.py` was removed).
- **`config.py`** — `EconConfig` (`ECON` singleton): the single source for every
  economic parameter (flat oil/gas deck, diffs, tax/GPT, opex/capex, 360-month
  horizon, DUC=+18mo / PERMITTED=+36mo timing, per-status discount ladders, the
  cube's oil-price deck). Read as `config.ECON.<field>`; never re-hardcode at a
  call site. Forecast/routing mechanics deliberately stay at their use sites.
- **`strip.py`** — NYMEX strip price path (`load_strip_curve` etc.); the default
  price deck.
- **`orchestrator.py`** — `forecast_wells_for_run` / `run_economics_for_run` /
  `compose_briefing_for_run`: the functions the tools wrap. Resolves interest
  per well (`by_api` else blanket) from the authoritative case file and persists
  net_oil/net_gas so net volumes are exact under per-well interest.
- **`run_record.py`** — `ValuationRunStore`: mint/read/write the
  `platform.valuation_runs` row. Durable per-deal state keyed by a server-minted
  UUID `run_id`; tools carry only `run_id` + the compact summary each returns.

### Maps (`server/maps/`)

- **`spec.py`** — `parse_map_spec` / `MapSpecError`: validate the map spec.
- **`hydrate.py`** — `hydrate_map` / `MapHydrateError`: fill layer data.
- **`catalog.py`** — layer/source catalog the hydrator draws from.

### Skills (`skills/`)

Static, occasional-use procedures Claude fetches on demand via `get_skill`
rather than having permanently in its system prompt. Each skill is a subfolder
with a `SKILL.md` (YAML-ish `name`/`description` frontmatter + instructions)
plus whatever supporting files it references; `server/skills.py` scans the
directory (`list_skills`) and loads a bundle (`load_skill`) — pure file I/O,
no DB/network/identity, so it works with no `EI_DB_URL` set. Drop a new
subfolder with a `SKILL.md` in to add a skill; nothing else registers it.
- **`dataroom-extract/`** — turns an uploaded oil & gas dataroom (LOS, check
  stubs, AFEs, production reports, title, division orders) into a structured
  `extraction.json` plus a bundled, frozen React viewer artifact
  (`DataroomViewer.jsx`) Claude pastes the extraction into. Feeds
  `forecast_wells` / `run_valuation` when the room is headed for a deal.

### Prompts (`prompts/`)

LLM-facing text, loaded via `utils/prompts.py` (`load("outer/...")`).
- **`outer/`** — text outer Claude reads: `system_prompt.md` (lead-analyst
  posture, available-data summary) + one docstring per tool
  (`tool_run_sql.md`, `tool_run_data_analysis.md`, `tool_forecast_wells.md`,
  `tool_run_valuation.md`, `tool_export_valuation_xlsx.md`, `tool_map.md`,
  `tool_get_skill.md`) + `widget_palette.md`. `compose_outer_system_prompt()`
  assembles `system_prompt.md` + the shared DB schema so Claude can write
  `run_sql` SELECTs without a separate schema tool.
- **`inner/shared_schema.md`** — the DB schema reference. Despite the legacy
  `inner/` path, it is appended to the **outer** system prompt today and is
  kept in sync with `utils/schemas.py` by `tests/test_schema_drift.py`. (It's
  the only surviving `inner/` file — the inner-agent role prompts are gone.)

### Shared Utilities (`utils/`)
- **schemas.py** — Single source of truth for queryable DB schemas.
  `WIDGET_SCHEMAS` (widgets, re-run on every render) and `EXPLORATION_SCHEMAS`
  (`run_sql`, adds `shapes`). Drift guard: `tests/test_schema_drift.py`.
- **db.py** — Connection pool (EI Postgres / RDS). `query(sql, params?, schema?,
  statement_timeout_ms?)` returns list of dicts, coerces Decimal → float.
- **sql_guard.py** — Shared SELECT validator + `run_guarded` executor +
  `dry_run`. Validates structure (SELECT/WITH only, single statement, no
  DML/DDL/smuggling/dangerous functions) and schema (defaults to
  `WIDGET_SCHEMAS`; exploration passes `EXPLORATION_SCHEMAS`), then runs with
  `statement_timeout` and row/JSON-size caps.
- **hydrate.py** — `hydrate_spec(spec)` fills widget data (runs each widget's SQL
  under the guard, isolates per-widget failures). `validate_widget_queries(spec)`
  dry-runs each query and returns a structured error list (the in-turn
  validation `run_data_analysis` calls).
- **briefing_spec.py** — `validate_briefing_spec`: shape/type validation of the
  Claude-authored spec (widget registry + per-widget validators).
- **briefing_handle_store.py** — In-memory per-user `BriefingHandleStore` mapping
  short-lived tokens to hydrated specs (24h TTL). `mint(user_slug, spec)` /
  `fetch(user_slug, token)` — synchronous; the spec is always in hand at mint
  time.
- **agent_results.py** — `AgentResultStore`: durable spec persistence in
  `platform.agent_results` (survives restarts; backs `get_briefing_by_run`).
- **spot_callouts.py** / **futures_callouts.py** — spot/strip price callout
  helpers used during hydration; cache recent `market.spot_prices` /
  `market.futures`.
- **prompts.py** — Loads `prompts/` files. `compose_outer_system_prompt()`
  assembles `outer/system_prompt.md` + `inner/shared_schema.md`.
- **platform.py** — user identity via Supabase (`users`): `resolve_identity`
  maps the `X-User-Slug` header to a user + org context. `_query` for Supabase
  tables (`workspace.*`, `platform.*`).
- **log.py** — centralized file logging with request-ID tracing → `logs/ei.log`.
- **env.py** — shared `.env` loader.
- **run_query.py** — CLI: `echo "SELECT ..." | .venv/bin/python utils/run_query.py`
  (hits `EI_DB_URL`). For Supabase tables use `utils.platform._query`.

### Market data

The platform reads commodity prices from `market.spot_prices` (daily close,
WTI / Brent / Henry Hub) and related `market.*` / `public.*` / `shapes.*` /
`financials.*` tables. Populating those tables (primary-source ingestion) is out
of scope for this repo — point `EI_DB_URL` at a Postgres database whose schema
matches `utils/schemas.py` and `prompts/inner/shared_schema.md`.

## Running Locally

One-time setup (after cloning): `.venv/bin/pip install -r requirements.txt`
(installs numpy/scipy/pandas/openpyxl and the rest). Then:
```bash
.venv/bin/python server/mcp_server.py &   # MCP on 9000
```
The renderer runs **inside** Claude Desktop, not a browser. To update it:
`cd renderer && npm run build` → `dist/app.html`, then deploy.

Always use `.venv/bin/python`. Never bare `python` / `python3`.

`.env` at repo root needs at least `EI_DB_URL` and `ANTHROPIC_API_KEY`.

## Deploy

- **`deploy.sh`** / **`deploy-dev.sh`** — idempotent scripts run on the host by
  GitHub Actions (`.github/workflows/deploy.yml` / `deploy-dev.yml`) on push to
  `main` / `dev`. Pull, sync the nginx config, rebuild the renderer, and
  restart the MCP server only when a path it actually loaded into memory
  changed since the last successful deploy (tracked in
  `.last-mcp-deployed-sha`).
- **`deploy/nginx/`** — the canonical prod/dev vhost configs, synced onto the
  host by the deploy scripts.
- **`deploy/systemd/`** — timer units for this deployment's own scheduled jobs
  (market/well ingestion, activity digests, staleness checks). They invoke an
  `ingest` package that lives outside this repo — populating the database is
  out of scope here (see Market data above).

## Testing

### Pytest suite (`tests/`)
Run: `.venv/bin/pytest -q`.
- `tests/conftest.py` — adds repo root to `sys.path`, exposes `fake_identity`,
  auto-skips tests marked `db` (no `EI_DB_URL`), `anthropic` (no
  `ANTHROPIC_API_KEY`), and `network` (no `--run-network`); purges sentinel
  `valuation_runs` rows at session end.
- Coverage spans the live surface: `run_data_analysis` + `run_sql` tools, the
  valuation engine (forecast/econ/deal-sheet/export/strip/routing), maps,
  `sql_guard`, `hydrate`, `briefing_handle_store`, `agent_results`, the
  `get_briefing_*` renderer tools, schema drift, and the export workbook.

### Frontend iteration (no Claude Desktop)
`cd renderer && npm run dev` → `http://localhost:5173/preview.html` mounts
`src/preview.tsx`, rendering the real production components against captured
fixtures with hot reload — no MCP server, no Claude Desktop. The fixtures under
`renderer/src/fixtures/` are committed captures; regenerate them from the real
builders when a spec changes. `app.html` stays the shipped build; `preview.html`
is dev-only and never bundled into `dist/`.
