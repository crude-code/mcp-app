# CrudeCode Refactor — Handoff Doc

**Audience:** Claude Code, executing a structural refactor of the CrudeCode repo (MCP server + renderer).
**Author:** CTO planning session, July 2026.
**Repo state referenced:** the current `mcp_server.py` / `server/valuation/` / `server/maps/` / `renderer/` layout as packed in `repomix-functionality-review.xml`.

---

## 1. The thesis (why this refactor exists)

CrudeCode has been through several iterations (inner agents, pip packages, briefings, IP protection). All of that history is dead. The product is now:

> **CrudeCode is a capability host: a skill server first, wrapped around the compute and surfaces that can't be skills.**

It is the "easy button" for users — connect to one MCP and get always-current skills plus functionality that's hard to do locally, instead of downloading skills from a website or installing code from GitHub.

- **Free and open source.** The hosted product runs against our warehouse; self-hosters point the same code at their own Postgres (`EI_DB_URL`). The data is the hosted offering's value; the code is identical everywhere.
- **Every component must have a one-sentence justification:**
  - Skills deliver always-current instructions (vs. download/upload).
  - Compute modules do deterministic, warehouse-backed work Claude can't do in its sandbox.
  - The renderer exists **solely** because maps are impossible in the artifact sandbox (no tile fetching).
  - Core hosts and guards.
- Anything that can't produce a sentence like that gets deleted.

## 2. The taxonomy (write this into CLAUDE.md)

Three capability types on one axis — how much the server does vs. how much Claude does:

| | **Skill** (dataroom-extract) | **Compute module** (valuation) | **Surface module** (maps) |
|---|---|---|---|
| Who computes | Claude, in its sandbox | Server (deterministic engine) | Server (hydrate SQL → GeoJSON) |
| Who presents | Frozen JSX viewer, Claude pastes data in | Frozen JSX viewer, Claude pastes data in | Module's own iframe app |
| What MCP delivers | Instructions + files | Data + viewer template | Token + rendering surface |
| Data source | User's upload | Warehouse | Warehouse |

**Decision path for any future capability (e.g. production accounting):**
1. *Who has the data?* User brings it → skill. Warehouse → module.
2. *Can an artifact render it?* Yes → compute module with a frozen viewer. No → surface module.

**The surface-module bar (write verbatim into CLAUDE.md):** a new surface module is justified only when the capability is **impossible** as a claude.ai artifact (browser APIs / network access the artifact sandbox cannot provide) — not merely nicer. Maps passes (MapLibre tile fetching). Nothing else currently does.

The frozen-viewer pattern (finished component + injected data, never rebuilt by Claude) is one shared presentation mechanism used by both skills and compute modules. Valuation is not a third architecture — it's a compute module borrowing the skill's presentation trick.

## 3. Target repo structure

```
crudecode/
├── core/                          # the host — modules import from core, never the reverse
│   ├── __init__.py                # explicit public API exports
│   ├── server.py                  # FastMCP bootstrap + module loader (~50 lines + loader)
│   ├── sql_guard.py               # from utils/sql_guard.py
│   ├── identity.py                # resolve_identity behind a swappable interface
│   ├── stores/
│   │   ├── handles.py             # BriefingHandleStore → generic HandleStore (maps: map_token)
│   │   └── runs.py                # ValuationRunStore → generic RunStore (valuation: run_id)
│   ├── schemas.py                 # EXPLORATION_SCHEMAS + schema-contract docs loader
│   ├── prompts.py                 # system-prompt composition from module fragments
│   ├── log.py
│   ├── skills.py                  # catalog + bundle loader (today's server/skills.py, unchanged logic)
│   └── tools/
│       ├── run_sql.py
│       └── get_skill.py
│
├── modules/
│   ├── valuation/                 # compute archetype (reference implementation)
│   │   ├── manifest.py
│   │   ├── tools.py               # forecast_wells, run_valuation, export_valuation_xlsx
│   │   ├── engine/                # orchestrator, routing, econ, deal_sheet, export_xlsx, config
│   │   ├── viewer/
│   │   │   └── DealSheetViewer.jsx   # NEW — frozen viewer (see §6)
│   │   ├── prompts/               # tool_forecast_wells.md, tool_run_valuation.md,
│   │   │                          #   tool_export_valuation_xlsx.md, available_data fragment
│   │   └── tests/                 # includes test_valuation_defaults_drift.py
│   └── maps/                      # surface archetype (reference implementation)
│       ├── manifest.py            # declares surface: ui:// URI + CSP + get_map_full
│       ├── tools.py               # map, get_map_full (renderer-only companion)
│       ├── engine/                # spec.py, hydrate.py
│       ├── surface/
│       │   └── MapView.tsx        # conceptually owned here; built into renderer bundle
│       ├── prompts/               # tool_map.md
│       └── tests/
│
├── skills/                        # delivered via get_skill — already plug-and-play
│   └── dataroom-extract/
│       ├── SKILL.md
│       ├── DataroomViewer.jsx     # frozen viewer (already exists)
│       └── (schema.py, example.json, triage.py, …)
│
├── renderer/                      # "the map app" — nothing else
│   └── src/                       # EIApp (one route), MapView, ErrorBoundary, map preview fixture
│
├── prompts/
│   └── system_prompt.md           # voice/framing/workflow only; tool docs + "Available data"
│                                  #   sections are composed from module fragments at startup
├── tests/                         # core tests only; module tests live with modules
├── CLAUDE.md                      # rewrite to reflect this doc: thesis, taxonomy, surface bar
└── README.md
```

