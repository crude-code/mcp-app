"""Shared database connection for the platform.

Connects to the Crude Code Postgres database. Reads CC_DB_URL (legacy
name EI_DB_URL still accepted) from a .env file at the repo root if
present, otherwise from environment.

Uses a module-level connection pool (lazy-initialized) so connections
are reused across calls instead of opening a new one per query.
"""

import os
from decimal import Decimal

from psycopg.sql import SQL, Identifier, Composed
from psycopg_pool import ConnectionPool

from utils.env import load_env

load_env()

# Lazy-initialized module-level connection pool
_pool: ConnectionPool | None = None


def _get_pool() -> ConnectionPool:
    """Return the module-level pool, creating it on first use."""
    global _pool
    if _pool is None:
        conninfo = os.environ.get("CC_DB_URL") or os.environ.get("EI_DB_URL")
        if not conninfo:
            raise RuntimeError("CC_DB_URL is not set")
        _pool = ConnectionPool(
            conninfo=conninfo,
            min_size=2,
            max_size=20,
            check=ConnectionPool.check_connection,
        )
    return _pool


def _coerce(val):
    """Coerce DB types to plain Python."""
    if isinstance(val, Decimal):
        return float(val)
    return val


def query(
    sql: "str | Composed",
    params: tuple | list | None = None,
    schema: str = "public",
    statement_timeout_ms: int | None = None,
) -> list[dict]:
    """Run a SELECT and return rows as list of dicts.

    If ``statement_timeout_ms`` is set, it's applied with SET LOCAL so it
    auto-resets when the transaction ends (commit or rollback). On any
    error we roll back explicitly so the connection returns to the pool
    in a clean state — avoiding the "current transaction is aborted"
    cascade that used to poison subsequent callers.
    """
    pool = _get_pool()
    with pool.connection() as conn:
        try:
            conn.execute(SQL("SET LOCAL search_path TO {}, public").format(Identifier(schema)))
            if statement_timeout_ms is not None:
                conn.execute(
                    SQL("SET LOCAL statement_timeout = {}").format(statement_timeout_ms)
                )
            cur = conn.execute(sql, params)
            cols = [d.name for d in cur.description]
            return [{c: _coerce(v) for c, v in zip(cols, row)} for row in cur.fetchall()]
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            raise


def execute(sql: str | Composed, params: tuple | list | None = None, schema: str = "public") -> int:
    """Run an INSERT/UPDATE/DELETE and return rows affected."""
    pool = _get_pool()
    with pool.connection() as conn:
        conn.execute(SQL("SET search_path TO {}, public").format(Identifier(schema)))
        cur = conn.execute(sql, params)
        conn.commit()
        return cur.rowcount
