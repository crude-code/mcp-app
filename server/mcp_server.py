"""Crude Code MCP Server.

Synchronous tool registry — run_sql, deal_forecast_wells, deal_valuation, map_render, get_skill,
plus the renderer-only read tool (map_read_full). No inner agents.
"""

# Release version. A dev → main merge is a release: bump this and the
# renderer's package.json version (kept in lockstep by
# tests/test_version_drift.py) in the last dev commit, then tag vX.Y.Z on
# main after the merge.
__version__ = "0.4.3"

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
from utils.sql_guard import GuardError, dry_run, run_guarded

_briefing_handles = BriefingHandleStore(ttl_seconds=86_400.0)  # 24h

from server.valuation.orchestrator import (
    compose_artifact_payload_for_run, forecast_wells_for_run,
    run_valuation_for_run, ForecastValidationError,
)
from server.valuation.artifact_payload import load_viewer, viewer_sha256, viewer_url

# Frozen deal-sheet artifact template, shipped in every deal_valuation response
# so the template Claude fills always matches the payload contract that
# produced `data`. The content-addressed URL + sha ride along so a session
# with code execution can download the template instead of re-emitting it
# token by token; the inline source stays the universal fallback.
_DEAL_SHEET_VIEWER = load_viewer()
_DEAL_SHEET_SHA256 = viewer_sha256()
_DEAL_SHEET_URL = viewer_url(_DEAL_SHEET_SHA256)
from server.maps.spec import parse_map_spec, MapSpecError
from server.maps.hydrate import hydrate_map, MapHydrateError
from server.skills import list_skills, load_skill, SkillNotFound
from server.blob_store import SupabaseBlobStore
from server.extraction_store import ExtractionStore
from server.room_store import RoomStore
from server.upload_tokens import UploadTokenStore
from server.accounts import RateLimiter, register_account_routes
from server.uploads import public_base_url, public_host, register_upload_routes
from server.user_profile import UserProfileStore, plan_update, profile_state
from server.valuation.run_record import ValuationRunStore
from server import export_tokens as _export_tokens
from server import exports as _exports
from server.team_messages import CATEGORIES as MESSAGE_CATEGORIES, TeamMessageStore
from utils.ses import send_notification

_blob_store = SupabaseBlobStore()
# Blob-backed: extraction payloads rest in Storage as pointer rows when the
# blob store is configured; inline rows otherwise (local dev, tests).
_extraction_store = ExtractionStore(_blob_store)
_room_store = RoomStore()
_upload_tokens = UploadTokenStore()
_team_messages = TeamMessageStore()
_user_profiles = UserProfileStore()
_run_store = ValuationRunStore()


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

register_upload_routes(mcp, tokens=_upload_tokens, extraction_store=_extraction_store,
                       room_store=_room_store, blob_store=_blob_store,
                       run_store=_run_store)
register_account_routes(mcp)


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
    """Serve the Crude Code app for `map_render` tool renders.

    Distinct URI so the host renders a fresh iframe per map call. The CSP meta
    whitelists OpenStreetMap tile fetches (the iframe blocks them otherwise) —
    this is the only resource that needs it.
    """
    return APP_HTML


# ── run_sql ────────────────────────────────────────────────────────────────

_run_sql_log = _logging.getLogger("cc.run_sql")
_map_log = _logging.getLogger("cc.map")


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

_get_skill_log = _logging.getLogger("cc.get_skill")


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


# ── dataroom_save_extraction ─────────────────────────────────────────────────

_save_extraction_log = _logging.getLogger("cc.dataroom_save_extraction")
_dataroom_open_log = _logging.getLogger("cc.dataroom_open")

_SHA256_HEX_LEN = 64


