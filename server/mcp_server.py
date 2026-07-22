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
from utils.prompts import (
    compose_outer_system_prompt,
    compose_run_sql_doc,
    load as _load_prompt,
)
from utils.briefing_handle_store import BriefingHandleStore
from utils.schemas import EXPLORATION_SCHEMAS
from utils.sql_guard import GuardError, run_guarded

_briefing_handles = BriefingHandleStore(ttl_seconds=86_400.0)  # 24h

from server.valuation.orchestrator import (
    compose_artifact_payload_for_run, forecast_wells_for_run,
    run_valuation_for_run, AnalogsRequired,
)
from server.valuation.routing import AnalogRequired
from server.valuation.artifact_payload import load_viewer

# Frozen deal-sheet artifact template, shipped in every run_valuation response
# so the template Claude fills always matches the payload contract that
# produced `data`.
_DEAL_SHEET_VIEWER = load_viewer()
from server.maps.spec import parse_map_spec, MapSpecError
from server.maps.hydrate import hydrate_map, MapHydrateError
from server.skills import list_skills, load_skill, SkillNotFound
from server.extraction_store import ExtractionStore
from server.extraction_transport import (
    TransportError, entity_counts, unpack_extraction,
)
from server.team_messages import CATEGORIES as MESSAGE_CATEGORIES, TeamMessageStore
from utils.ses import send_notification

_extraction_store = ExtractionStore()
_team_messages = TeamMessageStore()


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


def get_request_slug() -> str:
    """User slug straight from the routing header — no DB round-trip, so
    identity-free tools (get_skill) can still attribute their log lines."""
    try:
        return get_http_request().headers.get("x-user-slug", "") or "unknown"
    except RuntimeError:
        return "unknown"


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


