"""Durable dataroom extractions. Server-minted extraction_id, scoped by
user_id. Backed by platform.dataroom_extractions in Supabase.

At-rest layout: when a blob store is wired in (production), the full
ExtractionResult lives in Supabase Storage as extractions/<id>.json and the
row's jsonb column holds a small pointer stub — {"_storage_key", "_entity_counts"}.
This is what retired the old 2 MB row cap: the row stays row-sized no matter
how many revenue rows a package carries. Without a blob store (local dev,
tests) the payload is stored inline in the row, exactly the pre-pointer
behavior. `get_payload` resolves either form to the full extraction.

A stub passed INTO save() (e.g. dataroom_open copying a room's initial
snapshot to a first-time holder) is stored as-is — the copy points at the
room's immutable object, and a later correction re-save writes the user's
own object and repoints their row, never touching the room's.

The extraction contract lives with the skill (skills/dataroom-extract/schema.py)
and evolves there; this store treats the payload as an opaque blob on purpose
so schema changes never need a migration here.
"""
import json
import uuid

from server.extraction_transport import entity_counts
from utils.platform import _query

STORAGE_KEY_FIELD = "_storage_key"


def is_pointer_stub(payload: dict) -> bool:
    return isinstance(payload, dict) and STORAGE_KEY_FIELD in payload


class ExtractionStore:
    def __init__(self, blob_store=None) -> None:
        # Optional SupabaseBlobStore; unconfigured/None → inline rows.
        self._blobs = blob_store

    def _blob_mode(self) -> bool:
        return self._blobs is not None and self._blobs.configured()

    def _to_row_payload(self, extraction_id: str, extraction: dict) -> str:
        """Push the payload to Storage and return the pointer stub to store,
        or (inline mode / already a stub) return the payload itself."""
        if is_pointer_stub(extraction) or not self._blob_mode():
            return json.dumps(extraction)
        key = f"extractions/{extraction_id}.json"
        self._blobs.put_bytes(key, json.dumps(extraction).encode(),
                              content_type="application/json")
        stub = {STORAGE_KEY_FIELD: key, "_entity_counts": entity_counts(extraction)}
        return json.dumps(stub)

    def save(self, *, user_id: int, extraction: dict, label: str = "",
             extraction_id: str | None = None, room_id: str | None = None) -> str:
        """Insert a new extraction (mints a UUID) or, when extraction_id is
        given, overwrite that row — scoped to user_id so one user can never
        touch another's. `room_id` links the extraction to its captured room
        (platform.dataroom_rooms); on updates it only ever fills a null.
        Returns the extraction_id as a UUID string.

        Raises ValueError on a malformed extraction_id, LookupError when the
        id doesn't exist for this user."""
        if extraction_id is None:
            extraction_id = str(uuid.uuid4())
            payload = self._to_row_payload(extraction_id, extraction)
            _query(
                """
                INSERT INTO platform.dataroom_extractions
                    (extraction_id, user_id, label, extraction, room_id)
                VALUES (%s, %s, %s, %s::jsonb, %s)
                """,
                params=[extraction_id, user_id, label, payload, room_id],
            )
            return extraction_id

        try:
            uuid.UUID(extraction_id)
        except ValueError:
            raise ValueError(f"malformed extraction_id: {extraction_id!r}")
        payload = self._to_row_payload(extraction_id, extraction)
        rows = _query(
            """
            UPDATE platform.dataroom_extractions
            SET extraction = %s::jsonb, label = %s, updated_at = now(),
                room_id = COALESCE(room_id, %s)
            WHERE extraction_id = %s AND user_id = %s
            RETURNING extraction_id
            """,
            params=[payload, label, room_id, extraction_id, user_id],
        )
        if not rows:
            raise LookupError(
                f"extraction_id {extraction_id} not found for this user"
            )
        return extraction_id

    def get(self, extraction_id: str) -> dict | None:
        """Return the full record as a dict, or None if not found. The
        `extraction` field is the row payload verbatim — a pointer stub in
        blob mode; use `get_payload` to resolve the actual extraction."""
        rows = _query(
            "SELECT * FROM platform.dataroom_extractions WHERE extraction_id = %s",
            params=[extraction_id],
        )
        if not rows:
            return None
        rec = rows[0]
        # psycopg returns uuid columns as uuid.UUID objects — normalise to str
        if rec.get("extraction_id") is not None:
            rec["extraction_id"] = str(rec["extraction_id"])
        if isinstance(rec.get("extraction"), str):   # psycopg sometimes returns text
            rec["extraction"] = json.loads(rec["extraction"])
        return rec

    def get_payload(self, extraction_id: str) -> dict | None:
        """The full ExtractionResult for a row, resolving a pointer stub
        through the blob store. None when the row doesn't exist or carries
        no payload. Raises BlobStoreError if a pointed-at object can't be
        fetched — a pointer to nothing is an error, not an empty result."""
        rec = self.get(extraction_id)
        if rec is None:
            return None
        payload = rec.get("extraction")
        if not payload:
            return None
        if is_pointer_stub(payload):
            if self._blobs is None:
                raise RuntimeError(
                    f"extraction {extraction_id} is stored in Storage "
                    f"({payload[STORAGE_KEY_FIELD]}) but no blob store is configured")
            return json.loads(self._blobs.get_bytes(payload[STORAGE_KEY_FIELD]))
        return payload

    def find_for_user_room(self, user_id: int, room_id: str) -> dict | None:
        """This user's newest extraction for a room, id + label only. Used by
        dataroom_open to hand a returning user their own (possibly corrected)
        copy instead of re-copying the room's initial snapshot."""
        rows = _query(
            """
            SELECT extraction_id, label
            FROM platform.dataroom_extractions
            WHERE user_id = %s AND room_id = %s
            ORDER BY created_at DESC
            LIMIT 1
            """,
            params=[user_id, room_id],
        )
        if not rows:
            return None
        rec = rows[0]
        rec["extraction_id"] = str(rec["extraction_id"])
        return rec

    def list_for_user(self, user_id: int) -> list[dict]:
        """Newest-first index of a user's extractions — id, label, timestamps.
        No payload blob, so it stays cheap at any count."""
        rows = _query(
            """
            SELECT extraction_id, label, created_at, updated_at
            FROM platform.dataroom_extractions
            WHERE user_id = %s
            ORDER BY created_at DESC
            """,
            params=[user_id],
        )
        for rec in rows:
            rec["extraction_id"] = str(rec["extraction_id"])
        return rows
