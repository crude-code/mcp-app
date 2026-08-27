"""Per-token in-memory store for hydrated specs.

`map` validates + hydrates the map spec server-side, mints a token, and
stashes the full hydrated spec here. The renderer reads `map_token` out of
the tool result and calls `map_read_full(token)` once on mount to fetch the
spec. (Name kept for history — it also backed briefings before that
vertical was removed.)

Frozen-snapshot semantics: each render owns its own token; tokens never get
overwritten by later calls. TTL bounds memory growth — typical session lasts
well under the default 24h.
"""

import secrets
import time
from threading import Lock


class BriefingHandleStore:
    """GIL-safe per-token store of hydrated briefing specs.

    `mint(user_slug, spec)` stashes a fully-hydrated spec under a fresh token;
    `fetch(user_slug, token)` reads it back (scoped to the owning user).
    """

    def __init__(self, ttl_seconds: float = 86_400.0) -> None:
        self._ttl = ttl_seconds
        self._lock = Lock()
        # token -> (user_slug, spec, created_at)
        self._by_token: dict[str, tuple[str, dict, float]] = {}

    def mint(self, *, user_slug: str, spec: dict) -> str:
        token = secrets.token_urlsafe(16)
        now = time.monotonic()
        with self._lock:
            self._gc_expired(now)
            self._by_token[token] = (user_slug, spec, now)
        return token

    def fetch(self, *, user_slug: str, token: str) -> dict | None:
        now = time.monotonic()
        with self._lock:
            self._gc_expired(now)
            entry = self._by_token.get(token)
            if entry is None:
                return None
            owner, spec, _ = entry
            if owner != user_slug:
                return None
            return spec

    def _gc_expired(self, now: float) -> None:
        cutoff = now - self._ttl
        expired = [t for t, (_, _, created) in self._by_token.items() if created < cutoff]
        for t in expired:
            self._by_token.pop(t, None)
