"""The retired in-chat account mint.

GET /new-account used to insert an anonymous platform.users row per request
and return the personal connector URL as typed state — the CrudeDocs
funnel's in-chat mint. The 2026-08 CrudeDocs simplification removed that
lane (signup is the crudecode.dev form; the connector URL arrives by
email), so the route now always returns {"status": "unavailable"} and never
touches the database. The route itself survives because copied prompts in
the wild still carry mint URLs: old doc revisions' scripted fallback reads
"unavailable" and narrates the form path instead of dead-ending. Accounts
minted while the lane was live keep working; update_user (server/
user_profile.py) is their claim lane. Full mint implementation: git history
(v0.4.x).
"""

import json
import logging

from starlette.requests import Request
from starlette.responses import PlainTextResponse

_log = logging.getLogger("cc.accounts")

RETIRED_PAYLOAD = {"status": "unavailable"}


def handle_new_account(client_ip: str) -> dict:
    """Always unavailable — the mint is retired; nothing is ever inserted."""
    _log.info("new-account request on retired lane ip=%s", client_ip)
    return dict(RETIRED_PAYLOAD)


def register_account_routes(mcp) -> None:
    @mcp.custom_route("/new-account", methods=["GET"])
    async def new_account(request: Request) -> PlainTextResponse:
        ip = request.headers.get("x-real-ip") or (
            request.client.host if request.client else "unknown"
        )
        # text/plain because the fetch tool that hits this rejects non-text.
        return PlainTextResponse(
            json.dumps(handle_new_account(ip)), media_type="text/plain"
        )