def _known_room_response(identity: dict, existing: dict, label: str) -> str:
    """The dedupe/reuse branch: hand back an extraction instead of asking for
    an upload. A returning user gets their own newest (possibly corrected)
    row; a first-time holder of this room gets a fresh copy of the room's
    initial snapshot. Either way the payload never says who else has the
    room — 'already on the platform' is the entire story the user hears."""
    room_id = existing["room_id"]
    payload = {"status": "known", "room_id": room_id, "extraction_ready": False}
    try:
        mine = _extraction_store.find_for_user_room(identity["user_id"], room_id)
        eid = mine["extraction_id"] if mine else None
        if eid is None and existing.get("has_initial_extraction"):
            initial = _room_store.get_initial_extraction(room_id)
            if initial is not None:
                eid = _extraction_store.save(
                    user_id=identity["user_id"], extraction=initial,
                    label=label, room_id=room_id,
                )
        if eid:
            token = _upload_tokens.mint(
                user_id=identity["user_id"], user_slug=identity["user_slug"],
                purpose="extraction", meta={"extraction_id": eid},
            )
            base = public_base_url()
            payload.update({
                "extraction_ready": True,
                "extraction_id": eid,
                "extraction_url": f"{base}/upload/extraction/{token}",
                "expires_in_seconds": int(_upload_tokens.ttl_seconds),
                "how": 'curl -sS -o extraction.json "<extraction_url>" '
                       "— then skip extraction and go straight to the viewer; "
                       "corrections re-save under this extraction_id.",
            })
    except Exception as e:  # noqa: BLE001 — reuse must degrade, never block
        _dataroom_open_log.error("reuse path failed for %s: %s", room_id, e)
    if not payload["extraction_ready"]:
        payload["note"] = ("Room already captured — skip the zip upload, run the "
                          "normal extraction, and pass room_id when persisting.")
    _dataroom_open_log.info("known room %s ready=%s label=%r",
                            room_id, payload["extraction_ready"], label)
    return _json.dumps(payload)


@mcp.tool(description=_load_prompt("outer/tool_dataroom_open.md"))
def dataroom_open(label: str, sha256: str, size_bytes: int) -> str:
    """Register a dataroom zip before reading it. Known content hash →
    the room is already captured ({status: "known"}, no upload); new hash →
    a pending room row plus a one-time upload URL for the zip. Presented to
    the user as 'filed'/'processed' only — never reveal that a known room
    was uploaded by anyone else."""
    identity = get_current_identity()
    if not identity:
        return _json.dumps({"error": "Could not identify user"})

    with trace("dataroom_open", user=identity["user_slug"]):
        clean_label = (label or "").strip()
        clean_sha = (sha256 or "").strip().lower()
        if not clean_label:
            return _json.dumps({"error": "label is required — use the deal/teaser title"})
        if len(clean_sha) != _SHA256_HEX_LEN or any(c not in "0123456789abcdef" for c in clean_sha):
            return _json.dumps({"error": "sha256 must be the 64-char hex digest of the zip"})
        if not isinstance(size_bytes, int) or size_bytes <= 0:
            return _json.dumps({"error": "size_bytes must be the zip's byte count"})

        try:
            existing = _room_store.find_by_hash(clean_sha)
        except Exception as e:  # noqa: BLE001
            _dataroom_open_log.error("dataroom_open lookup failed: %s", e)
            return _json.dumps({"error": str(e)})

        if existing:
            return _known_room_response(identity, existing, clean_label)

        try:
            room_id = _room_store.create_pending(
                user_id=identity["user_id"], label=clean_label,
                sha256=clean_sha, size_bytes=size_bytes,
            )
        except Exception as e:  # noqa: BLE001
            _dataroom_open_log.error("dataroom_open insert failed: %s", e)
            return _json.dumps({"error": str(e)})

        token = _upload_tokens.mint(
            user_id=identity["user_id"], user_slug=identity["user_slug"],
            purpose="room", meta={"room_id": room_id, "sha256": clean_sha},
        )
        base = public_base_url()
        return _json.dumps({
            "status": "new",
            "room_id": room_id,
            "upload_url": f"{base}/upload/room/{token}",
            "upload_host": public_host(),
            "expires_in_seconds": int(_upload_tokens.ttl_seconds),
            "how": 'python3 room_push.py <room.zip> "<upload_url>"',
        })


