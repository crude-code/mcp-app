"""Self-service profile updates — the caller's own platform.users row.

The claim lane for the CrudeDocs funnel. `GET /new-account`
(server/accounts.py) mints an anonymous row: email NULL, name "CrudeDoc
visitor". That account works immediately but is unrecoverable — lose the
connector URL and there is no way back in, and no channel to reach the
person. `update_user` is how an email gets attached from inside the chat,
which is what the intro CrudeDoc already promises ("an email can optionally
be attached later, in chat").

Auth: the slug in the connector URL *is* the credential, so a caller writes
its own row and no other — user_id comes from the resolved identity, never
from a tool argument.

**Attach, don't reassign.** An email that arrived with the account (web
signup → provisioning) cannot be changed here: a leaked connector URL would
otherwise be an account takeover, quietly redirecting recovery mail. An
email attached in chat *can* be corrected in chat — typos are the common
case and there is no other repair path — which is why the source is recorded
in `notes.email_source`.

**Unverified by design.** There is no verification lane (utils.ses only ever
mails the team), so a stored address is a claim, not a proof:
`notes.email_verified` stays false and the tool says so in its response.
Anything that later treats email as identity must verify it first.
"""

import json
import re
from datetime import datetime, timezone

from server.accounts import PLACEHOLDER_NAME
from utils.platform import _query

# The shape the site's signup contract validates (crudecode-site
# src/lib/signup.ts), so an address accepted in chat is accepted there too.
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

NAME_MAX = 120
IN_CHAT = "in_chat"


def normalize_email(raw: str) -> str:
    """Trim + lowercase — the same treatment /api/signup gives an address."""
    return (raw or "").strip().lower()


def normalize_name(raw: str) -> str:
    """Trim and collapse interior whitespace."""
    return " ".join((raw or "").split())


def notes_of(row: dict) -> dict:
    """The row's `notes` jsonb as a dict — tolerating the JSON string some
    drivers hand back, so every reader (locking, the tool's merge) sees one
    shape."""
    raw = row.get("notes")
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except ValueError:
            return {}
    return raw or {}


def email_is_locked(row: dict) -> bool:
    """True when this row's email may not be changed in chat.

    Locked = an address is set and it did *not* come from this tool, i.e. it
    arrived from the web signup → provisioning path, where it is the
    account's recovery channel and a real person's inbox.
    """
    if not row.get("email"):
        return False
    return notes_of(row).get("email_source") != IN_CHAT


def profile_state(row: dict, changed: list[str] | None = None) -> dict:
    """The typed state every update_user response carries."""
    email = row.get("email")
    name = row.get("name") or ""
    return {
        "success": True,
        "email": email,
        "name": name,
        "email_attached": bool(email),
        # Never verified — see the module docstring. Stated on every response
        # so no caller has to infer it from silence.
        "email_verified": False,
        "email_locked": email_is_locked(row),
        "name_is_placeholder": name == PLACEHOLDER_NAME,
        "changed": changed or [],
    }


def plan_update(*, current: dict, email: str = "", name: str = "") -> dict:
    """Decide what an update does, given the row as it stands. Pure.

    Returns `{"error": ...}` for a refusal, else `{"email", "name",
    "changed"}` where a None field means "leave it alone" and an empty
    `changed` means the request was a no-op (already the stored value).
    """
    want_email = normalize_email(email)
    want_name = normalize_name(name)

    if not want_email and not want_name:
        return {"error": "nothing to update: pass email, name, or both"}

    new_email: str | None = None
    new_name: str | None = None
    changed: list[str] = []

    if want_email:
        if not EMAIL_RE.match(want_email):
            return {"error": f"not a valid email address: {want_email!r}"}
        stored = normalize_email(current.get("email") or "")
        if want_email != stored:
            if email_is_locked(current):
                return {"error": (
                    "this account's email was set when the account was created "
                    "and can't be changed from chat — file a message_team "
                    "request to have it changed"
                )}
            new_email = want_email
            changed.append("email")

    if want_name:
        if len(want_name) > NAME_MAX:
            return {"error": f"name is longer than {NAME_MAX} characters"}
        if want_name != (current.get("name") or ""):
            new_name = want_name
            changed.append("name")

    return {"email": new_email, "name": new_name, "changed": changed}


class UserProfileStore:
    def read(self, user_id: int) -> dict | None:
        rows = _query(
            "SELECT id, email, name, notes FROM users WHERE id = %s", [user_id]
        )
        return rows[0] if rows else None

    def email_owner(self, email: str) -> int | None:
        """user_id already holding this address, if any (case-insensitive).

        There is no unique index behind this on older databases, so the check
        is the application's job; deploy/sql/002-users-email-unique.sql adds
        the index that makes a concurrent double-claim fail loudly instead.
        """
        rows = _query(
            "SELECT id FROM users WHERE lower(email) = %s LIMIT 1", [email]
        )
        return rows[0]["id"] if rows else None

    def apply(self, *, user_id: int, email: str | None = None,
              name: str | None = None) -> None:
        """Write the planned fields. COALESCE leaves untouched what wasn't asked for."""
        patch: dict = {}
        if email is not None:
            patch = {
                "email_source": IN_CHAT,
                "email_verified": False,
                "email_attached_at": datetime.now(timezone.utc).isoformat(),
            }
        _query(
            "UPDATE users SET email = COALESCE(%s, email), "
            "name = COALESCE(%s, name), "
            "notes = COALESCE(notes, '{}'::jsonb) || %s::jsonb "
            "WHERE id = %s",
            [email, name, json.dumps(patch), user_id],
        )
