"""Durable user→team messages (bugs, feedback, feature/data requests).
Server-minted message_id, scoped by user_id. Backed by platform.team_messages
in Supabase — the table is the source of truth; the SES email the tool sends
alongside is best-effort delivery, tracked in email_sent.
"""
import json
import uuid

from utils.platform import _query


CATEGORIES = {"bug", "feedback", "feature_request", "data_request", "other"}


class TeamMessageStore:
    def save(self, *, user_id: int, category: str, subject: str, body: str,
             context: dict | None = None) -> str:
        """Insert a message (mints a UUID). Returns the message_id."""
        message_id = str(uuid.uuid4())
        _query(
            """
            INSERT INTO platform.team_messages
                (message_id, user_id, category, subject, body, context)
            VALUES (%s, %s, %s, %s, %s, %s::jsonb)
            """,
            params=[message_id, user_id, category, subject, body,
                    json.dumps(context) if context else None],
        )
        return message_id

    def mark_emailed(self, message_id: str) -> None:
        _query(
            "UPDATE platform.team_messages SET email_sent = true WHERE message_id = %s",
            params=[message_id],
        )

    def count_recent(self, user_id: int, *, minutes: int = 60) -> int:
        """Messages this user filed in the trailing window — the rate-cap check."""
        rows = _query(
            """
            SELECT count(*) AS n FROM platform.team_messages
            WHERE user_id = %s AND created_at > now() - make_interval(mins => %s)
            """,
            params=[user_id, minutes],
        )
        return int(rows[0]["n"])