@mcp.tool(description=_load_prompt("outer/tool_dataroom_save_extraction.md"))
def dataroom_save_extraction(label: str, extraction_id: str = "", room_id: str = "") -> str:
    """Mint a one-time HTTP upload URL for a persist_pack.py kit. The kit
    bytes travel out-of-band (a POST from the sandbox) and never transit the
    model; this call carries only the label plus an optional extraction_id
    for in-place re-saves. Storage semantics are unchanged — the upload
    handler runs the same transport-expansion and store code the old inline
    call did (server/uploads.py)."""
    identity = get_current_identity()
    if not identity:
        return _json.dumps({"error": "Could not identify user"})

    with trace("dataroom_save_extraction", user=identity["user_slug"]):
        clean_label = (label or "").strip()
        if not clean_label:
            return _json.dumps({"error": "label is required — use the deal/teaser title"})

        token = _upload_tokens.mint(
            user_id=identity["user_id"],
            user_slug=identity["user_slug"],
            purpose="kit",
            meta={"label": clean_label,
                  "extraction_id": extraction_id.strip() or None,
                  "room_id": room_id.strip() or None},
        )
        base = public_base_url()
        _save_extraction_log.info(
            "minted kit upload label=%r resave=%s", clean_label, bool(extraction_id.strip())
        )
        return _json.dumps({
            "upload_url": f"{base}/upload/kit/{token}",
            "upload_host": public_host(),
            "expires_in_seconds": int(_upload_tokens.ttl_seconds),
            "how": 'python3 persist_pack.py extraction.json --upload "<upload_url>"',
        })


# ── message_team ─────────────────────────────────────────────────────────────

_message_team_log = _logging.getLogger("cc.message_team")

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


# ── update_user ──────────────────────────────────────────────────────────────

_update_user_log = _logging.getLogger("cc.update_user")

# The "already on another account" refusal is unavoidably a yes/no oracle on
# whether an address has a CrudeCode account, so cap how fast one caller can
# ask. Far above honest use (you claim an account once), low enough that bulk
# probing is not worth the trouble.
_update_user_limiter = RateLimiter(limit=20, window_s=3600)


@mcp.tool(description=_load_prompt("outer/tool_update_user.md"))
def update_user(email: str = "", name: str = "") -> str:
    """Read or write the caller's own profile row. No arguments = read.

    The claim lane for anonymously minted accounts; see server/user_profile.py
    for the attach-don't-reassign rule and why a stored email is unverified."""
    identity = get_current_identity()
    if not identity:
        return _json.dumps({"error": "Could not identify user"})
    user_id = identity["user_id"]
    user_slug = identity["user_slug"]

    with trace("update_user", user=user_slug):
        try:
            current = _user_profiles.read(user_id)
        except Exception as e:  # noqa: BLE001 — DB errors surface here
            _update_user_log.error("update_user read failed: %s", e)
            return _json.dumps({"error": str(e)})
        if current is None:
            return _json.dumps({"error": "Could not identify user"})

        # No arguments: a read of current state. Deliberately not an error and
        # deliberately not rate-limited — it is what lets Claude check before
        # offering, instead of asking for an email the user already has.
        if not (email or "").strip() and not (name or "").strip():
            return _json.dumps(profile_state(current))

        if not _update_user_limiter.allow(user_slug):
            return _json.dumps({"error": (
                "rate limit: too many profile updates in the last hour — "
                "wait before trying again"
            )})

        plan = plan_update(current=current, email=email, name=name)
        if "error" in plan:
            return _json.dumps({"error": plan["error"]})

        # One address, one account: the site's signup path already refuses an
        # email that exists in platform.users, so claiming one here would
        # otherwise be the way to end up with two accounts on one address.
        if plan["email"]:
            try:
                owner = _user_profiles.email_owner(plan["email"])
            except Exception as e:  # noqa: BLE001
                _update_user_log.error("update_user owner check failed: %s", e)
                return _json.dumps({"error": str(e)})
            if owner is not None and owner != user_id:
                return _json.dumps({"error": (
                    "that email is already on another CrudeCode account — "
                    "if it's yours, use that account's connector URL, or file "
                    "a message_team request to merge them"
                )})

        if not plan["changed"]:
            return _json.dumps(profile_state(current))

        try:
            _user_profiles.apply(user_id=user_id, email=plan["email"],
                                 name=plan["name"])
        except Exception as e:  # noqa: BLE001
            _update_user_log.error("update_user write failed: %s", e)
            return _json.dumps({"error": str(e)})

        updated = dict(current)
        if plan["email"]:
            updated["email"] = plan["email"]
            updated["notes"] = {**(current.get("notes") or {}),
                                "email_source": "in_chat"}
        if plan["name"]:
            updated["name"] = plan["name"]
        _update_user_log.info("profile updated user=%s fields=%s",
                              user_slug, plan["changed"])

        # An anonymous account becoming reachable is the funnel converting —
        # the one event here worth a team notification. Best-effort: the row
        # is already written, and a mail hiccup must never read as a failure.
        if plan["email"] and not current.get("email"):
            try:
                send_notification(
                    f"[claim] {plan['email']} claimed a CrudeDoc account",
                    f"Slug: {user_slug}\nName: {updated.get('name') or 'unknown'}\n"
                    f"Email: {plan['email']} (unverified)\n",
                )
            except Exception as e:  # noqa: BLE001
                _update_user_log.warning("claim notice deferred: %s", e)

        return _json.dumps(profile_state(updated, changed=plan["changed"]))


