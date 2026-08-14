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
  (extraction_transport + ExtractionStore); only the wire changed. When the
  mint bound a room_id, the saved row links to it and the room's write-once
  initial-extraction snapshot is taken here.
- POST /upload/room/{token} — the dataroom zip itself (capture-first flow,
  minted by open_dataroom). Streamed to a temp file while hashing; the
  digest must match the sha256 asserted at mint time, then the blob lands
  in Supabase Storage keyed rooms/<sha256>.zip.
- GET /upload/extraction/{token} — the reuse lane: serves a stored
  extraction (the caller's own row, bound at mint time by open_dataroom) so
  a duplicate room skips re-extraction entirely and the sandbox just curls
  extraction.json down. Single-use like the upload routes.
- POST /upload/echo/{token} — probe endpoint: streams the body, answers
  {bytes_received, sha256}. Validates (but never consumes) a token, so the
  sandbox-proxy size ceiling can be measured against a real deployment
  without an open bandwidth sink.
- GET /export/{token}/{filename} — the download lane: assembles a CSV from
  the run record (server/exports.py) and serves it as a file attachment.
  Unlike every route above it, the client is a *browser* — a person clicking
  a link Claude printed — so it never consumes the token and its grant
  carries a longer TTL. Lives under /export/ rather than /upload/ because
  the URL is user-visible.
"""

import asyncio
import hashlib
import json
import logging
import os
import tempfile

from urllib.parse import urlparse

from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse

from fastmcp.server.dependencies import get_http_request

from server import exports
from server.extraction_store import STORAGE_KEY_FIELD
from server.extraction_transport import TransportError, entity_counts, unpack_extraction

_log = logging.getLogger("cc.uploads")

# Sanity ceilings only. The old 2 MB figure was the inline-tool era's cap,
# sized for extractions that traveled through the model's context; now that
# extractions rest in Supabase Storage (pointer rows — see extraction_store),
# the caps exist to stop abuse, not to bound a Postgres row. A real room
# (47 wells / 227 stubs) expands to ~7 MB and must fit whole: the skill's
# "never persist an abbreviated copy" rule is load-bearing.
MAX_EXTRACTION_BYTES = 50_000_000
MAX_KIT_BODY_BYTES = 64_000_000

# Room zips: nginx enforces 600m at the edge; this is the in-app backstop.
MAX_ROOM_BYTES = 600_000_000


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


def public_host() -> str:
    """Hostname of `public_base_url()` — the thing a user adds to their
    Claude network egress allowlist. Derived with a real URL parse so a
    path-bearing base (the /dev-prefixed apex lane) never leaks its path
    into that instruction."""
    return urlparse(public_base_url()).hostname or ""


def _reject(status: int, message: str) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status)


def register_upload_routes(mcp, *, tokens, extraction_store,
                           room_store=None, blob_store=None, run_store=None) -> None:
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
        room_id = grant.meta.get("room_id") or None
        try:
            # save() pushes the payload to Storage and writes a pointer row
            # (inline row without a blob store) — run off the event loop;
            # a multi-MB blob push must not block the MCP endpoint.
            eid = await asyncio.to_thread(
                lambda: extraction_store.save(
                    user_id=grant.user_id,
                    extraction=full,
                    label=label,
                    extraction_id=grant.meta.get("extraction_id") or None,
                    room_id=room_id,
                ))
        except (ValueError, LookupError) as e:
            return _reject(409, str(e))
        except Exception as e:  # noqa: BLE001 — DB/Storage failures land here
            _log.error("upload_kit store failed: %s", e)
            return _reject(500, str(e))

        if room_id and room_store is not None and label:
            # The room registered under a placeholder (open_dataroom runs
            # before anything in the zip is read); the kit's label is the
            # real deal title. Uploader-scoped inside the store.
            try:
                room_store.refine_label(room_id, label, user_id=grant.user_id)
            except Exception as e:  # noqa: BLE001 — label polish never fails a save
                _log.error("room label refine failed for %s: %s", room_id, e)

        if room_id and room_store is not None and not grant.meta.get("extraction_id"):
            # Write-once room snapshot: only a *first* save (not a
            # correction re-save) can become the initial extraction, and
            # the store refuses if a snapshot already exists. In blob mode
            # the snapshot gets its OWN object (keyed by room + eid, so a
            # racing first-saver can never repoint an already-stamped row):
            # the saver's extractions/<eid>.json may be overwritten by their
            # later corrections, and the room snapshot must stay immutable.
            try:
                if room_store.get_initial_extraction(room_id) is None:
                    snap = full
                    if blob_store is not None and blob_store.configured():
                        skey = f"extractions/room-{room_id}-{eid}.json"
                        await asyncio.to_thread(
                            blob_store.put_bytes, skey,
                            json.dumps(full).encode(),
                            content_type="application/json")
                        snap = {STORAGE_KEY_FIELD: skey,
                                "_entity_counts": entity_counts(full)}
                    room_store.save_initial_extraction(room_id, snap)
            except Exception as e:  # noqa: BLE001 — snapshot must never fail the save
                _log.error("initial-extraction snapshot failed for %s: %s", room_id, e)

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

    @mcp.custom_route("/upload/room/{token}", methods=["POST"])
    async def upload_room(request: Request) -> JSONResponse:
        token = request.path_params["token"]
        grant = tokens.claim(token, purpose="room")
        if grant is None:
            return _reject(410, "unknown, expired, or already-used upload URL — "
                                "mint a fresh one with open_dataroom")
        if room_store is None or blob_store is None:
            return _reject(500, "room capture is not configured on this server")

        expected_sha = grant.meta["sha256"]
        room_id = grant.meta["room_id"]
        digest = hashlib.sha256()
        received = 0
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".zip")
        try:
            async for chunk in request.stream():
                received += len(chunk)
                if received > MAX_ROOM_BYTES:
                    return _reject(413, f"room too large (cap {MAX_ROOM_BYTES} bytes)")
                digest.update(chunk)
                tmp.write(chunk)
            tmp.close()

            if received == 0:
                return _reject(400, "empty body")
            if digest.hexdigest() != expected_sha:
                return _reject(422, "sha256 mismatch: received bytes do not match the "
                                    "hash asserted to open_dataroom — retry the upload")

            key = f"rooms/{expected_sha}.zip"
            try:
                await asyncio.to_thread(blob_store.put_file, key, tmp.name)
                final_room_id = room_store.mark_complete(room_id, storage_key=key)
            except Exception as e:  # noqa: BLE001 — storage/DB failures land here
                _log.error("upload_room failed for %s: %s", room_id, e)
                return _reject(500, str(e))
        finally:
            tmp.close()
            os.unlink(tmp.name)

        tokens.consume(token)
        _log.info("room stored user=%s room=%s bytes=%d", grant.user_slug,
                  final_room_id, received)
        return JSONResponse({
            "saved": True,
            "room_id": final_room_id,
            "bytes_received": received,
            "sha256": expected_sha,
        })

    @mcp.custom_route("/upload/extraction/{token}", methods=["GET"])
    async def download_extraction(request: Request) -> JSONResponse:
        token = request.path_params["token"]
        grant = tokens.claim(token, purpose="extraction")
        if grant is None:
            return _reject(410, "unknown, expired, or already-used download URL — "
                                "mint a fresh one with open_dataroom")
        try:
            # get_payload resolves a pointer row through Storage; blob fetch
            # runs off the event loop like every other Storage call here.
            payload = await asyncio.to_thread(
                extraction_store.get_payload, grant.meta["extraction_id"])
        except Exception as e:  # noqa: BLE001
            _log.error("download_extraction failed: %s", e)
            return _reject(500, str(e))
        if payload is None:
            return _reject(404, "extraction not found")
        tokens.consume(token)
        _log.info("extraction served user=%s id=%s", grant.user_slug,
                  grant.meta["extraction_id"])
        return JSONResponse(payload)

    @mcp.custom_route("/upload/echo/{token}", methods=["POST"])
    async def upload_echo(request: Request) -> JSONResponse:
        token = request.path_params["token"]
        if (tokens.claim(token, purpose="kit") is None
                and tokens.claim(token, purpose="room") is None):
            return _reject(410, "unknown, expired, or already-used token")
        digest = hashlib.sha256()
        received = 0
        async for chunk in request.stream():
            digest.update(chunk)
            received += len(chunk)
        return JSONResponse({"bytes_received": received, "sha256": digest.hexdigest()})

    @mcp.custom_route("/export/{token}/{filename}", methods=["GET"])
    async def download_export(request: Request):
        token = request.path_params["token"]
        grant = tokens.claim(token, purpose="export")
        if grant is None:
            return _reject(410, "this download link has expired — ask Claude to "
                                "export again to mint a fresh one")

        kind = grant.meta.get("kind", "")
        try:
            # Assembly can hit the database (run record, or a re-run query), so
            # it goes to a thread: this route shares an event loop with the MCP
            # endpoint and a 30s query must not stall other sessions.
            body, rows = await asyncio.to_thread(
                exports.assemble, kind, grant.meta, run_store=run_store,
            )
        except exports.ExportError as e:
            return _reject(422, str(e))
        except Exception as e:  # noqa: BLE001
            _log.error("export assembly failed kind=%s: %s", kind, e)
            return _reject(500, str(e))

        # The filename rides in the path (so a browser saves something
        # recognisable) but it lands in a response header, so it is rebuilt
        # from an allowlist rather than trusted.
        raw = request.path_params["filename"] or ""
        filename = "".join(c for c in raw if c.isalnum() or c in "-_.") or "export.csv"
        _log.info("export served user=%s kind=%s rows=%d bytes=%d",
                  grant.user_slug, kind, rows, len(body))
        return PlainTextResponse(
            body,
            media_type="text/csv; charset=utf-8",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                # A capability URL is not a cacheable public resource.
                "Cache-Control": "no-store",
                "X-Export-Rows": str(rows),
            },
        )
