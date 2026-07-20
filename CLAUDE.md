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
- When the chat becomes a deliverable, **Claude itself builds a claude.ai
  artifact** straight from `run_sql` data — there is no server-side spec
  authoring or render step for this path anymore.
- For deals it calls `forecast_wells` → `run_valuation` → gets a slim payload
  plus the frozen `DealSheet.jsx` template in the same response, and builds
  the deal-sheet artifact from them directly.
- For geography it calls `map`.
- For a one-off packaged procedure (e.g. extracting a dataroom upload) it
  calls `get_skill(name)` to fetch the instructions and follows them directly.

Every tool is synchronous and server-side. The renderer today only ever
renders maps: it fetches the finished, hydrated map spec **once** via
`get_map_full(token)` and renders it inline — no streaming, no event log, no
polling.

### MCP Server (`server/mcp_server.py`)

FastMCP server that Claude Desktop / claude.ai connect to. Plain Python tools —
no agent in the loop. Runs on port 9000 (`/mcp` endpoint). Per-user auth: a
reverse proxy routes `https://<your-host>/<slug>/mcp` to the server with an
`X-User-Slug: <slug>` header; identity resolves via the Supabase `users` table
(`utils.platform.resolve_identity`).

Tools (all return JSON strings):

- **run_sql** — Outer Claude's exploration tool. Plain-English question →
  Claude writes a SELECT → `utils.sql_guard.run_guarded` with
  `EXPLORATION_SCHEMAS` and a 200-row / 100 KB / 5s cap. Returns `{rows, count}`
  or `{error}`. The cap is on purpose: results land in the visible chat
  thread, so keep it presentable and the context lean.
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
  series when the deal has an active status, and `economics` carrying
  `npv_at_centers`, the full deck×status×rate `cube`, `decks`,
  `default_deck`, `default_rates`, and `statuses`), and returns
  `{surface: "deal_sheet_artifact", run_id, data, viewer}` — `viewer` is the
  frozen `DealSheet.jsx` template (`server/valuation/viewer/`), shipped in
  every response so the template always matches the payload contract. Claude
  builds the deal-sheet artifact itself by filling `data` into `viewer`, per
  the guardrail in `prompts/outer/tool_run_valuation.md` — no MCP-app render.
  See `server/valuation/`.
- **map** — Takes a map `spec`, validates + mints a map handle, returns
  `{surface: "map", map_token}`. See `server/maps/`.
- **get_skill** — Takes an optional skill `name`. With no/unknown name,
  returns the catalog (`{available_skills: [{name, description}, ...]}`).
  With a valid name, returns the full bundle (`{name, description,
  instructions, files}`) via `server/skills.py`. Pure/static — no DB, no
  network. See `server/skills.py` and `skills/`.
- **get_map_full** — Renderer-only. Returns the full hydrated map spec.

### MCP App (`renderer/`)

Inline React app rendered inside Claude Desktop. Single-pass build:
`dist/app.html`.

- Vite + React + TypeScript + Tailwind v4 + `vite-plugin-singlefile`
- Entry: `app.html` → `src/app-entry.tsx` → `EIApp`
- Build: `cd renderer && npm run build` → `dist/app.html` (gated on `tsc -b` —
  vite alone does not type-check)

**Render flow:** `EIApp` parses `ontoolresult` payloads and looks at the
invoking tool name; only `map` triggers a render — it mounts `MapView` (a
MapLibre GL well/unit/PLSS map), which fetches the full hydrated map spec
**once** via `get_map_full(map_token)` and shows a plain loading spinner
until it resolves (error text on a bad/expired token). `run_valuation`
(and every other tool) has no `app=` config and never triggers an
`ontoolresult` render — Claude builds the deal-sheet as a claude.ai artifact
directly from the tool's `data` payload and the frozen template (`viewer`)
that rides in the same response. There is no streaming/event-log path.

**Component tree:**
- `src/EIApp.tsx` — app shell; on `map` tool results, mounts `MapView`.
- `src/components/MapView.tsx` — MapLibre GL map surface, including its own
  loading/error states.
- `src/ErrorBoundary.tsx` — top-level error boundary.

**Filename convention:** `PascalCase.tsx` = one React component;
`kebab-case.tsx` = entry bootstrap (`app-entry.tsx`).

