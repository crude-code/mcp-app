"""Energy Insights MCP Server.

Synchronous tool registry — run_sql, forecast_wells, run_valuation, map, get_skill,
plus the renderer-only read tool (get_map_full). No inner agents.
"""

import json as _json
import logging as _logging
import sys
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
from utils.briefing_handle_store import BriefingHandleStore
from utils.schemas import EXPLORATION_SCHEMAS
from utils.sql_guard import GuardError, run_guarded

_briefing_handles = BriefingHandleStore(ttl_seconds=86_400.0)  # 24h

from server.valuation.orchestrator import (
    compose_artifact_payload_for_run, forecast_wells_for_run,
    run_valuation_for_run, AnalogsRequired,
)
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

mcp = FastMCP("Crude Code", instructions=compose_outer_system_prompt())


_app_path = Path(__file__).resolve().parent.parent / "renderer" / "dist" / "app.html"
APP_HTML = _app_path.read_text() if _app_path.exists() else "<html><body><p>App not built. Run: cd renderer && npm run build</p></body></html>"

_app_config_app_only = AppConfig(
    resource_uri="ui://app/view.html",
    visibility=["app"],
)

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


# ── run_sql ────────────────────────────────────────────────────────────────

_run_sql_log = _logging.getLogger("ei.run_sql")
_map_log = _logging.getLogger("ei.map")


@mcp.tool(description=_load_prompt("outer/tool_run_sql.md"))
def run_sql(sql: str, schema: str = "public") -> str:
    """SELECT-only data tool under the shared SQL guard; tighter caps because
    results land in the chat thread."""
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
                row_cap=200,
                size_cap_bytes=100_000,
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


# ── valuation tools (synchronous) ────────────────────────────────────────────

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


if __name__ == "__main__":
    import os as _os

    _port = int(_os.environ.get("MCP_PORT", "9000"))
    mcp.run(transport="http", host="0.0.0.0", port=_port, uvicorn_config={"timeout_graceful_shutdown": 10})
