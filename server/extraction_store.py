"""Durable dataroom extractions. Server-minted extraction_id, whole
ExtractionResult stored verbatim as JSONB, scoped by user_id. Backed by
platform.dataroom_extractions in Supabase.

The extraction contract lives with the skill (skills/dataroom-extract/schema.py)
and evolves there; this store treats the payload as an opaque blob on purpose
so schema changes never need a migration here.
"""
import json
import uuid

from utils.platform import _query


class ExtractionStore:
    def save(self, *, user_id: int, extraction: dict, label: str = "",
             extraction_id: str | None = None, room_id: str | None = None) -> str:
        """Insert a new extraction (mints a UUID) or, when extraction_id is
        given, overwrite that row — scoped to user_id so one user can never
        touch another's. `room_id` links the extraction to its captured room
        (platform.dataroom_rooms); on updates it only ever fills a null.
        Returns the extraction_id as a UUID string.

        Raises ValueError on a malformed extraction_id, LookupError when the
        id doesn't exist for this user."""
        payload = json.dumps(extraction)
        if extraction_id is None:
            extraction_id = str(uuid.uuid4())
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
        """Return the full record as a dict, or None if not found."""
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
