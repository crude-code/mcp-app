"""Energy Insights MCP Server.

Synchronous tool registry — run_sql, run_data_analysis, forecast_wells,
run_valuation, map, plus the renderer-only read
tools (get_briefing_full, get_briefing_by_run, get_map_full). No inner agents.
"""

import base64 as _b64
import json as _json
import logging as _logging
import sys
import uuid as _uuid
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent

from fastmcp import FastMCP
from fastmcp.server.apps import AppConfig
from fastmcp.server.dependencies import get_http_request

# Add repo root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from utils.log import setup as _log_setup, trace
from utils.platform import resolve_identity
from utils.prompts import compose_outer_system_prompt, load as _load_prompt
from utils.agent_results import AgentResultStore
from utils.briefing_handle_store import BriefingHandleStore
from utils.hydrate import hydrate_spec, validate_widget_queries
from utils.schemas import EXPLORATION_SCHEMAS
from utils.sql_guard import GuardError, run_guarded

_briefing_handles = BriefingHandleStore(ttl_seconds=86_400.0)  # 24h
_agent_results = AgentResultStore()

from server.valuation.run_record import ValuationRunStore
_valuation_store = ValuationRunStore()

from server.valuation.orchestrator import (
    compose_artifact_payload_for_run, forecast_wells_for_run,
    run_valuation_for_run, AnalogsRequired,
)
from server.valuation.export_xlsx import build_workbook_bytes, export_filename, ExportError
from server.valuation.deal_sheet import roll_up_facts
from server.valuation import config as _vconfig
from server.maps.spec import parse_map_spec, MapSpecError
from server.maps.hydrate import hydrate_map, MapHydrateError
from server.skills import list_skills, load_skill, SkillNotFound


_log_setup()


# Sentry — exceptions in server code get reported with traceback + request
# context. No-op if SENTRY_DSN_PYTHON is unset, so unconfigured dev boxes
# stay silent.
import os as _os
import sentry_sdk
_SENTRY_DSN = _os.environ.get("SENTRY_DSN_PYTHON")
if _SENTRY_DSN:
    sentry_sdk.init(
        dsn=_SENTRY_DSN,
        traces_sample_rate=0.0,       # errors only for beta — no perf sampling
        send_default_pii=False,
        environment=_os.environ.get("SENTRY_ENV", "production"),
    )


def get_current_identity() -> dict | None:
    """Get the current user/org identity from the HTTP request header."""
    try:
        request = get_http_request()
        slug = request.headers.get("x-user-slug", "")
        if not slug:
            return None
        identity = resolve_identity(slug)
        if _SENTRY_DSN and identity:
            sentry_sdk.set_user({"username": slug})
        return identity
    except RuntimeError:
        return None


# ── MCP Server ───────────────────────────────────────────────────────────────

mcp = FastMCP("EnergyInsights", instructions=compose_outer_system_prompt())

from utils.briefing_spec import validate_briefing_spec   # noqa: E402


_app_path = Path(__file__).resolve().parent.parent / "renderer" / "dist" / "app.html"
APP_HTML = _app_path.read_text() if _app_path.exists() else "<html><body><p>App not built. Run: cd renderer && npm run build</p></body></html>"

_app_config_app_only = AppConfig(
    resource_uri="ui://app/view.html",
    visibility=["app"],
)

# Per-agent UI resources — each tool that should render its own inline
# block in the chat thread points at a distinct ui:// URI (same bundle,
# different resource so the host doesn't pool by URI).
_app_config_data_analyst = AppConfig(resource_uri="ui://app/briefing.html")


@mcp.resource("ui://app/briefing.html")
def briefing_view() -> str:
    """Serve the Energy Insights app for data_analyst renders.

    Same bundle as `app_view` — distinct URI so the host renders a new
    inline iframe per data_analyst tool call.
    """
    return APP_HTML


_app_config_map = AppConfig(resource_uri="ui://app/map.html")


@mcp.resource("ui://app/map.html", meta={"ui": {"csp": {
    "connectDomains":  ["https://*.openstreetmap.org"],
    "resourceDomains": ["https://*.openstreetmap.org"],
}}})
def map_view() -> str:
    """Serve the Crude Code app for `map` tool renders.

    Distinct URI so the host renders a fresh iframe per map call. The CSP meta
    whitelists OpenStreetMap tile fetches (the iframe blocks them otherwise) —
    this is the only resource that needs it.
    """
    return APP_HTML


_analyst_log = _logging.getLogger("ei.data_analyst")


