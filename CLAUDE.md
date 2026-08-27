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
- For deals it calls `deal_forecast_wells` → `deal_valuation` → gets a slim payload
  plus the frozen `DealSheet.jsx` template in the same response, and builds
  the deal-sheet artifact from them directly.
- For geography it calls `map_render`.
- For a one-off packaged procedure (e.g. extracting a dataroom upload) it
  calls `get_skill(name)` to fetch the instructions and follows them directly.
- When the dataroom-extract skill produces an `extraction.json`, it persists
  it via `dataroom_save_extraction` so the deal record outlives the chat.
- When the user hits friction or wants something (a bug, a dataset request,
  a feature wish) it files `message_team` — durable row + best-effort email
  to the team.

Every tool is synchronous and server-side. The renderer today only ever
renders maps: it fetches the finished, hydrated map spec **once** via
`map_read_full(token)` and renders it inline — no streaming, no event log, no
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
- **deal_forecast_wells** — Accept-and-echo. Claude is the reservoir engineer
  (doctrine: `get_skill("well-forecasting")`); it asserts decline parameters
  per well or cohort — `{qi, di, b}` per stream (qi = rate at the anchor,
  never peak-anything), a required `anchor_month` (producers: where qi
  applies; undrilled wells: the asserted first-production month — timing is
  Claude's call too), optional `uptime_factor` (server commits qi × factor),
  `struck_months`, a required `rationale`, and an optional structured
  `analog_cohort` (curve_label / criteria / kept / excluded-with-reasons —
  the analog method's judgment record, display-only; kept analogs must
  exist and have production). The server bounds-validates
  (all-or-nothing per call, every violation listed, nothing saved on a
  bounce), merges into the run's forecast stage (re-asserting a well
  overwrites just that well — commits are cheap), and echoes consequences in
  future volumes: next-12/24 cum vs trailing-12 actuals, effective annual
  decline at years 1/5, EUR + EUR/ft, terminal switch timing, warnings.
  Cohort entries (several `wells`) assert the summed stream; the server
  allocates to members pro-rata on trailing-12 per stream (exact — q(t) is
  linear in qi). Run ownership is enforced. Nothing server-side ever chooses
  a parameter; evidence comes from `run_sql` (offsets, histories, operator
  timing cadence).
- **deal_valuation** — Takes `run_id` (from `deal_forecast_wells`) and `params`
  (interest type + blanket numbers, optional `by_api` per-well overrides,
  optional `economics_overrides`). Runs econ on the forecast stage in the run
  record, assembles the artifact payload (`build_artifact_payload` in
  `server/valuation/artifact_payload.py` — exec facts, `economics` carrying
  `npv_at_centers`, the full deck×status×rate `cube`, `decks`,
  `default_deck`, `default_rates`, and `statuses`, plus `assumptions` for
  the sheet's provenance panel and `evidence` — the per-assertion judgment
  record built by `server/valuation/evidence.py` at valuation time), and
  returns `{surface: "deal_sheet_artifact", run_id, data, viewer,
  viewer_url, viewer_sha256}`. `data.export.bundle_url` is minted here — a
  signed `bundle` link for this run, which is what the template's download
  row renders; it is omitted (and the row disappears) when no signing secret
  is configured, since an in-memory ticket would leave a button that dies at
  the next restart. `viewer` is the frozen `DealSheet.jsx`
  template (`server/valuation/viewer/`), shipped in every response so the
  template always matches the payload contract; `viewer_url` +
  `viewer_sha256` are the fast lane — the same source published as a
  static content-addressed file (`deal-sheet-<sha12>.jsx`) on the apex
  `crudecode.dev/templates/`, so a session with code execution downloads
  it instead of re-emitting ~50 KB token by token (inline `viewer` stays
  the universal fallback: Team/Enterprise egress defaults block external
  domains, and code execution can be off). Claude builds the deal-sheet
  artifact itself by filling `data` into the template, per the guardrail
  in `prompts/outer/tool_deal_valuation.md` — no MCP-app render. See
  `server/valuation/`.
