"""HTTP upload lane for bulk payloads out of the code-execution sandbox.

The MCP tools stay slim (mint a one-time URL, a few hundred bytes of
context); the bytes travel here as plain HTTPS POSTs and never transit the
model. Routes hang off the same Starlette app as the MCP endpoint
(`register_upload_routes(mcp, ...)`), behind nginx's `/upload/` location —
which, unlike `/<slug>/mcp`, injects no identity header: the token in the
path carries it (see server/upload_tokens.py).

Routes:
- POST /upload/kit/{token} — a persist_pack.py kit. Expands the CSV tables
  and stores through the exact same code path the old inline tool call used
  (extraction_transport + ExtractionStore); only the wire changed.
- POST /upload/echo/{token} — probe endpoint: streams the body, answers
  {bytes_received, sha256}. Validates (but never consumes) a token, so the
  sandbox-proxy size ceiling can be measured against a real deployment
  without an open bandwidth sink.
"""

import hashlib
import json
import logging
import os

from starlette.requests import Request
from starlette.responses import JSONResponse

from fastmcp.server.dependencies import get_http_request

from server.extraction_transport import TransportError, entity_counts, unpack_extraction

_log = logging.getLogger("cc.uploads")

# At-rest cap on the expanded ExtractionResult row (same number the inline
# tool enforced) and a pre-parse guard on the raw kit body above it.
MAX_EXTRACTION_BYTES = 2_000_000
MAX_KIT_BODY_BYTES = 8_000_000


def public_base_url() -> str:
    """Absolute base for minted upload URLs. CC_UPLOAD_BASE_URL overrides
    (local dev); otherwise derived from the live request's Host header, so
    prod and dev deployments mint their own hostnames with zero config."""
    env = os.environ.get("CC_UPLOAD_BASE_URL")
    if env:
        return env.rstrip("/")
    try:
        host = get_http_request().headers.get("host", "")
    except RuntimeError:
        host = ""
    return f"https://{host}" if host else "http://127.0.0.1:9000"


def _reject(status: int, message: str) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status)


def register_upload_routes(mcp, *, tokens, extraction_store) -> None:
    @mcp.custom_route("/upload/kit/{token}", methods=["POST"])
    async def upload_kit(request: Request) -> JSONResponse:
        token = request.path_params["token"]
        grant = tokens.claim(token, purpose="kit")
        if grant is None:
            return _reject(410, "unknown, expired, or already-used upload URL — "
                                "mint a fresh one with save_dataroom_extraction")

        body = await request.body()
        if len(body) > MAX_KIT_BODY_BYTES:
            return _reject(413, f"kit body too large ({len(body)} bytes; cap {MAX_KIT_BODY_BYTES})")
        try:
            kit = json.loads(body)
        except ValueError:
            return _reject(400, "kit body must be a JSON object")
        if not isinstance(kit, dict) or not isinstance(kit.get("extraction"), dict) \
                or not kit["extraction"]:
            return _reject(400, "kit must carry a non-empty `extraction` object")

        try:
            full = unpack_extraction(
                kit["extraction"],
                production_csv=kit.get("production_csv") or "",
                revenue_csv=kit.get("revenue_csv") or "",
                sources=kit.get("sources"),
            )
        except TransportError as e:
            return _reject(422, str(e))

        size = len(json.dumps(full).encode())
        if size > MAX_EXTRACTION_BYTES:
            return _reject(413, f"extraction too large ({size} bytes; cap {MAX_EXTRACTION_BYTES})")

        label = (grant.meta.get("label") or "").strip()
        try:
            eid = extraction_store.save(
                user_id=grant.user_id,
                extraction=full,
                label=label,
                extraction_id=grant.meta.get("extraction_id") or None,
            )
        except (ValueError, LookupError) as e:
            return _reject(409, str(e))
        except Exception as e:  # noqa: BLE001 — DB failures land here
            _log.error("upload_kit store failed: %s", e)
            return _reject(500, str(e))

        tokens.consume(token)
        stored = entity_counts(full)
        _log.info("kit stored user=%s label=%r bytes=%d %s",
                  grant.user_slug, label, len(body), stored)
        return JSONResponse({
            "extraction_id": eid,
            "label": label,
            "saved": True,
            "stored": stored,
            "bytes_received": len(body),
        })

    @mcp.custom_route("/upload/echo/{token}", methods=["POST"])
    async def upload_echo(request: Request) -> JSONResponse:
        token = request.path_params["token"]
        if tokens.claim(token, purpose="kit") is None:
            return _reject(410, "unknown, expired, or already-used token")
        digest = hashlib.sha256()
        received = 0
        async for chunk in request.stream():
            digest.update(chunk)
            received += len(chunk)
        return JSONResponse({"bytes_received": received, "sha256": digest.hexdigest()})
