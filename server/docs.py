"""CrudeDoc delivery for connected sessions (the get_doc tool).

Reads platform.crudedocs — the same table the crudecode.dev site serves
/docs/<slug> from (DDL and the publish pipeline live in the site repo;
`npm run doc -- publish` there is the one write path). Serving docs through
the connector skips every constraint the public fetch lane fights — URL
allowlists, per-URL caches, injection caution — because the doc arrives as
a tool result over a connector the user installed themselves. The public
lane still exists for exactly one doc (the intro, for visitors without the
connector).

Catalog lists live docs only; load accepts live + unlisted (unlisted is the
live-test lane, mirroring the site's /docs/<slug> behavior).
"""

from utils import platform as _platform


def list_docs() -> list[dict]:
    """The catalog: slug/title/description of every live doc, index order."""
    return _platform._query(
        "SELECT slug, title, description FROM crudedocs "
        "WHERE status = 'live' ORDER BY sort_order ASC, slug ASC"
    )


def load_doc(slug: str) -> dict | None:
    """One doc's full body, or None. Unlisted docs load (the test lane)."""
    rows = _platform._query(
        "SELECT slug, title, description, type, rev, body_md FROM crudedocs "
        "WHERE slug = %s AND status IN ('live', 'unlisted') LIMIT 1",
        [slug],
    )
    return rows[0] if rows else None
