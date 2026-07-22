"""Centralized logging — writes to logs/cc.log with request tracing.

Every tool call gets a request_id that propagates through the full
call chain: server → tool → SQL. One ID per user request.
"""

import logging
from logging.handlers import RotatingFileHandler
import time
import uuid
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
    """
    rid = uuid.uuid4().hex[:8]
    token = request_id.set(rid)
    log = logging.getLogger("cc.server")

    ctx = " ".join(f"{k}={v}" for k, v in context.items()) if context else ""
    log.info("→ %s %s", tool_name, ctx)
    t0 = time.time()
    try:
        yield rid
    except Exception as e:
        log.error("✗ %s failed: %s (%.1fs)", tool_name, e, time.time() - t0)
        raise
    finally:
        log.info("← %s (%.1fs)", tool_name, time.time() - t0)
        request_id.reset(token)
