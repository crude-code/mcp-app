"""Durable per-tool-call telemetry — best effort, never load-bearing.

Called from utils.log.trace(). Three rules:

1. A failure here must never surface to the caller. If Supabase is down,
   run_sql still runs.
2. A stall here must not delay the caller. Swallowing exceptions makes the
   write non-fatal, not non-blocking: an exhausted or unreachable pool would
   otherwise leave the user waiting after their work has finished. Pool
   acquisition and statement execution are both bounded.
3. A sustained outage must not tax every call. After a failure the writer
   opens a circuit for COOLDOWN_SECONDS and returns immediately, so a sick
   analytics DB costs a handful of dropped rows rather than latency on every
   tool call. (Bounding each attempt is not enough on its own — without the
   circuit, every call during an outage still pays the full budget.)

Records ATTEMPTS, not outcomes. See deploy/sql/002-tool-calls.sql for why
there is no success column.

Lives in utils/ rather than server/ because utils.log imports it, and a
utils -> server import would invert the layering.

Off switch: CC_TOOL_CALL_LOG=0 disables the write entirely.
"""

import logging
import os
import time

_log = logging.getLogger("cc.telemetry")

# Per-attempt budget. Small on purpose: this is a fire-and-forget insert of
# five scalars, so anything slower is a sick pool or a sick network, and in
# both cases giving up beats making the user wait. Note these bound the pool
# wait and the server-side statement; a synchronous socket operation can still
# exceed the sum under exotic network failures. Acceptable at current volume —
# the circuit below is what keeps that from being a recurring cost.
POOL_WAIT_SECONDS = 1.0
STATEMENT_TIMEOUT_MS = 1_000

# How long to stop trying after a failure.
COOLDOWN_SECONDS = 60.0

# Monotonic deadline before which no attempt is made. Wall clock is avoided so
# an NTP correction can't strand the circuit open. A plain float is fine under
# concurrency: a race costs at most one extra attempt, never correctness.
_circuit_open_until = 0.0

# Logged once per open circuit, not once per call.
_warned = False


def enabled() -> bool:
    """False when explicitly disabled, or when there's no platform DB configured.

    The env check matters for tests and local runs where SUPABASE_DATABASE_URL
    is absent — without it, every call would try to build a pool and pay a
    connect timeout before being swallowed.
    """
    if os.environ.get("CC_TOOL_CALL_LOG", "1") == "0":
        return False
    return bool(os.environ.get("SUPABASE_DATABASE_URL"))


def record(
    *,
    request_id: str,
    tool_name: str,
    user_slug: str | None,
    started_at,
    duration_ms: int,
    uncaught_error_type: str | None = None,
) -> None:
    """Insert one attempt row. Swallows every exception by design.

    `started_at` is passed in rather than defaulted in SQL: the insert happens
    after the tool finishes, so DEFAULT now() would record the END of the call.
    """
    global _circuit_open_until, _warned
    if not enabled():
        return
    if time.monotonic() < _circuit_open_until:
        return
    try:
        # Imported lazily so pool construction stays off the import path
        # (utils.log.setup() runs early in startup).
        #
        # Uses the pool directly rather than utils.platform._query (the house
        # write pattern, cf. server/team_messages.py) because _query offers no
        # way to bound acquisition or statement time, and bounding both is the
        # point of this module.
        from utils.platform import _get_pool

        with _get_pool().connection(timeout=POOL_WAIT_SECONDS) as conn:
            conn.execute(f"SET LOCAL statement_timeout = {STATEMENT_TIMEOUT_MS}")
            conn.execute(
                "INSERT INTO platform.tool_calls "
                "(request_id, tool_name, user_slug, started_at, duration_ms, "
                " uncaught_error_type) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                [request_id, tool_name, user_slug, started_at, duration_ms,
                 uncaught_error_type],
            )
        _warned = False
    except Exception as e:  # noqa: BLE001 — swallowing is the contract
        _circuit_open_until = time.monotonic() + COOLDOWN_SECONDS
        if not _warned:
            _warned = True
            _log.warning(
                "tool_call telemetry paused for %.0fs after: %s: %s",
                COOLDOWN_SECONDS, type(e).__name__, e,
            )