# Widget fields stripped before returning a briefing to outer Claude. These
# are the bulky hydrated payloads (tables, chart series, sparkline arrays).
# Structure (type/label/code/query) + summary fields (value/delta) are kept
# so Claude can answer interpretive follow-ups without re-calling.
_STRIP_WIDGET_FIELDS = ("data", "rows", "sparkline", "cube", "production")


def _harvest_queries(spec: dict) -> list[str]:
    """Flat list of SQL strings from the pre-hydration spec (hydration pops them)."""
    queries: list[str] = []
    for section in spec.get("sections", []):
        for w in section.get("widgets", []):
            q = w.get("query")
            if isinstance(q, str) and q:
                queries.append(q)
    return queries


def _strip_widget_payloads(sections: list) -> list:
    """Shallow-copy sections with bulky widget payloads removed."""
    out = []
    for section in sections:
        widgets_out = [
            {k: v for k, v in w.items() if k not in _STRIP_WIDGET_FIELDS}
            for w in section.get("widgets", [])
        ]
        out.append({**section, "widgets": widgets_out})
    return out




# ── run_sql ────────────────────────────────────────────────────────────────

_run_sql_log = _logging.getLogger("ei.run_sql")
_map_log = _logging.getLogger("ei.map")


@mcp.tool(description=_load_prompt("outer/tool_run_sql.md"))
def run_sql(sql: str, schema: str = "public") -> str:
    """Outer Claude's SELECT-only data tool. Same guard as the inner agent
    plugin, but with a tighter row cap because results land in the chat
    thread."""
    identity = get_current_identity()
    if not identity:
        return _json.dumps({"error": "Could not identify user"})

    user_slug = identity["user_slug"]

    if not sql or not sql.strip():
        return _json.dumps({"error": "sql is required"})

    with trace("run_sql", user=user_slug):
        try:
            result = run_guarded(
                sql,
                schema=schema,
                allowed_schemas=EXPLORATION_SCHEMAS,
                row_cap=50,
                size_cap_bytes=50_000,
            )
        except GuardError as e:
            return _json.dumps({"error": str(e)})
        except Exception as e:
            _run_sql_log.error("run_sql failed: %s", e)
            return _json.dumps({"error": str(e)})

        return _json.dumps(
            {"rows": result["rows"], "count": result["count"]},
            default=str,
        )


# ── get_skill ────────────────────────────────────────────────────────────────

_get_skill_log = _logging.getLogger("ei.get_skill")


@mcp.tool(description=_load_prompt("outer/tool_get_skill.md"))
def get_skill(name: str = "") -> str:
    """Return a packaged skill bundle (instructions + files), or the catalog
    when called with no/unknown name. Static repo files — no DB or identity."""
    try:
        if not name or not name.strip():
            return _json.dumps({"available_skills": list_skills()})
        try:
            return _json.dumps(load_skill(name.strip()))
        except SkillNotFound:
            return _json.dumps({"available_skills": list_skills()})
    except Exception as e:
        _get_skill_log.error("get_skill failed: %s", e)
        return _json.dumps({"error": str(e)})


# ── map ────────────────────────────────────────────────────────────────────


@mcp.tool(name="map", app=_app_config_map, description=_load_prompt("outer/tool_map.md"))
def render_map(spec: dict) -> str:
    """Synchronous map render. Validate -> hydrate -> mint handle -> summary."""
    identity = get_current_identity()
    if not identity:
        return _json.dumps({"error": "Could not identify user"})
    user_slug = identity["user_slug"]

    with trace("map", user=user_slug):
        try:
            parsed = parse_map_spec(spec)
            hydrated = hydrate_map(parsed)
        except (MapSpecError, MapHydrateError) as e:
            return _json.dumps({"error": str(e)})
        except Exception as e:  # noqa: BLE001 — DB errors surface here too
            _map_log.error("map failed: %s", e)
            return _json.dumps({"error": str(e)})

        token = _briefing_handles.mint(user_slug=user_slug, spec=hydrated)
        return _json.dumps({
            "surface": "map",
            "map_token": token,
            "title": hydrated["title"],
            "layers": [
                {"id": layer["id"], "label": layer["label"], "feature_count": layer["feature_count"]}
                for layer in hydrated["layers"]
            ],
            "static_layers": [s["id"] for s in hydrated["static_layers"]],
        }, default=str)


@mcp.tool(
    name="get_map_full",
    app=_app_config_app_only,
    description="INTERNAL — Crude Code app only. Returns the full hydrated map spec for a map_token.",
)
def get_map_full(token: str) -> str:
    """Renderer-only, non-blocking full-spec fetch from the handle store."""
    identity = get_current_identity()
    if not identity:
        return _json.dumps({"error": "Could not identify user"})
    user_slug = identity["user_slug"]
    spec = _briefing_handles.fetch(user_slug=user_slug, token=token)
    if spec is None:
        return _json.dumps({"error": "unknown or expired token"})
    return _json.dumps({"spec": spec}, default=str)


