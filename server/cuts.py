"""Crude Cut delivery for connected sessions (the get_cut tool).

Reads platform.crudecuts — the same table crudecode.dev serves the homepage
shelf and /cuts/<slug> from (DDL and the publish pipeline live in the site
repo; `npm run cut -- publish` there is the one write path). A cut's
recipe_md is the rebuild recipe, written for Claude in a connected session:
every query in it passes the run_sql guard, so the session can re-run the
analysis verbatim against today's data and see what drifted since the cut's
pinned as-of.

Catalog lists live cuts only, newest № first; load accepts live + unlisted
(unlisted is the eyeball lane, mirroring the site's /cuts/<slug> behavior).
Cuts are addressable by slug or by № ("greenlake-scraps", "1", "001").
"""

from utils import platform as _platform

_FIELDS = "cut_no, slug, tag, title, dek, as_of, rev, recipe_md"


def list_cuts() -> list[dict]:
    """The catalog: №/slug/tag/title/dek/as_of of every live cut, newest first."""
    return _platform._query(
        "SELECT cut_no, slug, tag, title, dek, as_of FROM crudecuts "
        "WHERE status = 'live' ORDER BY cut_no DESC"
    )


def load_cut(ref: str) -> dict | None:
    """One cut's recipe payload, or None. Unlisted cuts load (the eyeball lane).

    ref is a slug ("greenlake-scraps") or a cut № ("1", "001", "№ 001").
    """
    ref = ref.strip().lstrip("№#").strip()
    if ref.isdigit():
        where, param = "cut_no = %s", int(ref)
    else:
        where, param = "slug = %s", ref
    rows = _platform._query(
        f"SELECT {_FIELDS} FROM crudecuts "
        f"WHERE {where} AND status IN ('live', 'unlisted') LIMIT 1",
        [param],
    )
    return rows[0] if rows else None


def record_pull(slug: str, user_slug: str | None) -> None:
    """Count one connector pull of a cut in platform.crudecut_views
    (source 'get_cut') — the same table the site's /cuts/<slug> handler
    writes web views into, so `npm run cut -- stats` in the site repo shows
    both lanes side by side (DDL lives there: deploy/sql/002-crudecut-views.sql).

    Best-effort by contract: the caller swallows any failure, because a
    readership counter must never break recipe delivery. The routing header's
    "unknown" placeholder is stored as NULL, not as a user.
    """
    _platform._query(
        "INSERT INTO crudecut_views (slug, source, user_slug) VALUES (%s, 'get_cut', %s)",
        [slug, user_slug if user_slug and user_slug != "unknown" else None],
    )