**Import rules (enforce, e.g. with import-linter):**
- `modules/*` import from `core`'s public API only.
- `core` never imports from `modules`.
- Modules never import from each other.
- No pip packaging of modules. Monorepo folder discovery only. (The pip approach was tried in the managed-agents era and removed; do not reintroduce.)

## 4. The kill list

Delete outright — **briefings are dead**:

- `run_data_analysis` tool and everything behind it: `utils/hydrate.py` (hydrate_spec, validate_widget_queries), `utils/briefing_spec.py`, `utils/agent_results.py` (AgentResultStore — only briefings needed durable reopening).
- Renderer-only briefing tools: `get_briefing_full`, `get_briefing_by_run`, and the `ui://app/briefing.html` resource.
- Prompts: `prompts/outer/tool_run_data_analysis.md`, `prompts/outer/widget_palette.md`.
- Renderer components: `SpecSurface.tsx`, `widgets.tsx` (SpecRenderer), `AgentContainer.tsx` / AgentChrome, `DealSheet.tsx`, `EconPanel.tsx`, `AssetPanel.tsx`, `ProductionPanel.tsx`, `AdvancedView.tsx`, `valuationUI.tsx`, the `TOOL_AGENTS` map in `EIApp.tsx`, briefing/deal-sheet fixtures, and the briefing scenarios in `preview.tsx`. (The deal-sheet components are briefing-era leftovers — valuation renders as a claude.ai artifact, not in the iframe.)
- Any remaining inner-agent-era references (`AgentResultStore`, "data_analyst"/"Valuation Analyst" naming, `_analyst_log`, agent copy in the renderer).

After the cut, `EIApp` routes exactly one tool (`map`) to exactly one component (`MapView`).

## 5. The manifest + loader contract

Each module ships a `manifest.py` declaring everything it contributes. Keep it boring — a Python dict, not a DSL:

```python
# modules/valuation/manifest.py
from .tools import forecast_wells, run_valuation, export_valuation_xlsx

MODULE = {
    "name": "valuation",
    "core_api_version": 1,                    # checked at load; escape hatch for evolving core
    "tools": [
        {"fn": forecast_wells,        "prompt": "prompts/tool_forecast_wells.md"},
        {"fn": run_valuation,         "prompt": "prompts/tool_run_valuation.md"},
        {"fn": export_valuation_xlsx, "prompt": "prompts/tool_export_valuation_xlsx.md",
         "renderer_only": True},
    ],
    "system_prompt_fragment": "prompts/available_data.md",   # composed into system prompt
    "required_schemas": ["public"],           # warn/skip gracefully if a self-hoster lacks one
    "viewer": "viewer/DealSheetViewer.jsx",   # optional — frozen artifact viewer
    "surface": None,
}
```

```python
# modules/maps/manifest.py
MODULE = {
    "name": "maps",
    "core_api_version": 1,
    "tools": [
        {"fn": render_map,   "prompt": "prompts/tool_map.md"},
        {"fn": get_map_full, "renderer_only": True},
    ],
    "system_prompt_fragment": None,
    "required_schemas": ["public", "shapes"],
    "viewer": None,
    "surface": {
        "resource_uri": "ui://app/map.html",
        "csp": {
            "connectDomains":  ["https://*.openstreetmap.org"],
            "resourceDomains": ["https://*.openstreetmap.org"],
        },
    },
}
```

The loader in `core/server.py` (~80–100 lines) at startup:

1. Iterate `modules/` (sorted), import each `manifest.MODULE`.
2. Check `core_api_version`; refuse to load on mismatch with a clear error.
3. Check `required_schemas` against the connected DB; log a warning and skip the module (or degrade) if missing — a self-hoster without our `features` schema must get a clear message, not mystery SQL errors.
4. Register each tool with FastMCP, loading its `.md` prompt as the description; `renderer_only` tools get the app-scoped `AppConfig`.
5. Register the `surface` (ui:// resource serving `dist/app.html` + CSP meta) if declared.
6. Collect `system_prompt_fragment`s and compose into the system prompt (voice/framing from `prompts/system_prompt.md` + module fragments).

Result: `mcp_server.py`'s hand-wiring is replaced entirely. Adding production accounting = drop a folder in `modules/`, restart.

## 6. Valuation viewer (new work, not just a move)

Today `tool_run_valuation.md` instructs Claude to build the deal-sheet artifact freehand ("no fixed layout to follow"). Replace this with the dataroom pattern:

- Build **`modules/valuation/viewer/DealSheetViewer.jsx`** — a single, finished React component (react + recharts + lucide-react only; claude.ai artifact sandbox constraints). It renders the full `data` payload: `facts` (deal type, interest, operator, area), the net production/cashflow chart when `data.production` is non-null, and `economics.npv_at_centers` (total + by_status).
- `run_valuation`'s response includes the viewer source alongside `data` (per the manifest `viewer` key), and the tool prompt changes to: **paste `data` into the viewer; do not rebuild or redesign it; do not omit or invent fields.**
- This eliminates the freehand-artifact failure modes the current prompt warns against (omitted fields, invented numbers, inconsistent layouts).

## 7. Contracts for self-hosters

The hosted product runs against our warehouse; the open-source story is "bring your own Postgres." Two boundaries must be explicit:

- **Schema contract.** `core/schemas.py` + a documented schema reference define what the DB must look like (today's `utils/schemas.py` + `prompts/inner/shared_schema.md`). Module manifests declare `required_schemas`; the loader degrades gracefully when one is absent.
- **Identity contract.** `X-User-Slug` + Supabase resolution is *our hosting infrastructure*, not the product. Put `resolve_identity` behind a small interface in `core/identity.py` with a **single-user localhost default** requiring no Supabase. Deployment-specific things (Supabase URL, Sentry DSN, DB URLs) live in config/env, never in code.

## 8. Migration order

Each step leaves the server runnable:

1. **Kill briefings** (§4). Biggest simplification; do it first so nothing dead gets migrated.
2. **Carve out `core/`** from `utils/` + the generic parts of `mcp_server.py`. Generalize `BriefingHandleStore` → `HandleStore`, `ValuationRunStore` → `RunStore`. Add the identity interface + single-user default. Define `core/__init__.py` public API.
3. **Write the manifest contract + loader** (§5), including `core_api_version` and `required_schemas` checks.
4. **Migrate valuation** into `modules/valuation/` (the hard one: RunStore usage, renderer-only xlsx tool, prompts). Zero core → module imports when done.
5. **Migrate maps** into `modules/maps/` (proves the surface path: ui:// resource, CSP, `get_map_full`, HandleStore).
6. **Slim the renderer** to EIApp/MapView/ErrorBoundary + map preview fixture. Remove TOOL_AGENTS routing in favor of the single map route (a declarative surface registry can come later — hardcoding one entry is fine).
7. **Build `DealSheetViewer.jsx`** and rewrite `tool_run_valuation.md`'s artifact section (§6).
8. **Split prompts**: tool docs into module `prompts/`; "Available data" becomes module fragments; `system_prompt.md` shrinks to voice/framing/workflow (keep the assumptions-grid and zero-cost-trap guidance with the valuation module's prompts).
9. **Rewrite CLAUDE.md** around this doc: thesis, taxonomy table, decision path, surface bar, module contract, self-hoster contracts.
10. **CI**: run `modules/*/tests` + core tests; add import-linter rules from §3.

## 9. Explicitly out of scope (do not do)

- No pip packaging or independent versioning of modules.
- No new surface modules; no re-expanding the renderer.
- No skill-ifying the valuation engine (it needs determinism + warehouse access). Mitigate Claude-blindness instead: engine source is in the open repo, methodology documented in prompt fragments, tool outputs stay explanatory (fit stats, classification reasons, `spectrum`).
- No changes to the dataroom-extract skill (it's the reference skill; already correct).
- Deferred hardening items noted in review (proxy↔server auth secret, sanitized error strings, server-side zero-capex guard, in-memory store durability) — real, but separate work; don't bundle into this refactor. Exception: don't make the store situation *worse* while generalizing them.