# ── valuation tools (synchronous; the inner agent is retired in Plan 3) ──────

@mcp.tool(description=_load_prompt("outer/tool_forecast_wells.md"))
def forecast_wells(groups: list[dict], run_id: str | None = None) -> str:
    """Classify + forecast wells grouped by area. See prompts/outer/tool_forecast_wells.md."""
    identity = get_current_identity()
    if not identity:
        return _json.dumps({"error": "Could not identify user"})
    user_id = identity["user_id"]
    with trace("forecast_wells", user=identity["user_slug"]):
        try:
            result = forecast_wells_for_run(run_id=run_id, groups=groups, user_id=user_id)
        except AnalogsRequired as e:
            return _json.dumps({
                "error": "analogs_required",
                "needs_analogs": e.needs_analogs,
                "message": ("These wells can't be forecast from their own history. "
                            "Find analogs (same formation, comparable lateral, nearby, "
                            "real producers with enough history) with run_sql and call "
                            "forecast_wells again."),
            })
        except Exception as e:  # noqa: BLE001
            return _json.dumps({"error": str(e)})
        return _json.dumps(result, default=str)


@mcp.tool(description=_load_prompt("outer/tool_run_valuation.md"))
def run_valuation(run_id: str, params: dict) -> str:
    """Union forecasts → econ → slim artifact payload. See prompts/outer/tool_run_valuation.md."""
    identity = get_current_identity()
    if not identity:
        return _json.dumps({"error": "Could not identify user"})
    user_slug = identity["user_slug"]
    with trace("run_valuation", user=user_slug):
        try:
            run_valuation_for_run(run_id=run_id, params=params)
            data = compose_artifact_payload_for_run(run_id)
            return _json.dumps({
                "surface": "deal_sheet_artifact",
                "run_id": run_id,
                "data": data,
            }, default=str)
        except Exception as e:  # noqa: BLE001
            return _json.dumps({"error": str(e)})


# ── data-analysis tool (synchronous; the inner agent is retired in Plan 3) ──

@mcp.tool(app=_app_config_data_analyst, description=_load_prompt("outer/tool_run_data_analysis.md"))
def run_data_analysis(spec: dict) -> str:
    """Validate → hydrate → persist a Claude-authored briefing spec.

    Synchronous replacement for the data_analyst agent: Claude already did the
    analysis with run_sql and authored the full spec; the server only validates,
    fills widget data, persists, and returns the summary. See
    prompts/outer/tool_run_data_analysis.md.
    """
    identity = get_current_identity()
    if not identity:
        return _json.dumps({"error": "Could not identify user"})
    user_slug = identity["user_slug"]
    user_id = identity["user_id"]

    with trace("run_data_analysis", user=user_slug):
        if not isinstance(spec, dict):
            return _json.dumps({"error": "spec must be a JSON object"})

        # 1. Shape validation — structured error in-turn so Claude fixes & recomposes.
        try:
            clean = validate_briefing_spec(spec)
        except (ValueError, TypeError, KeyError, AttributeError) as e:
            return _json.dumps({"error": "invalid spec", "details": str(e)})

        # 2. Widget-query dry-run — same defense-in-depth as the legacy persist hook.
        widget_errors = validate_widget_queries(clean)
        if widget_errors:
            return _json.dumps({
                "error": "widget query validation failed",
                "message": (
                    "one or more widget queries failed to plan against the "
                    "database. Fix the queries listed under `widgets` and call "
                    "run_data_analysis again — nothing is consumed on failure."
                ),
                "widgets": widget_errors,
            })

        # 3. Harvest queries (hydration pops them), hydrate, stash for the summary.
        queries = _harvest_queries(clean)
        try:
            hydrated = hydrate_spec(clean)
        except Exception as e:  # noqa: BLE001
            return _json.dumps({"error": f"hydration failed: {e}"})
        hydrated["_queries"] = queries

        # 4. Persist: ephemeral handle (renderer reads via get_briefing_full) +
        #    durable agent_results row (reopen after the 24h token TTL).
        token = _briefing_handles.mint(user_slug=user_slug, spec=hydrated)
        result_id = str(_uuid.uuid4())
        try:
            _agent_results.save(
                run_id=result_id,
                agent_type="data_analyst",
                user_id=user_id,
                spec=hydrated,
            )
        except Exception as e:  # noqa: BLE001
            _analyst_log.warning("agent_results.save failed: %s", e)

        # 5. Return the compact summary outer Claude narrates from (same shape
        #    get_briefing returns today).
        return _json.dumps(_briefing_summary(token=token, spec=hydrated), default=str)