**Styling convention:** Color, typography, and design tokens use inline
`style={{}}` with semantic CSS vars (`var(--bg-surface)`, `var(--text-primary)`,
`var(--content-accent)`, etc., in `src/index.css`). Layout (flex, grid, padding,
gap, sizing) uses Tailwind classes. Never use shadcn-style tokens like `bg-card`
or `text-foreground`. `index.css` is the single source of truth for color,
type, and surface identity. (`MapView`'s cartographic ramps are data-viz
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
- **`deal_sheet.py`** — pure assembly helpers for the artifact payload (no
  DB): exec facts (`roll_up_facts`), the net forecast production series
  (`build_production_series`), and `default_rates`. Consumed by
  `artifact_payload.py`.
- **`artifact_payload.py`** — `build_artifact_payload`: assembles the slim
  payload `run_valuation` returns (`facts`, `production`, and `economics` —
  `npv_at_centers`, the full deck×status×rate `cube`, `decks`,
  `default_deck`, `default_rates`, `statuses`) from a run's `wells` +
  `economics` stages, reusing `deal_sheet.py`'s helpers. Also `load_viewer`:
  reads the frozen artifact template.
- **`viewer/DealSheet.jsx`** — the frozen deal-sheet artifact template
  (react + recharts only; no host APIs, no CSS vars — it runs in the
  claude.ai artifact sandbox). Shipped verbatim as `viewer` in every
  `run_valuation` response; Claude fills `DATA`/`TITLE`/`TLDR` and nothing
  else.
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
- **`orchestrator.py`** — `forecast_wells_for_run` / `run_valuation_for_run` /
  `compose_artifact_payload_for_run`: the functions the tools wrap. Resolves
  interest per well (`by_api` else blanket) from the authoritative case file
  and persists net_oil/net_gas so net volumes are exact under per-well
  interest.
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
  (The deal-sheet template is NOT a skill — it rides in `run_valuation`'s
  response; see `server/valuation/viewer/`.)

### Prompts (`prompts/`)

LLM-facing text, loaded via `utils/prompts.py` (`load("outer/...")`).
- **`outer/`** — text outer Claude reads: `system_prompt.md` (lead-analyst
  posture, available-data summary) + one docstring per tool
  (`tool_run_sql.md`, `tool_forecast_wells.md`, `tool_run_valuation.md`,
  `tool_map.md`, `tool_get_skill.md`). `compose_outer_system_prompt()`
  assembles `system_prompt.md` + a live skills catalog (built from
  `server/skills.list_skills()`) into the MCP server `instructions`.
- **`outer/shared_schema.md`** — the DB schema reference, kept in sync with
  `utils/schemas.py` by `tests/test_schema_drift.py`. It is appended to the
  **`run_sql` tool description** (`compose_run_sql_doc()`), NOT to the server
  instructions: clients truncate MCP instructions (observed ~2.3 KB on
  claude.ai), while tool descriptions arrive intact. All SQL guidance —
  tables, columns, join keys, unit caveats — lives in that one docstring;
  other tool docs point to it rather than repeating any of it.

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
- **briefing_handle_store.py** — In-memory per-user `BriefingHandleStore`
  mapping short-lived tokens to hydrated specs (24h TTL). `mint(user_slug,
  spec)` / `fetch(user_slug, token)` — synchronous, spec always in hand at
  mint time. Today it serves only map specs, backing `map` / `get_map_full`
  (name kept for history, from when it also backed briefings).
- **prompts.py** — Loads `prompts/` files. `compose_outer_system_prompt()`
  assembles `outer/system_prompt.md` + a live skills catalog (no schema —
  instructions get truncated by clients). `compose_run_sql_doc()` assembles
  `outer/tool_run_sql.md` + `outer/shared_schema.md` for the `run_sql`
  tool description.
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
matches `utils/schemas.py` and `prompts/outer/shared_schema.md`.

## Running Locally

One-time setup (after cloning): `.venv/bin/pip install -r requirements.txt`
(installs numpy/scipy/pandas and the rest). Then:
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
- Coverage spans the live surface: `run_sql` + the valuation tools
  (`forecast_wells`, `run_valuation`), the valuation engine (forecast/econ/
  artifact-payload/strip/routing), maps, `sql_guard`,
  `briefing_handle_store` (map tokens), and schema drift.
