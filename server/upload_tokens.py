"""One-time upload tokens: the MCP channel mints, the HTTP channel redeems.

The code-execution sandbox has no credentials, so bulk payloads (persist
kits, later dataroom zips) can't ride an authenticated request of their own.
Instead the authenticated MCP side calls `mint(...)` and hands the sandbox a
capability URL; the anonymous POST that follows proves itself by presenting
the token. Identity travels at mint time, never at upload time.

Semantics: single-use on *success* — `claim` validates without consuming, so
a mid-transfer network failure can retry the same URL inside the TTL;
`consume` retires the token only after the server has stored the payload.
Export links (server/exports.py) deliberately never consume: a browser retries,
a person double-clicks, a download manager issues range requests, and all
three must work. There the TTL alone bounds the grant.
Same in-memory pattern as utils.map_handle_store (one server process;
a lost token after a restart costs one cheap re-mint).
"""

import secrets
import time
from dataclasses import dataclass, field
from threading import Lock

DEFAULT_TTL_SECONDS = 15 * 60.0


@dataclass
class UploadGrant:
    user_id: int
    user_slug: str
    purpose: str                     # "kit" | "room" | "extraction" | "export"
    meta: dict = field(default_factory=dict)
    # Per-grant lifetime; None uses the store default. Uploads are minted for
    # a sandbox that redeems immediately; an export link is minted for a human
    # who may not be at the keyboard, so it lives longer (server/exports.py).
    ttl_seconds: float | None = None


class UploadTokenStore:
    def __init__(self, ttl_seconds: float = DEFAULT_TTL_SECONDS) -> None:
        self.ttl_seconds = ttl_seconds
        self._lock = Lock()
        # token -> (grant, created_at, consumed)
        self._by_token: dict[str, tuple[UploadGrant, float, bool]] = {}

    def mint(self, *, user_id: int, user_slug: str, purpose: str,
             meta: dict | None = None, ttl_seconds: float | None = None) -> str:
        token = secrets.token_urlsafe(24)
        grant = UploadGrant(user_id=user_id, user_slug=user_slug,
                            purpose=purpose, meta=dict(meta or {}),
                            ttl_seconds=ttl_seconds)
        now = time.monotonic()
        with self._lock:
            self._gc_expired(now)
            self._by_token[token] = (grant, now, False)
        return token

    def claim(self, token: str, *, purpose: str) -> UploadGrant | None:
        """Validate a token without consuming it. None when the token is
        unknown, expired, already consumed, or minted for another purpose."""
        now = time.monotonic()
        with self._lock:
            self._gc_expired(now)
            entry = self._by_token.get(token)
            if entry is None:
                return None
            grant, _, consumed = entry
            if consumed or grant.purpose != purpose:
                return None
            return grant

    def consume(self, token: str) -> None:
        """Retire a token after a successful upload."""
        with self._lock:
            entry = self._by_token.get(token)
            if entry is not None:
                grant, created, _ = entry
                self._by_token[token] = (grant, created, True)

    def _gc_expired(self, now: float) -> None:
        expired = [
            t for t, (grant, created, _) in self._by_token.items()
            if created < now - (grant.ttl_seconds or self.ttl_seconds)
        ]
        for t in expired:
            self._by_token.pop(t, None)
