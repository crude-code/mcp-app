"""Anonymous account minting for the CrudeDocs funnel.

GET /new-account — creates a fresh platform.users row (no email, placeholder
name, its own org) and returns the personal connector URL as typed state:

    {"status": "created", "shared": false,
     "mcp_url": "https://mcp.crudecode.dev/<slug>/mcp", "expires_at": null}

The caller is Claude's web-fetch tool, invoked mid-conversation by a CrudeDoc
(crudecode.dev/docs/*) after the user says yes to an account. The response is
text/plain because the fetch tool rejects non-text content types, and it
carries facts only — never prose for Claude to relay. Narration per status
lives in the CrudeDoc itself (crudedocs/README.md in the site repo: "the
server sends state, the doc supplies speech").

The ?t=<token> query param is ignored here: the site's copy button appends a
random token per click purely so Anthropic's per-URL fetch cache never hands
two visitors the same response.

Rate limit: fixed window per client IP (nginx passes X-Real-IP), in-memory.
A restart forgets counts — fine for an abuse brake, not an entitlement
system. Over-limit and mint failures both return status "unavailable" with
HTTP 200: the fetch tool must deliver the body so the doc's fallback branch
can narrate it instead of guessing at an opaque fetch error.
"""

import asyncio
import json
import logging
import os
import secrets
import time
import uuid
from collections import deque
from datetime import datetime, timezone

from starlette.requests import Request
from starlette.responses import PlainTextResponse

from utils import platform as _platform

_log = logging.getLogger("cc.accounts")

MINT_ORG_SLUG = "crudedoc-signups"
MINT_ORG_NAME = "CrudeDoc Signups"
PLACEHOLDER_NAME = "CrudeDoc visitor"
RATE_LIMIT = 10  # mints per IP per window
RATE_WINDOW_S = 3600


def _mcp_base() -> str:
    return os.environ.get("CC_PUBLIC_MCP_BASE", "https://mcp.crudecode.dev").rstrip("/")


class RateLimiter:
    """Fixed-window per-key counter. now_fn injectable for tests."""

    def __init__(self, limit: int = RATE_LIMIT, window_s: int = RATE_WINDOW_S, now_fn=time.monotonic):
        self.limit = limit
        self.window_s = window_s
        self.now_fn = now_fn
        self._hits: dict[str, deque] = {}

    def allow(self, key: str) -> bool:
        now = self.now_fn()
        q = self._hits.setdefault(key, deque())
        while q and now - q[0] > self.window_s:
            q.popleft()
        if len(q) >= self.limit:
            return False
        q.append(now)
        return True


def _org_id() -> int:
    rows = _platform._query(
        "SELECT id FROM organizations WHERE slug = %s LIMIT 1", [MINT_ORG_SLUG]
    )
    if rows:
        return rows[0]["id"]
    ins = _platform._query(
        "INSERT INTO organizations (slug, name) VALUES (%s, %s) RETURNING id",
        [MINT_ORG_SLUG, MINT_ORG_NAME],
    )
    return ins[0]["id"]


def _unique_slug() -> str:
    # 12-hex slug — the MCP lookup key (same shape provisioning mints).
    for _ in range(10):
        s = secrets.token_hex(6)
        hit = _platform._query("SELECT 1 FROM users WHERE slug = %s LIMIT 1", [s])
        if not hit:
            return s
    raise RuntimeError("could not generate a unique slug")


def mint_account() -> dict:
    """Insert an anonymous user row; return typed state for the fetch body."""
    org_id = _org_id()
    slug = _unique_slug()
    user_key = str(uuid.uuid4())
    notes = json.dumps(
        {"source": "crudedoc", "minted_at": datetime.now(timezone.utc).isoformat()}
    )
    _platform._query(
        "INSERT INTO users (org_id, user_key, name, email, role, slug, notes) "
        "VALUES (%s, %s, %s, NULL, 'user', %s, %s::jsonb)",
        [org_id, user_key, PLACEHOLDER_NAME, slug, notes],
    )
    return {
        "status": "created",
        "shared": False,
        "mcp_url": f"{_mcp_base()}/{slug}/mcp",
        "expires_at": None,
    }


def handle_new_account(client_ip: str, limiter: RateLimiter) -> dict:
    """The route's whole brain, sans HTTP — returns the response payload."""
    if not limiter.allow(client_ip):
        _log.warning("new-account rate-limited ip=%s", client_ip)
        return {"status": "unavailable"}
    try:
        payload = mint_account()
        _log.info("new-account minted ip=%s url=%s", client_ip, payload["mcp_url"])
        return payload
    except Exception:
        _log.exception("new-account mint failed ip=%s", client_ip)
        return {"status": "unavailable"}


def register_account_routes(mcp) -> None:
    limiter = RateLimiter()

    @mcp.custom_route("/new-account", methods=["GET"])
    async def new_account(request: Request) -> PlainTextResponse:
        ip = request.headers.get("x-real-ip") or (
            request.client.host if request.client else "unknown"
        )
        payload = await asyncio.to_thread(handle_new_account, ip, limiter)
        return PlainTextResponse(json.dumps(payload), media_type="text/plain")
