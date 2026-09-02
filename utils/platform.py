"""Supabase platform database connection.

Connects to Supabase for user/org identity resolution.
Reads SUPABASE_DATABASE_URL from .env.
"""

import os
from psycopg_pool import ConnectionPool

from utils.env import load_env

load_env()

_pool: ConnectionPool | None = None


def _configure_conn(conn):
    # Supabase pooler shares backends across sessions — disable psycopg3
    # prepared statements to avoid DuplicatePreparedStatement collisions.
    conn.prepare_threshold = None


def _get_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        _pool = ConnectionPool(
            conninfo=os.environ["SUPABASE_DATABASE_URL"],
            min_size=1,
            max_size=12,
            open=True,
            configure=_configure_conn,
            check=ConnectionPool.check_connection,
        )
    return _pool


def _query(sql: str, params: list | None = None) -> list[dict]:
    pool = _get_pool()
    with pool.connection() as conn:
        conn.execute("SET LOCAL search_path TO platform, public")
        cur = conn.execute(sql, params)
        if cur.description is None:
            return []
        cols = [d.name for d in cur.description]
        return [{c: v for c, v in zip(cols, row)} for row in cur.fetchall()]


def get_user_by_slug(slug: str) -> dict | None:
    """Look up a user by their URL slug — just the columns identity carries."""
    rows = _query(
        "SELECT u.id, u.slug, u.name, u.email, o.name AS org_name "
        "FROM users u JOIN organizations o ON o.id = u.org_id "
        "WHERE u.slug = %s",
        [slug],
    )
    return rows[0] if rows else None


def resolve_identity(slug: str) -> dict | None:
    """Resolve a URL slug to the identity every tool reads:
    ``{user_id, user_slug, user_name, user_email, org_name}``.

    The slug is per-user (e.g. 'jane-doe'); the org comes through the user's
    org_id. Returns None if the slug doesn't match any user. Runs on every
    tool call, so it carries only what a consumer actually reads.
    """
    user = get_user_by_slug(slug)
    if not user:
        return None
    return {
        "user_id": user["id"],
        "user_slug": user["slug"],
        "user_name": user["name"],
        "user_email": user["email"],
        "org_name": user["org_name"],
    }


