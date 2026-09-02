"""Fixed-window per-key rate limiter, in memory.

One server process, so a restart resets the counters. That is right for a
cap whose job is to slow a probe — update_user's "already on another
account" refusal is an address-existence oracle — and wrong for a quota
that must survive restarts, which is why message_team counts rows in the
database instead.
"""
import time
from collections import deque


class RateLimiter:
    """`allow(key)` → True and count it, or False when `key` has already hit
    `limit` inside the trailing `window_s`. `now_fn` is injectable for tests."""

    def __init__(self, limit: int, window_s: int = 3600, now_fn=time.monotonic):
        self.limit = limit
        self.window_s = window_s
        self.now_fn = now_fn
        self._hits: dict[str, deque] = {}

    def allow(self, key: str) -> bool:
        now = self.now_fn()
        q = self._hits.setdefault(key, deque())
        while q and now - q[0] > self.window_s:
            q.popleft()
        if len(q) >= self.limit:
            return False
        q.append(now)
        return True
