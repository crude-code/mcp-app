"""Centralized logging — writes to logs/cc.log with request tracing.

Every tool call gets a request_id that propagates through the full
call chain: server → tool → SQL. One ID per user request.

trace() also records one durable ATTEMPT row per call in
platform.tool_calls (see utils.tool_call_log). That write is best effort,
time-bounded, circuit-broken, and can never break a tool call.
"""

import logging
from logging.handlers import RotatingFileHandler
import time
import uuid
from datetime import datetime, timezone
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path

request_id: ContextVar[str] = ContextVar("request_id", default="-")

_setup_done = False


class _RequestFormatter(logging.Formatter):
    def format(self, record):
        record.request_id = request_id.get("-")
        return super().format(record)


def setup():
    """Configure file logging for all cc.* loggers. Safe to call multiple times."""
    global _setup_done
    if _setup_done:
        return
    _setup_done = True

    log_dir = Path(__file__).resolve().parent.parent / "logs"
    log_dir.mkdir(exist_ok=True)

    # 50 MB per file, keep 10 — so cc.log history stays under ~500 MB even
    # if a tenant loops hot. Rollover is synchronous on write.
    handler = RotatingFileHandler(
        log_dir / "cc.log",
        maxBytes=50_000_000,
        backupCount=10,
    )
    formatter = _RequestFormatter(
        "%(asctime)s [%(request_id)s] %(name)s %(levelname)s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    handler.setFormatter(formatter)

    root = logging.getLogger("cc")
    root.setLevel(logging.INFO)
    root.addHandler(handler)


@contextmanager
def trace(tool_name: str, **context):
    """Context manager that assigns a request_id and logs tool entry/exit with timing.

    Usage:
        with trace("run_sql", user="jane-doe"):
            ...

    Also writes one attempt row to platform.tool_calls on exit.

    `user` from context is stored as a slug — trace() is never handed an
    integer user id, and resolving one here would add a lookup to every call.

    Note what is NOT recorded: whether the call succeeded. Every tool handler
    catches its own errors inside this context and returns {"error": ...}, so
    nothing reaches here to observe, and several failure paths are early
    returns that raise nothing at all. `uncaught_error_type` therefore means
    only "an exception escaped the handler" — a NULL does not imply success.
    """
    rid = uuid.uuid4().hex[:16]
    token = request_id.set(rid)
    log = logging.getLogger("cc.server")

    ctx = " ".join(f"{k}={v}" for k, v in context.items()) if context else ""
    log.info("→ %s %s", tool_name, ctx)
    # Two clocks: a wall time for the row (the insert happens after the tool
    # finishes, so the DB cannot supply this) and a monotonic one for elapsed,
    # which a clock adjustment mid-call would otherwise distort.
    started_at = datetime.now(timezone.utc)
    t0 = time.perf_counter()
    uncaught_error_type = None
    try:
        yield rid
    except Exception as e:
        # Class name only. str(e) can carry row values and user SQL, and it is
        # already in cc.log, where retention is a bounded rotating file.
        uncaught_error_type = type(e).__name__
        log.error("✗ %s failed: %s (%.1fs)", tool_name, e,
                  time.perf_counter() - t0)
        raise
    finally:
        elapsed = time.perf_counter() - t0
        log.info("← %s (%.1fs)", tool_name, elapsed)
        # record() swallows its own exceptions; this guard is not redundant.
        # An exception raised in a finally block REPLACES the one propagating
        # out of the body, so anything failing before record's own try would
        # turn a GuardError from run_sql into a telemetry error. The import is
        # inside the guard too, so even a broken telemetry module cannot become
        # load-bearing. Tests pin both.
        try:
            from utils import tool_call_log

            tool_call_log.record(
                request_id=rid,
                tool_name=tool_name,
                user_slug=context.get("user"),
                started_at=started_at,
                duration_ms=int(elapsed * 1000),
                uncaught_error_type=uncaught_error_type,
            )
        except Exception:  # noqa: BLE001 — telemetry must never mask a tool error
            pass
        request_id.reset(token)