# ── map ────────────────────────────────────────────────────────────────────


@mcp.tool(name="map_render", app=_app_config_map, description=_load_prompt("outer/tool_map_render.md"))
def map_render(spec: dict) -> str:
    """Synchronous map render. Validate -> hydrate -> mint handle -> summary."""
    identity = get_current_identity()
    if not identity:
        return _json.dumps({"error": "Could not identify user"})
    user_slug = identity["user_slug"]

    with trace("map_render", user=user_slug):
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
    name="map_read_full",
    app=_app_config_app_only,
    description="INTERNAL — Crude Code app only. Returns the full hydrated map spec for a map_token.",
)
def map_read_full(token: str) -> str:
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

@mcp.tool(description=_load_prompt("outer/tool_deal_forecast_wells.md"))
def deal_forecast_wells(forecasts: list[dict], run_id: str | None = None) -> str:
    """Accept asserted decline parameters, echo consequences. See
    prompts/outer/tool_deal_forecast_wells.md."""
    identity = get_current_identity()
    if not identity:
        return _json.dumps({"error": "Could not identify user"})
    user_id = identity["user_id"]
    with trace("deal_forecast_wells", user=identity["user_slug"]):
        try:
            result = forecast_wells_for_run(run_id=run_id, forecasts=forecasts, user_id=user_id)
        except ForecastValidationError as e:
            return _json.dumps({
                "error": "validation_failed",
                "violations": e.violations,
                "message": ("Nothing was saved. Fix every listed violation and re-send "
                            "the full call."),
            })
        except Exception as e:  # noqa: BLE001
            return _json.dumps({"error": str(e)})
        return _json.dumps(result, default=str)


@mcp.tool(description=_load_prompt("outer/tool_deal_valuation.md"))
def deal_valuation(run_id: str, params: dict) -> str:
    """Union forecasts → econ → slim artifact payload. See prompts/outer/tool_deal_valuation.md."""
    identity = get_current_identity()
    if not identity:
        return _json.dumps({"error": "Could not identify user"})
    user_slug = identity["user_slug"]
    with trace("deal_valuation", user=user_slug):
        try:
            run_valuation_for_run(run_id=run_id, params=params)
            data = compose_artifact_payload_for_run(run_id)
            # The sheet's download row. Minting is arithmetic, so it costs
            # nothing to always offer one — no extra tool call, no guessing at
            # valuation time whether the user will want the data.
            #
            # Offered only when the link is *durable*. A deal sheet outlives its
            # session, gets reopened, gets forwarded; an in-memory ticket would
            # leave a button that works today and 404s next week, and a dead
            # button inside a deliverable is worse than no button. With no
            # CC_EXPORT_SECRET configured the row simply doesn't render and the
            # chat lane carries on unchanged.
            bundle_url, _fn, durable = _mint_export_url(
                identity, kind="bundle", run_id=run_id,
                label=(data.get("facts") or {}).get("area") or "")
            if durable:
                data["export"] = {"bundle_url": bundle_url}
            return _json.dumps({
                "surface": "deal_sheet_artifact",
                "run_id": run_id,
                "data": data,
                "viewer": _DEAL_SHEET_VIEWER,
                "viewer_url": _DEAL_SHEET_URL,
                "viewer_sha256": _DEAL_SHEET_SHA256,
            }, default=str)
        except Exception as e:  # noqa: BLE001
            return _json.dumps({"error": str(e)})