- **export_data** — The download lane: hands the user a file of work the
  session already did, instead of a chat payload. Takes a `kind`
  (`bundle` — a zip of `wells_monthly.csv` (the whole schedule: volumes *and*
  every cashflow line item, `net_cashflow = net_rev − sev_tax − gpt − capex −
  opex` row by row), `parameters.csv`, and a generated README; the generous
  default for a finished valuation, since the user keeps whichever columns
  they need rather than naming them up front. `volumes` — monthly gross + net
  oil/gas per well over the run's full horizon; `parameters` — the committed
  decline curves per well per stream, committed *and* asserted qi, Di, b,
  terminal switch, anchor, rationale; `query` — a `run_sql` SELECT re-run at
  export scale, 100k rows against the 200-row chat cap) and returns
  `{download_url, filename, kind, expires_in_hours}` — a few hundred bytes of
  context no matter how large the file. The narrow CSV kinds stay for when
  someone wants one slice; `bundle` is the one to offer when they just want
  the deal's numbers. Bytes are assembled at *fetch* time by `server/exports.py` straight
  from the run record and streamed down `GET /export/{token}/{filename}`
  (`server/uploads.py`), so nothing sits at rest and an expired link costs one
  re-mint, never a recomputation. The mirror of the upload lane, with two
  differences that follow from the client being a browser rather than the
  sandbox: the token is never consumed (browsers retry, people double-click)
  and failures render as an HTML page rather than JSON, since the click can
  come from a deal sheet weeks after the session that produced it.
  **Two grant forms.** Run-scoped kinds get a *signed* token
  (`server/export_tokens.py`) — kind, run id, user and expiry travel inside it
  under an HMAC the server recomputes, so nothing is stored and a link keeps
  working across restarts for a year. That durability is what lets a deal
  sheet carry a download row. `query` keeps the in-memory ticket and its
  24-hour TTL, because its grant is an arbitrary SELECT: too large for a URL
  and not a thing to publish in one. Signing needs `CC_EXPORT_SECRET` in the
  environment; with none set every kind falls back to the ticket and the deal
  sheet renders no download row (`durable: false` in the tool's response).
  Revocation is by rotating that secret — there is no per-token kill switch,
  which is the cost of not keeping a list.
  A `query` export is dry-run at mint time so a bad SELECT fails in the
  conversation, not behind a link the user already clicked. Deliberately not a
  data feed: the link expires, re-minting needs a live session, and the caps
  are finite — see `prompts/outer/tool_export_data.md`.
- **message_team** — Files a user message (bug / feedback / feature_request /
  data_request / other) to the Crude Code team. Table-first: inserts into
  `platform.team_messages` (`server/team_messages.py`, the durable record),
  then best-effort SES email to `agent@crudecode.dev` (`utils/ses.py`) with
  identity tagged server-side — a mail failure returns `email_sent: false`,
  never a failed filing. Optional `context` jsonb joins the message to live
  records (`run_id`, `extraction_id`, …). Rate-capped (10/user/hour, checked
  pre-insert). Destination hardwired — not a general email capability. The
  proactive-filing posture lives in `prompts/outer/tool_message_team.md` +
  a system-prompt bullet.
- **map** — Takes a map `spec`, validates + mints a map handle, returns
  `{surface: "map", map_token}`. See `server/maps/`.
- **get_skill** — Takes an optional skill `name`. With no/unknown name,
  returns the catalog (`{available_skills: [{name, description}, ...]}`).
  With a valid name, returns the full bundle (`{name, description,
  instructions, files, file_urls, file_sha256}`) via `server/skills.py`.
  `file_urls`/`file_sha256` are the fast lane — every supporting file is
  also published content-addressed (`skill-<sha12>-<name>`) on the apex
  `crudecode.dev/templates/` by the deploy scripts, so a session with code
  execution curls the frozen files instead of re-typing ~45 KB from the
  response (inline `files` stays the fallback; naming pinned by
  `tests/test_template_publish_drift.py`). Pure/static — no DB, no
  network (fetches are still `trace`-logged, slug read straight from the
  routing header). See `server/skills.py` and `skills/`.
- **dataroom_open** — Capture-first registration of a dataroom zip, called
  before any of it is read. Takes `label`, `sha256`, `size_bytes` (hashed
  in the sandbox). New hash → pending `platform.dataroom_rooms` row
  (`server/room_store.py`, `RoomStore`) + one-time upload URL; the skill's
  `room_push.py` streams the zip to `/upload/room/{token}`, which re-hashes
  on receipt (mismatch → 422, token survives for retry) and lands the blob
  in Supabase Storage keyed `rooms/<sha256>.zip`
  (`server/blob_store.py`, `SupabaseBlobStore` — service-role key, bucket
  auto-created, pushed via asyncio.to_thread so big rooms never block the
  event loop). Known hash → `{status: "known"}`: the identical room is
  already captured (rooms are content-addressed and global across users —
  never revealed as such to the user; "filed", nothing more), and the
  reuse lane kicks in: a returning user gets their own newest row's id, a
  first-time holder gets a fresh per-user copy of the room's
  `initial_extraction` snapshot — either way `extraction_ready: true` plus
  a one-time `extraction_url` (`GET /upload/extraction/{token}`) the
  sandbox curls straight to `extraction.json`, skipping re-extraction
  entirely (`extraction_ready: false` → normal flow, pass `room_id` when
  persisting). Rooms carry a write-once `initial_extraction` snapshot: the
  first kit saved with a `room_id` (not a correction re-save) is copied to
  the room row by the kit upload handler; per-user corrections only ever
  touch `platform.dataroom_extractions` rows (which now carry `room_id`).
  DDL: `deploy/sql/001-dataroom-rooms.sql` (first in-repo migration; apply
  with psql against SUPABASE_DATABASE_URL).
- **dataroom_save_extraction** — Mints a one-time HTTP upload URL for a
  dataroom-extract persist kit; carries only `label` (+ optional
  `extraction_id` for in-place re-saves). The kit itself travels
  out-of-band: the skill's `persist_pack.py --upload` POSTs it from the
  code-execution sandbox to `/upload/kit/{token}` (`server/uploads.py`), so
  extraction data never transits the model's context. Tokens
  (`server/upload_tokens.py`, `UploadTokenStore`) are minted on the
  authenticated MCP channel, TTL ~15 min, single-use **on success** — a
  failed upload can retry the same URL. The handler runs the same path the
  old inline call did: the two tall tables arrive as CSV strings + a
  `sources` provenance legend, expanded back to canonical rows by
  `server/extraction_transport.py` (headers drift-tested against the
  packer) — CSV exists only on the wire, never at rest. The persisted
  contract is the room's **private economics** (interests, check-stub
  revenue, LOS/AFE expenses, deal/wells/tracts/DOs/documents);
  `production_history` omitted by default (publicly reconstructable by
  API). The packer verifies the response's `stored` counts against its own
  `expected_stored` and prints a one-line verdict — the only thing that
  enters chat. Backed by `platform.dataroom_extractions` via
  `server/extraction_store.py` (`ExtractionStore`): in blob mode
  (production) the payload rests in Supabase Storage as
  `extractions/<id>.json` and the row holds a pointer stub — rows stay
  row-sized at any package scale, so a full 227-stub room persists whole
  (50 MB sanity ceiling; the old 2 MB row cap was an inline-tool-era
  relic). Upload URLs are single-use on *success* — a rejected upload
  retries the same URL inside the ~15-min TTL.
  A sandbox connection failure = the user's network egress allowlist is
  missing the upload host (incomplete setup — surfaced to the user, no
  inline fallback). `/upload/echo/{token}` is a token-gated probe endpoint
  for measuring the sandbox-proxy size ceiling against a live deploy.
  nginx: dedicated `/upload/` location (no slug header — the token carries
  identity), `client_max_body_size 600m`.
