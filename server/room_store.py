"""Durable dataroom rooms — the captured zip's registry row.

Content-addressed and global across users: `find_by_hash` matches any
completed room regardless of who uploaded it, which is what makes duplicate
uploads free. Never surface that sharing to a user (deal-flow
confidentiality); tool docs carry the rule, this store just implements it.

`initial_extraction` is written once (first kit ever saved against the
room, pre-review) and never overwritten — per-user corrections live on
platform.dataroom_extractions rows only. Backed by platform.dataroom_rooms
(deploy/sql/001-dataroom-rooms.sql), same pattern as run_record.py.
"""
import json
import uuid

from utils.platform import _query


class RoomStore:
    def find_by_hash(self, sha256: str) -> dict | None:
        """The completed room for a content hash, or None. Global on purpose."""
        rows = _query(
            """
            SELECT room_id, sha256, size_bytes, label, storage_key,
                   initial_extraction IS NOT NULL AS has_initial_extraction
            FROM platform.dataroom_rooms
            WHERE sha256 = %s AND upload_complete
            """,
            params=[sha256],
        )
        if not rows:
            return None
        rec = rows[0]
        rec["room_id"] = str(rec["room_id"])
        return rec

    def create_pending(self, *, user_id: int, label: str, sha256: str,
                       size_bytes: int) -> str:
        room_id = str(uuid.uuid4())
        _query(
            """
            INSERT INTO platform.dataroom_rooms
                (room_id, sha256, size_bytes, label, uploaded_by_user_id)
            VALUES (%s, %s, %s, %s, %s)
            """,
            params=[room_id, sha256, size_bytes, label, user_id],
        )
        return room_id

    def refine_label(self, room_id: str, label: str, *, user_id: int) -> bool:
        """Replace the registration-time placeholder label with the real deal
        title once extraction knows it (dataroom_open must be called before
        anything in the zip is read, so the good label arrives late). Scoped
        to the original uploader — rooms are global rows, and another
        holder's kit save must never rename someone else's room."""
        if not label.strip():
            return False
        rows = _query(
            """
            UPDATE platform.dataroom_rooms
            SET label = %s
            WHERE room_id = %s AND uploaded_by_user_id = %s
            RETURNING room_id
            """,
            params=[label.strip(), room_id, user_id],
        )
        return bool(rows)

    def mark_complete(self, room_id: str, *, storage_key: str) -> str:
        """Flip a pending row to complete. On a same-hash race (two users
        uploading the identical room concurrently) the partial unique index
        rejects the second writer — the blob is identical bytes under the
        same key, so the loser just adopts the winner's room_id."""
        try:
            _query(
                """
                UPDATE platform.dataroom_rooms
                SET upload_complete = true, storage_key = %s, completed_at = now()
                WHERE room_id = %s
                """,
                params=[storage_key, room_id],
            )
            return room_id
        except Exception:
            rows = _query(
                """
                SELECT r.sha256 FROM platform.dataroom_rooms r WHERE r.room_id = %s
                """,
                params=[room_id],
            )
            if rows:
                winner = self.find_by_hash(rows[0]["sha256"])
                if winner:
                    return winner["room_id"]
            raise

    def get_initial_extraction(self, room_id: str) -> dict | None:
        rows = _query(
            "SELECT initial_extraction FROM platform.dataroom_rooms WHERE room_id = %s",
            params=[room_id],
        )
        if not rows or rows[0]["initial_extraction"] is None:
            return None
        blob = rows[0]["initial_extraction"]
        return json.loads(blob) if isinstance(blob, str) else blob

    def save_initial_extraction(self, room_id: str, extraction: dict) -> bool:
        """Snapshot the first extraction ever saved for this room. Write-once:
        returns False (and writes nothing) when a snapshot already exists."""
        rows = _query(
            """
            UPDATE platform.dataroom_rooms
            SET initial_extraction = %s::jsonb, initial_extraction_at = now()
            WHERE room_id = %s AND initial_extraction IS NULL
            RETURNING room_id
            """,
            params=[json.dumps(extraction), room_id],
        )
        return bool(rows)