# ── export_data ──────────────────────────────────────────────────────────────

_export_log = _logging.getLogger("cc.export")

# A person, not a sandbox: long enough to survive stepping away from the desk,
# short enough that the link is a session deliverable rather than a standing
# endpoint. Re-minting is one tool call inside a live session.
_EXPORT_TTL_HOURS = 24


def _mint_export_url(identity, *, kind: str, run_id: str = "", sql: str = "",
                     schema: str = "public", label: str = "") -> tuple[str, str, bool]:
    """Grant → `(download_url, filename, durable)`.

    Shared by `export_data` and the deal sheet's download row so both mint on
    identical terms. A run-scoped kind gets a signed, self-describing token
    that survives restarts; `query` — and everything, when no signing secret is
    configured — falls back to the in-memory ticket. `durable` says which,
    because it changes what the caller can honestly promise. Called above its
    definition by `deal_valuation`; module-level names resolve at call time, and
    the export lane's constants belong here with the rest of it.
    """
    run_id = run_id.strip()
    durable = False
    if kind in _export_tokens.SIGNABLE_KINDS and _export_tokens.secret() is not None:
        token = _export_tokens.mint(kind=kind, run_id=run_id,
                                    user_id=identity["user_id"],
                                    user_slug=identity["user_slug"])
        durable = True
    else:
        token = _upload_tokens.mint(
            user_id=identity["user_id"],
            user_slug=identity["user_slug"],
            purpose="export",
            meta={"kind": kind, "run_id": run_id or None,
                  "sql": sql.strip() or None, "schema": schema},
            ttl_seconds=_EXPORT_TTL_HOURS * 3600,
        )
    filename = _exports.filename_for(kind, run_id=run_id, label=label)
    _export_log.info("minted export kind=%s run=%s durable=%s",
                     kind, run_id or "-", durable)
    return f"{public_base_url()}/export/{token}/{filename}", filename, durable


@mcp.tool(description=_load_prompt("outer/tool_export_data.md"))
def export_data(kind: str, run_id: str = "", sql: str = "",
                schema: str = "public", label: str = "") -> str:
    """Mint a browser-clickable download URL — a CSV, or a zip for `bundle`.
    The bytes are assembled at fetch time (server/exports.py) and never transit
    the model's context; this call returns only a link and a filename."""
    identity = get_current_identity()
    if not identity:
        return _json.dumps({"error": "Could not identify user"})

    with trace("export_data", user=identity["user_slug"]):
        if kind not in _exports.KINDS:
            return _json.dumps({
                "error": f"unknown kind {kind!r}; expected one of {list(_exports.KINDS)}"
            })
        if kind in ("volumes", "parameters", "bundle") and not run_id.strip():
            return _json.dumps({"error": f"kind {kind!r} needs a run_id"})
        if kind == "query" and not sql.strip():
            return _json.dumps({"error": "kind 'query' needs a sql SELECT"})

        # Validate a query at mint time so a broken SELECT fails here, in the
        # conversation, rather than behind a link the user has already clicked.
        if kind == "query":
            try:
                dry_run(sql, schema=schema, allowed_schemas=EXPLORATION_SCHEMAS)
            except GuardError as e:
                return _json.dumps({"error": str(e)})

        url, filename, durable = _mint_export_url(
            identity, kind=kind, run_id=run_id, sql=sql, schema=schema, label=label)
        return _json.dumps({
            "download_url": url,
            "filename": filename,
            "kind": kind,
            # A signed run-scoped link outlives the session; a query link is an
            # in-memory ticket. Reported honestly so Claude tells the user which
            # one they are holding.
            "expires_in_hours": (_export_tokens.DEFAULT_TTL_SECONDS // 3600
                                 if durable else _EXPORT_TTL_HOURS),
            "durable": durable,
        })


if __name__ == "__main__":
    import os as _os

    _port = int(_os.environ.get("MCP_PORT", "9000"))
    _logging.getLogger("cc.server").info(
        "Crude Code MCP v%s starting on port %d", __version__, _port)
    mcp.run(transport="http", host="0.0.0.0", port=_port, uvicorn_config={"timeout_graceful_shutdown": 10})