- **map_read_full** — Renderer-only. Returns the full hydrated map spec.

Non-tool HTTP lane: **GET /new-account** (`server/accounts.py`) — anonymous
account mint for the CrudeDocs funnel (crudecode.dev/docs/*). Fetched by
Claude's web-fetch tool from a visitor's chat after they say yes to an
account: inserts a `platform.users` row (email NULL, name "CrudeDoc
visitor", org `crudedoc-signups`, `notes.source='crudedoc'`) and returns
typed state only — `{status, shared, mcp_url, expires_at}` as text/plain
(the fetch tool rejects non-text). Never prose: the CrudeDoc owns all
narration per status. Per-IP rate limit (in-memory, X-Real-IP from nginx);
over-limit or mint failure → `{"status": "unavailable"}` with HTTP 200 so
the doc's fallback branch can narrate. `?t=` is ignored (the site's copy
button appends a per-click token purely to defeat Anthropic's per-URL fetch
cache). `CC_PUBLIC_MCP_BASE` overrides the URL base (default the prod
`https://mcp.crudecode.dev` — dev mints deliberately return prod connector
URLs; both point at the same Supabase).

### MCP App (`renderer/`)

Inline React app rendered inside Claude Desktop. Single-pass build:
`dist/app.html`.

- Vite + React + TypeScript + Tailwind v4 + `vite-plugin-singlefile`
- Entry: `app.html` → `src/app-entry.tsx` → `CCApp`
- Build: `cd renderer && npm run build` → `dist/app.html` (gated on `tsc -b` —
  vite alone does not type-check)

**Render flow:** `CCApp` parses `ontoolresult` payloads and looks at the
invoking tool name; only `map_render` triggers a render — it mounts `MapView` (a
MapLibre GL well/unit/PLSS map), which fetches the full hydrated map spec
**once** via `map_read_full(map_token)` and shows a plain loading spinner
until it resolves (error text on a bad/expired token). `deal_valuation`
(and every other tool) has no `app=` config and never triggers an
`ontoolresult` render — Claude builds the deal-sheet as a claude.ai artifact
directly from the tool's `data` payload and the frozen template (`viewer`)
that rides in the same response. There is no streaming/event-log path.

**Component tree:**
- `src/CCApp.tsx` — app shell; on `map_render` tool results, mounts `MapView`.
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

Server-side calculator + economics, invoked by the valuation tools (Claude never
authors this code). Decline parameters are asserted by Claude via
`deal_forecast_wells`; nothing in this package fits or chooses one. Methodology
changes are proven in the sibling **`forecast-benchmark`** repo (blind
hindcast, both arms scored by the same code) — this repo ships only the
calculator. Pure, unit-tested modules:
- **`types.py`** — `DeclineCurve` (qi = anchor rate), `Forecast`, `WellMeta`,
  `ForecastProvenance`.
- **`forecast.py`** — the calculator: `make_curve` (asserted params →
  curve; owns the terminal-switch formula), `make_zero_curve` (unasserted
  stream), `curve_rate` (hyperbolic + terminal-exponential tail),
  `project` / `aggregate` (calendar-aware).
- **`consequences.py`** — the echo math, pure: effective annual decline,
  next-12/24 cums, trailing-window and cum-through comparators, EUR/EUR-ft,
  cohort `allocation_shares`. Conventions (t=1..N for producers, t=0.. for
  undrilled online months; EUR replaces post-anchor actuals, never
  double-counts) are pinned in its module docstring.
- **`casefile.py`** — `parse_case_file` / `CaseFile`: validate + type the JSON
  contract `deal_valuation` sends (interest_type, blanket `interest` + optional
  `by_api` overrides, `asset_list` as `well_apis` XOR `filter_sql`,
  economics_overrides). The authoritative interest source.
- **`econ.py`** — `compute_gross_revenue`, `compute_net_cashflow` (WI vs
  minerals branch), `npv`, `resolve_well_interest`. Defaults from `config.ECON`.
- **`deal_sheet.py`** — pure assembly helpers for the artifact payload (no
  DB): exec facts (`roll_up_facts`) and `default_rates`. Consumed by
  `artifact_payload.py`.
- **`artifact_payload.py`** — `build_artifact_payload`: assembles the
  payload `deal_valuation` returns (`facts`, `economics` —
  `npv_at_centers`, the full deck×status×rate `cube`, `decks`,
  `default_deck`, `default_rates`, `statuses` — plus `assumptions` and the
  `evidence` passthrough) from a run's `wells` + `economics` stages,
  reusing `deal_sheet.py`'s helpers. Also `load_viewer` (reads the frozen
  artifact template), `viewer_sha256` (digest of the template file bytes),
  and `viewer_url` (the published content-addressed URL;
  `CC_TEMPLATE_BASE_URL` overrides the apex base for local testing) —
  naming pinned against the deploy scripts and nginx by
  `tests/test_template_publish_drift.py`.
- **`evidence.py`** — evidence assembly, pure (DB loads passed in by the
  orchestrator): groups the forecast stage back into assertion entries
  (`entry_id`; same-`curve_label` analog entries merge), hydrates reported
  histories (capped 60 mo), evaluates the committed curves forward from
  their anchors, prices each well off the persisted `by_well` schedule at
  its status-center rate (entry PVs sum to the headline by construction),
  and hydrates analog cohorts — kept analogs' per-1,000-ft series, excluded
  reasons, mile-space coordinates from `wells.geom`. Display-only; nothing
  here feeds the cashflow math. Written into the `wells` stage at
  valuation time.
- **`viewer/DealSheet.jsx`** — the frozen deal-sheet artifact template
  (react + recharts only; no host APIs, no CSS vars — it runs in the
  claude.ai artifact sandbox). V3 layout: exec header + PV-by-status +
  sensitivity + "what informed the model", then two data-driven evidence
  modules (producing fits with residual strip; type curves with analog
  cohort, kept/excluded tables, schematic map) that render only when the
  payload carries entries of that kind, and a download row that renders when
  the payload carries `data.export.bundle_url` (a plain `<a target="_blank">`
  — the artifact CSP blocks cross-origin `fetch`, and fetching would pull the
  bytes into the iframe instead of the user's disk). Shipped verbatim as
  `viewer` in every `deal_valuation` response; Claude fills
  `DATA`/`TITLE`/`TLDR` and nothing else. Nothing in the build compiles this
  file — it is parsed first inside the artifact sandbox — so
  `tests/test_template_publish_drift.py` runs it through
  `esbuild --loader=jsx`.
- **`wells.py`** — `bulk_load_wells` / `bulk_load_production`: one query each.
- **`config.py`** — `EconConfig` (`ECON` singleton): the single source for every
  economic parameter (flat oil/gas deck, diffs, tax/GPT, opex/capex, 360-month
  horizon, the terminal decline `terminal_di_annual` — the calculator's one
  own number — per-status discount ladders, the cube's oil-price deck, and
  the DUC=+18mo / PERMITTED=+36mo timing fallbacks that now date only legacy
  runs — new forecasts carry an asserted online month). Read as
  `config.ECON.<field>`; never re-hardcode at a call site.
- **`strip.py`** — NYMEX strip price path (`load_strip_curve` etc.); the default
  price deck.
- **`orchestrator.py`** — `forecast_wells_for_run` (validate → allocate →
  merge-write → echo; raises `ForecastValidationError` carrying every
  violation) / `run_valuation_for_run` / `compose_artifact_payload_for_run`:
  the functions the tools wrap. `_load_forecast_stage` is the one reader of
  the forecast stage and replays legacy fit-era stages unchanged (tolerant
  `qi_peak` serde, per-stream peak offsets, status-derived timing fallback,
  `classification`→`needs_capex` fallback). Resolves interest per well
  (`by_api` else blanket) from the authoritative case file and persists
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
no DB/network/identity, so it works with no `CC_DB_URL` set. Drop a new
subfolder with a `SKILL.md` in to add a skill; nothing else registers it.
- **`aries-explorer/`** — reads an uploaded ARIES database (`.accdb`/`.mdb`,
  the Halliburton/Landmark reserves & economics format) and shows the user
  what's inside — standalone: not the dataroom flow, not a valuation, no
  persistence lane (nothing uploaded or stored; the file stays in the chat).
  Bundled `ARIES.md` is the domain reference (table map, the AC_ECONOMIC
  8-word line grammar, units/escalation codes, stream numbers);
  `aries_triage.py` opens the binary (mdb-tools if present, else pip
  `access_parser` — code execution is a hard requirement, no by-hand
  fallback), inventories every table, dumps the load-bearing ones to CSV and
  streams AC_PRODUCT into coverage stats (the huge computed tables are never
  dumped); `aries_payload.py` decodes deterministically — scenario
  qualifiers (BASE by default), reserve-category rollup, per-property
  forecast source (segments / type-curve lookup / rate lines; AC_FCST is
  the cache of the rate lines, reported as one forecast), assumption
  clusters (identical lines counted across properties, unknown keywords
  passed through verbatim), ARLOOKUP type curves, AR_SIDEFILE side files
  (where price decks usually live), NET-line interests (word 0 = WI,
  word 1 = NRI, %-unit aware — what the economics run actually uses; the
  viewer leads with these and surfaces a disagreeing master value) with
  reversion/schedule tails flagged verbatim, and integrity checks
  (referential, master-vs-NET interest reconciliation, forecast START vs
  last actuals) — with a `--facts` digest the model reads before writing
  `notes.json` (the judgment layer). Claude fills the emitted payload into
  the frozen `AriesViewer.jsx` as `DATA`/`TITLE`/`TLDR` (`example.json` is
  generated from a synthetic fixture by the payload script itself, so it
  can't drift). Doctrine: the database's forecasts and economics are the
  author's claims — displayed, never adopted into a valuation (the one
  sanctioned exception is `aries-to-valuation`, below, on explicit request).
- **`aries-to-valuation/`** — lane 1 of the ARIES→valuation integration:
  when the user explicitly asks to value an ARIES database's own curves,
  `aries_curves.py` translates the section-4 forecasts into `deal_forecast_wells`
  assertions — decline conversion per the pinned conventions in the
  explorer's ARIES.md (effective-annual secant → nominal monthly; verified
  against a real database's own oneliner to ≤0.013% per stream, 20 wells ×
  2 streams), anchor = START, rationale carrying the verbatim §4 lines +
  qualifier + db sha — and the normal `deal_forecast_wells` → `deal_valuation`
  flow runs unchanged (echo, evidence, exports all come free). Only the
  proven line shape translates (hyperbolic main + terminal ditto); LOOKUP /
  LIST / multi-segment streams are refused per stream with verbatim reasons
  in the coverage report, which also carries what the engine doesn't model
  (NGL yield, shrink, water opex) and the quantified ARIES-tail vs
  engine-tail delta. Optional `--tieout oneliner.json` reproduces the
  seller's EURs as a translation-health gate (>0.1% mean = stop). The
  deliverable is labeled "seller's curves, Crude Code economics" — a third
  number, never a replay of the seller's model (their prices/costs/life are
  never used) and never the default valuation. Engine constants are
  drift-pinned by `tests/test_aries_curves.py`.
- **`aries-writeback/`** — the reverse direction: exports Crude Code
  forecasts as an **ARIES import package** — a zip of CSVs
  (`AC_ECONOMIC.csv` rows in the canonical six-column shape under a NEW
  qualifier, a PROPNUM-by-API crosswalk, and a generated README walking the
  engineer through the MS Access append on a copy of their database).
  `aries_package.py` runs the pinned decline conversion backwards
  (nominal-monthly → effective-annual secant); the round trip through
  aries-to-valuation's forward parser is pinned by
  `tests/test_aries_package.py`, and the engine's terminal is drift-pinned
  against `config.ECON`. Guardrails: refuses a qualifier that already
  exists in the target database (never overwrites scenarios), never
  fabricates a PROPNUM (unknowns ship as labeled placeholders with join
  instructions), never produces or edits a binary `.accdb` — that would be
  a server-side Jackcess/JVM lane, deliberately not built yet.
- **`dataroom-extract/`** — turns an uploaded oil & gas dataroom (LOS, check
  stubs, AFEs, production reports, title, division orders) into a structured
  `extraction.json` (now carrying a `flags` list — the read-before-bidding
  caveats) plus a viewer artifact built like the deal sheet: the bundled
  `viewer_payload.py` derives a compact display payload (LTM net-revenue
  rollups, revenue shares, interest sums, status groups, document folders —
  deterministic code, never model arithmetic; ~13 KB where the raw
  extraction is ~1.4 MB) and Claude fills it into the frozen
  `DataroomViewer.jsx` (react-only cover page: stat strip, numbered flags,
  collapsible status-grouped manifest, doc folders; wells spine or tracts
  spine, modules hide when data is absent) as `DATA`/`TITLE`/`TLDR`. The
  extraction's private economics are persisted via `persist_pack.py` →
  `dataroom_save_extraction` (count-verified; re-saved under the same
  `extraction_id` after corrections; the raw extraction never gets pasted
  into an artifact). Feeds `deal_forecast_wells` / `deal_valuation` when the room
  is headed for a deal.
- **`statement-checkup/`** — a plain-English health check of one royalty
  check stub for an individual mineral/royalty owner (explicitly not a
  valuation and not a dataroom — `dataroom-extract` is for acquisition
  packages). Claude extracts the statement into `statement.json` (Owner
  Share vs Property Values columns never mixed, line items signed as
  printed, interest decimals copied verbatim), resolves wells and pulls
  state volumes + benchmark prices via `run_sql` into `public.json`, then
  the bundled `checkup_payload.py` does every rollup — no model
  arithmetic — and ties the extraction out against the statement's own
  printed totals (a statement that can't reproduce its own check total is
  itself a finding). Claude reads the script's `--facts` digest, writes
  `findings.json` (attention/info/good; every attention finding pairs
  with a ready-to-send question for the operator — questions, never
  underpayment claims), and fills the emitted payload into the frozen
  `StatementCheckup.jsx` viewer (react-only) as `DATA`/`TITLE`/`TLDR`.
  The doctrine encodes what normal looks like (sales-vs-production
  timing, plant shrink vs NGL lines, regional basis, per-state tax bands,
  young-well decline) so normal gaps reassure rather than alarm. No
  persistence lane — the owner's statement stays in the chat.
- **`well-forecasting/`** — the reservoir-engineer doctrine behind
  `deal_forecast_wells`: reading production history (contamination signatures,
  strike-vs-average), trust judgment by maturity, qi/anchor + the uptime
  factor, Di, b as a population quantity (priors table), the analog
  method (filter-hierarchy analog selection + peak-aligned averaging,
  the population end of a producing↔non-producing continuum), timing for
  undrilled wells, the consequence-echo interrogation, and four worked
  examples. Ported from the benchmark-winning skill in the sibling
  `forecast-benchmark` repo (v3 doctrine, 2026-07-27), adapted for the
  agentic context (run_sql evidence, real echo, cohort entries); analog
  doctrine added 2026-08-11.
  (The deal-sheet template is NOT a skill — it rides in `deal_valuation`'s
  response; see `server/valuation/viewer/`.)

### Prompts (`prompts/`)

LLM-facing text, loaded via `utils/prompts.py` (`load("outer/...")`).
- **`outer/`** — text outer Claude reads: `system_prompt.md` (lead-analyst
  posture, available-data summary) + one docstring per tool
  (`tool_run_sql.md`, `tool_deal_forecast_wells.md`, `tool_deal_valuation.md`,
  `tool_map_render.md`, `tool_get_skill.md`, `tool_dataroom_save_extraction.md`). `compose_outer_system_prompt()`
  assembles `system_prompt.md` + a live skills catalog (built from
  `server/skills.list_skills()`) into the MCP server `instructions`.
- **`outer/shared_schema.md`** — the DB schema reference, kept in sync with
  `utils/schemas.py` by `tests/test_schema_drift.py`. It is appended to the
  **`run_sql` tool description** (`compose_run_sql_doc()`), NOT to the server
  instructions. All SQL guidance — tables, columns, join keys, unit caveats —
  lives in that one docstring; other tool docs point to it rather than
  repeating any of it.

**Prompt delivery channels** (what actually reaches the model — verified
Aug 2026): the MCP *instructions* channel (server system prompt) is
unreliable — claude.ai was observed truncating it at ~2.3 KB (July 2026)
and external reports (anthropics/claude-ai-mcp#131) say claude.ai may drop
it entirely — so nothing load-bearing may live only there, and
`system_prompt.md` keeps its skill-routing section inside the first ~2 KB
as insurance. *Tool descriptions* arrive intact (verified to ~18 KB on a
live client), but tool-search clients defer them: pre-load the model sees
only each description's **first sentence** (search matches full
descriptions, names, and arg docs). Rule: every tool doc's opening
sentence must carry the routing keywords a user's ask would match.

### Shared Utilities (`utils/`)
- **schemas.py** — Single source of truth for queryable DB schemas.
  `WIDGET_SCHEMAS` (widgets, re-run on every render) and `EXPLORATION_SCHEMAS`
  (`run_sql`, adds `shapes`). Drift guard: `tests/test_schema_drift.py`.
- **db.py** — Connection pool (the Crude Code Postgres). `query(sql, params?, schema?,
  statement_timeout_ms?)` returns list of dicts, coerces Decimal → float.
- **sql_guard.py** — Shared SELECT validator + `run_guarded` executor +
  `dry_run`. Validates structure (SELECT/WITH only, single statement, no
  DML/DDL/smuggling/dangerous functions) and schema (defaults to
  `WIDGET_SCHEMAS`; exploration passes `EXPLORATION_SCHEMAS`), then runs with
  `statement_timeout` and row/JSON-size caps.
- **briefing_handle_store.py** — In-memory per-user `BriefingHandleStore`
  mapping short-lived tokens to hydrated specs (24h TTL). `mint(user_slug,
  spec)` / `fetch(user_slug, token)` — synchronous, spec always in hand at
  mint time. Today it serves only map specs, backing `map_render` / `map_read_full`
  (name kept for history, from when it also backed briefings).
- **prompts.py** — Loads `prompts/` files. `compose_outer_system_prompt()`
  assembles `outer/system_prompt.md` + a live skills catalog (no schema —
  the instructions channel is unreliable; see **Prompt delivery channels**
  under Prompts). `compose_run_sql_doc()` assembles
  `outer/tool_run_sql.md` + `outer/shared_schema.md` for the `run_sql`
  tool description.
- **platform.py** — user identity via Supabase (`users`): `resolve_identity`
  maps the `X-User-Slug` header to a user + org context. `_query` for Supabase
  tables (`workspace.*`, `platform.*`).
- **ses.py** — AWS SES team notifications (`send_notification`), destination
  hardwired to `agent@crudecode.dev`. Trimmed port of the pre-rebuild module;
  creds from env with boto3 default-chain fallback.
- **log.py** — centralized file logging with request-ID tracing → `logs/cc.log`.
- **env.py** — shared `.env` loader.
- **run_query.py** — CLI: `echo "SELECT ..." | .venv/bin/python utils/run_query.py`
  (hits `CC_DB_URL`). For Supabase tables use `utils.platform._query`.

### Market data

The platform reads commodity prices from `market.spot_prices` (daily close,
WTI / Brent / Henry Hub) and related `market.*` / `public.*` / `shapes.*` /
`financials.*` tables. Populating those tables (primary-source ingestion) is out
of scope for this repo — point `CC_DB_URL` at a Postgres database whose schema
matches `utils/schemas.py` and `prompts/outer/shared_schema.md`. All ingestion —
state well data *and* the non-state market/financial sources behind `market.*`
and `financials.*` — lives in the **private** sibling repo `data-pipeline` (in
the crudecode-workbench); never copy its connector code into this public repo.

The `market.*` and `financials.*` tables this server reads are a *consumer
surface*: the pipeline lands each source in its own schema and projects onto
these typed tables. Those landing schemas are deliberately outside
`EXPLORATION_SCHEMAS` — `run_sql` sees the projected tables only.

## Running Locally

One-time setup (after cloning): `.venv/bin/pip install -r requirements.txt`
(installs numpy/scipy/pandas and the rest). Then:
```bash
.venv/bin/python server/mcp_server.py &   # MCP on 9000
```
The renderer runs **inside** Claude Desktop, not a browser. To update it:
`cd renderer && npm run build` → `dist/app.html`, then deploy.

Always use `.venv/bin/python`. Never bare `python` / `python3`.

`.env` at repo root needs at least `CC_DB_URL` (legacy name `EI_DB_URL` still
accepted) and `SUPABASE_DATABASE_URL`. `CC_EXPORT_SECRET` (any long random
string) enables signed export links and the deal sheet's download row; without
it the export lane still works, just with short-lived in-memory tickets and no
row on the sheet. Rotating it invalidates every outstanding signed link.

## Deploy

- **Branching.** All work enters through `dev`; `main` only ever receives
  `dev` → `main` merges. Push to `dev` = dev server deploy
  (`mcp-dev.crudecode.dev`); push to `main` = prod deploy. Verify a change
  on the dev server before merging it to `main`. Invariant: everything on
  `main` is also on `dev` — `dev` may run ahead, never behind. The one
  exception: prod is broken *and* `dev` holds unshippable work → fix on
  `main` directly, then merge `main` back into `dev` the same day. Both
  deploy workflows post their outcome to the crude-code Slack channel
  (Notify Slack step; `SLACK_WEBHOOK_URL` repo secret).
- **Releases.** A `dev` → `main` merge is a release: bump `__version__`
  (`server/mcp_server.py`) and `renderer/package.json`'s version together in
  the last dev commit (`npm --prefix renderer version X.Y.Z
  --no-git-tag-version` updates package + lock; lockstep pinned by
  `tests/test_version_drift.py`), then tag `vX.Y.Z` on `main` after the
  merge. The server logs its version at startup (`logs/cc.log`).
- **`deploy.sh`** / **`deploy-dev.sh`** — idempotent scripts run on the host by
  GitHub Actions (`.github/workflows/deploy.yml` / `deploy-dev.yml`) on push to
  `main` / `dev`. Pull, sync the nginx config, publish the deal-sheet
  template and every skill supporting file (content-addressed into
  `/var/www/cc-templates/`, served by the apex vhost at
  `crudecode.dev/templates/` — both scripts publish into the
  same dir; only the prod deploy syncs the apex vhost config), rebuild the
  renderer, and restart the MCP server only when a path it actually loaded
  into memory changed since the last successful deploy (tracked in
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
  auto-skips tests marked `db` (no `CC_DB_URL`), `anthropic` (no
  `ANTHROPIC_API_KEY`), and `network` (no `--run-network`); purges sentinel
  `valuation_runs` rows at session end.
- Coverage spans the live surface: `run_sql` + the valuation tools
  (`deal_forecast_wells` accept-and-echo — validation matrix, cohort allocation,
  merge/overwrite, legacy-stage replay — and `deal_valuation`), the
  calculator (forecast/consequences/econ/artifact-payload/strip), maps,
  `sql_guard`,
  `briefing_handle_store` (map tokens), the dataroom persistence path —
  store, mint tools (`dataroom_save_extraction`, `dataroom_open`), upload
  tokens, HTTP upload handlers (kit, room, echo), room store, CSV
  transport, and the packer round-trip + `--upload` mode against a live
  local HTTP server (`test_extraction_store.py`, `test_tools_dataroom.py`,
  `test_upload_tokens.py`, `test_uploads.py`, `test_room_store.py`,
  `test_extraction_transport.py`, `test_persist_pack.py`), the dataroom
  viewer payload — derived rollups plus the payload ⇄ frozen-template drift
  pin (`test_dataroom_viewer_payload.py`), the export lane
  (`test_exports.py` — CSV assembly, zip assembly and a round-trip that
  unzips what the route actually served, signed-grant round trip plus
  tamper/forge/expiry refusals, the browser-facing download semantics
  including the HTML error page, and two drift guards tying the volume
  columns and the bundle's full column set to the orchestrator's schedule),
  team messages
  (`test_team_messages_store.py`, `test_tools_message_team.py`), and schema
  drift.