_briefing_log = _logging.getLogger("ei.briefing")


@mcp.tool(
    app=_app_config_app_only,
    description="INTERNAL — for the Crude Code MCP app only. Returns the FULL hydrated spec (unstripped) the renderer needs to render widgets.",
)
def get_briefing_full(token: str) -> str:
    """Renderer-only full-spec fetch. Plan-3 specs are persisted synchronously
    by run_data_analysis / run_valuation before the token reaches Claude, so the
    handle store is always populated by read time — no event buffer, no waiting."""
    identity = get_current_identity()
    if not identity:
        return _json.dumps({"error": "Could not identify user"})
    user_slug = identity["user_slug"]
    spec = _briefing_handles.fetch(user_slug=user_slug, token=token)
    if spec is None:
        return _json.dumps({"error": "unknown or expired token"})
    return _json.dumps({"spec": spec}, default=str)


@mcp.tool(
    app=_app_config_app_only,
    description="INTERNAL — for the Crude Code MCP app only. Returns the durable, restart-surviving briefing spec for a run by its run_id (used to re-render a reopened card). Non-blocking.",
)
def get_briefing_by_run(run_id: str) -> str:
    """Renderer-only durable fetch. Unlike get_briefing_full (in-memory, by
    ephemeral token, blocks on the live run), this reads the saved spec from
    platform.agent_results by the durable run_id and never blocks — a reopened
    card has nothing to wait for. User-scoped: a run_id belonging to another
    user resolves to None -> error."""
    identity = get_current_identity()
    if not identity:
        return _json.dumps({"error": "Could not identify user"})
    user_id = identity["user_id"]
    try:
        spec = _agent_results.get(run_id=run_id, user_id=user_id)
    except Exception as e:
        _briefing_log.warning("get_briefing_by_run failed: %s", e)
        return _json.dumps({"error": "lookup failed"})
    if spec is None:
        return _json.dumps({"error": "not found"})
    return _json.dumps({"spec": spec}, default=str)


@mcp.tool(
    app=_app_config_app_only,
    description=_load_prompt("outer/tool_export_valuation_xlsx.md"),
)
def export_valuation_xlsx(run_id: str) -> str:
    """Renderer-only: build the editable Excel model for a completed run."""
    identity = get_current_identity()
    if not identity:
        return _json.dumps({"error": "Could not identify user"})
    user_id = identity["user_id"]
    with trace("export_valuation_xlsx", user=identity["user_slug"]):
        try:
            rec = _valuation_store.get(run_id)
            if not rec or rec.get("user_id") != user_id:
                return _json.dumps({"error": "unknown run"})
            economics = rec.get("economics")
            wells = rec.get("wells")
            if not economics or not wells:
                return _json.dumps({"error": "run has no economics yet"})
            if isinstance(economics, str):
                economics = _json.loads(economics)
            if isinstance(wells, str):
                wells = _json.loads(wells)
            interest = economics.get("interest") or {}
            rate_centers = economics.get("rate_centers") or _vconfig.resolve_rate_centers(None)
            facts, _ = roll_up_facts(wells.get("well_meta", {}), interest, rate_centers)
            data = build_workbook_bytes(run_id, economics, wells, facts)
            return _json.dumps({
                "filename": export_filename(facts, run_id),
                "xlsx_base64": _b64.b64encode(data).decode(),
            })
        except ExportError as e:
            return _json.dumps({"error": str(e)})
        except Exception as e:  # noqa: BLE001
            return _json.dumps({"error": str(e)})


def _briefing_summary(*, token: str, spec: dict) -> dict:
    """Build the summary payload outer Claude reads to narrate the result.

    Same shape data_analyst returned synchronously before async-return.
    Prefers spec["_queries"] (harvested pre-hydration) over harvesting now —
    hydrated specs no longer carry per-widget `query` strings.
    """
    return {
        "surface":        "briefing",
        "briefing_token": token,
        "kind":           spec.get("kind"),
        "headline":       spec.get("headline"),
        "tldr":           spec.get("tldr"),
        "sections":       _strip_widget_payloads(spec.get("sections", [])),
        "queries":        spec.get("_queries") or _harvest_queries(spec),
        "reason":         spec.get("reason"),
        "clarify_ask":    spec.get("clarify_ask"),
    }


if __name__ == "__main__":
    import os as _os

    _port = int(_os.environ.get("MCP_PORT", "9000"))
    mcp.run(transport="http", host="0.0.0.0", port=_port, uvicorn_config={"timeout_graceful_shutdown": 10})