@mcp.tool(description=compose_run_sql_doc())
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
    when called with no/unknown name. Static repo files — no DB or identity
    resolution; the trace user comes straight from the routing header."""
    requested = (name or "").strip()
    with trace("get_skill", user=get_request_slug(), skill=requested or "catalog"):
        try:
            if not requested:
                return _json.dumps({"available_skills": list_skills()})
            try:
                return _json.dumps(load_skill(requested))
            except SkillNotFound:
                return _json.dumps({"available_skills": list_skills()})
        except Exception as e:
            _get_skill_log.error("get_skill failed: %s", e)
            return _json.dumps({"error": str(e)})


# ── save_dataroom_extraction ─────────────────────────────────────────────────

_save_extraction_log = _logging.getLogger("ei.save_dataroom_extraction")

# Generous vs. a typical extraction.json (tens of KB), but a hard stop before
# someone stores a whole parsed dataroom as one row.
_MAX_EXTRACTION_BYTES = 2_000_000


@mcp.tool(description=_load_prompt("outer/tool_save_dataroom_extraction.md"))
def save_dataroom_extraction(extraction: dict, label: str = "", extraction_id: str = "",
                             production_csv: str = "", revenue_csv: str = "",
                             sources: dict | None = None) -> str:
    """Persist a dataroom-extract ExtractionResult; the two tall tables may
    arrive CSV-packed (persist_pack.py kit) and are expanded back to the
    canonical shape before storage. Insert on first save, user-scoped
    overwrite when extraction_id is supplied. Echoes stored entity counts."""
    identity = get_current_identity()
    if not identity:
        return _json.dumps({"error": "Could not identify user"})

    with trace("save_dataroom_extraction", user=identity["user_slug"]):
        if not isinstance(extraction, dict) or not extraction:
            return _json.dumps({"error": "extraction must be the non-empty ExtractionResult object"})

        try:
            full = unpack_extraction(
                extraction,
                production_csv=production_csv or "",
                revenue_csv=revenue_csv or "",
                sources=sources,
            )
        except TransportError as e:
            return _json.dumps({"error": str(e)})

        size = len(_json.dumps(full).encode())
        if size > _MAX_EXTRACTION_BYTES:
            return _json.dumps({"error": f"extraction too large ({size} bytes; cap {_MAX_EXTRACTION_BYTES})"})

        clean_label = (label or "").strip()
        try:
            eid = _extraction_store.save(
                user_id=identity["user_id"],
                extraction=full,
                label=clean_label,
                extraction_id=extraction_id.strip() or None,
            )
        except (ValueError, LookupError) as e:
            return _json.dumps({"error": str(e)})
        except Exception as e:
            _save_extraction_log.error("save_dataroom_extraction failed: %s", e)
            return _json.dumps({"error": str(e)})

        stored = entity_counts(full)
        _save_extraction_log.info(
            "stored %s label=%r bytes=%d", stored, clean_label, size
        )
        return _json.dumps({
            "extraction_id": eid,
            "label": clean_label,
            "saved": True,
            "stored": stored,
        })


# ── message_team ─────────────────────────────────────────────────────────────

_message_team_log = _logging.getLogger("ei.message_team")

# Per-user cap: enough for a rough session, a stop on a runaway loop.
_MESSAGE_RATE_CAP = 10          # per window
_MESSAGE_RATE_WINDOW_MIN = 60


@mcp.tool(description=_load_prompt("outer/tool_message_team.md"))
def message_team(subject: str, body: str, category: str = "other",
                 context: dict | None = None) -> str:
    """File a user message to the Crude Code team: durable row first
    (platform.team_messages), then best-effort SES email to the team
    mailbox. Destination is hardwired — never a general email capability."""
    identity = get_current_identity()
    if not identity:
        return _json.dumps({"error": "Could not identify user"})

    with trace("message_team", user=identity["user_slug"], category=category):
        clean_subject = (subject or "").strip()
        clean_body = (body or "").strip()
        if not clean_subject or not clean_body:
            return _json.dumps({"error": "subject and body are both required"})
        if category not in MESSAGE_CATEGORIES:
            return _json.dumps({"error": f"category must be one of {sorted(MESSAGE_CATEGORIES)}"})

        try:
            if _team_messages.count_recent(
                identity["user_id"], minutes=_MESSAGE_RATE_WINDOW_MIN,
            ) >= _MESSAGE_RATE_CAP:
                return _json.dumps({"error": (
                    f"rate limit: more than {_MESSAGE_RATE_CAP} messages in "
                    f"{_MESSAGE_RATE_WINDOW_MIN} minutes — batch further items "
                    "into one message or wait"
                )})
            message_id = _team_messages.save(
                user_id=identity["user_id"],
                category=category,
                subject=clean_subject,
                body=clean_body,
                context=context or None,
            )
        except Exception as e:
            _message_team_log.error("message_team store failed: %s", e)
            return _json.dumps({"error": str(e)})

        # Best-effort email — the row above is the record; a mail hiccup must
        # never read as a failed filing.
        user_email = identity.get("user_email") or "unknown"
        tagged_subject = f"[{category}] [{user_email}] {clean_subject}"
        tagged_body = (
            f"From: {identity.get('user_name') or 'Unknown'} <{user_email}>\n"
            f"Org: {identity.get('org_name') or 'Unknown'}\n"
            f"Message-ID: {message_id}\n"
            + (f"Context: {_json.dumps(context)}\n" if context else "")
            + f"\n---\n\n{clean_body}"
        )
        email_sent = False
        try:
            send_notification(tagged_subject, tagged_body)
            _team_messages.mark_emailed(message_id)
            email_sent = True
        except Exception as e:
            _message_team_log.warning(
                "message %s stored but email deferred: %s", message_id, e
            )

        return _json.dumps({
            "success": True,
            "message_id": message_id,
            "email_sent": email_sent,
        })


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
                            "real producers with enough history — include several ≥2 "
                            "years past peak) with run_sql and call forecast_wells "
                            "again."),
            })
        except AnalogRequired as e:
            # Belt-and-braces: the orchestrator converts these to AnalogsRequired
            # bounces; if one ever escapes, still return an actionable message.
            return _json.dumps({
                "error": "analogs_required",
                "message": (f"A well's {e.stream} stream needs an analog type curve "
                            "it wasn't given. Supply analogs for its group and call "
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
                "viewer": _DEAL_SHEET_VIEWER,
            }, default=str)
        except Exception as e:  # noqa: BLE001
            return _json.dumps({"error": str(e)})


if __name__ == "__main__":
    import os as _os

    _port = int(_os.environ.get("MCP_PORT", "9000"))
    mcp.run(transport="http", host="0.0.0.0", port=_port, uvicorn_config={"timeout_graceful_shutdown": 10})
