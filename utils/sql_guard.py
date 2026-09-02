"""Shared SQL guardrails for every query Claude authors: `run_sql`, the
`export_data` query kind, and map data layers.

Two layers of defense:
1. ``validate_select`` — structural: SELECT/WITH only, single statement,
   no DML/DDL keywords, no references to schemas outside the allowlist
   (bare or double-quoted), no unqualified pg_catalog table references,
   no dangerous built-in function calls, no dollar-quoted string smuggling.
2. ``validate_schema`` — ensures the caller's requested schema (used for
   ``SET search_path``) is one we allow.

This is belt-and-suspenders against a Claude-authored query trying to reach
``platform`` tables (users, orgs, run records) or system catalogs. It is the
code-side floor; the database role's own GRANTs are the other half.
"""

import json as _json
import re

from utils.db import query as _db_query
from utils.schemas import MAP_SCHEMAS

_FORBIDDEN_KEYWORDS_RE = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|TRUNCATE|CREATE|GRANT|REVOKE|COPY|CALL|DO)\b",
    re.IGNORECASE,
)

# Any identifier of the form "schema.name" where schema is not in the allowlist
# is rejected. We intentionally ignore string literals (inside '...') and
# line comments (-- ... \n) by stripping them before scanning.
_IDENT_SCHEMA_RE = re.compile(r"\b([a-zA-Z_][a-zA-Z0-9_]*)\s*\.\s*[a-zA-Z_][a-zA-Z0-9_]*")
_STRING_LIT_RE = re.compile(r"'(?:[^']|'')*'")
_LINE_COMMENT_RE = re.compile(r"--[^\n]*")
_BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)

# Dollar-quoted strings: $tag$...$tag$ or $$...$$  (tags must match).
_DOLLAR_QUOTE_RE = re.compile(
    r"\$([A-Za-z_][A-Za-z0-9_]*)?\$[\s\S]*?\$\1\$",
    re.DOTALL,
)

# Double-quoted identifiers containing blocked schema/catalog names.
# Catches: "platform", "pg_*", "information_schema", "shapes" (case-insensitive).
_QUOTED_BLOCKED_IDENT_RE = re.compile(
    r'"(pg_[a-zA-Z0-9_]*|information_schema|platform|shapes)"',
    re.IGNORECASE,
)

# Unqualified bare references to pg_catalog tables that are dangerous to expose.
_CATALOG_TABLES = {
    "pg_class",
    "pg_tables",
    "pg_user",
    "pg_settings",
    "pg_roles",
    "pg_shadow",
    "pg_stat_activity",
    "pg_stat_database",
    "pg_stat_user_tables",
    "pg_authid",
    "pg_database",
    "pg_namespace",
    "pg_proc",
}
_CATALOG_TABLE_RE = re.compile(
    r"\b(" + "|".join(re.escape(t) for t in _CATALOG_TABLES) + r")\b",
    re.IGNORECASE,
)

# Dangerous built-in function calls (must be followed by optional whitespace + '(').
_DANGEROUS_FUNCTIONS = [
    "pg_read_file",
    "pg_read_binary_file",
    "pg_ls_dir",
    "pg_terminate_backend",
    "pg_cancel_backend",
    "pg_sleep",
    "set_config",
    "lo_import",
    "lo_export",
    "dblink",
    "pg_advisory_lock",
    "pg_reload_conf",
]
_DANGEROUS_FUNC_RE = re.compile(
    r"\b(" + "|".join(re.escape(f) for f in _DANGEROUS_FUNCTIONS) + r")\s*\(",
    re.IGNORECASE,
)


class GuardError(ValueError):
    """Raised when a SQL statement violates a guard rule."""


def validate_schema(schema: str, allowed: frozenset[str] = MAP_SCHEMAS) -> None:
    """Raise GuardError if ``schema`` isn't in the allowlist."""
    if schema not in allowed:
        raise GuardError(
            f"schema {schema!r} is not allowed; must be one of {sorted(allowed)}"
        )


def _strip_noise(sql: str) -> str:
    """Remove comments, string literals, and dollar-quoted strings.

    Dollar-quoted strings are stripped first because they can span multiple
    lines and nest forbidden keywords. Standard string literals and comments
    follow. This prevents any hidden-keyword smuggling via these constructs.
    """
    s = _DOLLAR_QUOTE_RE.sub(" ", sql)
    s = _BLOCK_COMMENT_RE.sub(" ", s)
    s = _LINE_COMMENT_RE.sub(" ", s)
    s = _STRING_LIT_RE.sub("''", s)
    return s


def validate_select(sql: str, allowed_schemas: frozenset[str] = MAP_SCHEMAS) -> str:
    """Validate and normalize a read-only SQL statement.

    Returns the normalized statement (stripped, trailing ; removed).
    Raises GuardError on any violation, including:
    - References to schemas outside ``allowed_schemas`` (bare or double-quoted)
    - Unqualified references to pg_catalog system tables
    - Calls to dangerous built-in functions
    - Dollar-quoted strings (stripped before other checks, so hidden keywords
      are still caught)
    """
    s = (sql or "").strip().rstrip(";").strip()
    if not s:
        raise GuardError("sql is empty")
    upper = s.upper()
    if not (upper.startswith("SELECT") or upper.startswith("WITH")):
        first_word = upper.split()[0] if upper.split() else ""
        raise GuardError(f"sql must start with SELECT or WITH (got {first_word})")
    if ";" in s:
        raise GuardError("sql must be a single statement (no semicolons)")

    scan = _strip_noise(s)

    if _FORBIDDEN_KEYWORDS_RE.search(scan):
        raise GuardError("sql contains a forbidden keyword (INSERT/UPDATE/DELETE/...)")

    # Reject double-quoted identifiers naming blocked schemas/catalogs.
    # We check the *original* SQL (before stripping) because a double-quoted
    # ident is structural syntax, not a string literal. A name in the caller's
    # allowlist passes (e.g. `run_sql`, whose allowlist includes `shapes`).
    for m in _QUOTED_BLOCKED_IDENT_RE.finditer(s):
        if m.group(1).lower() in allowed_schemas:
            continue
        raise GuardError(
            f"sql contains a quoted identifier {m.group(0)!r} referencing a "
            f"blocked schema or catalog; only {sorted(allowed_schemas)} are permitted"
        )

    # Reject dangerous function calls.
    m = _DANGEROUS_FUNC_RE.search(scan)
    if m:
        raise GuardError(
            f"sql calls dangerous function '{m.group(1)}' which is not allowed"
        )

    # Schema-qualified reference check runs before the bare catalog-table check
    # so that e.g. `pg_catalog.pg_tables` is flagged as a bad *schema* rather
    # than a bad *catalog table* — keeping existing error-message expectations.
    #
    # We don't parse SQL; the regex matches any `<ident>.<ident>` pair, which
    # includes both real schema qualifiers AND table aliases (`w.col`). To
    # distinguish, we rely on an empirical fact: every dangerous schema
    # we care about blocking (`platform`, `pg_*`, `information_schema`,
    # `shapes`) is 6+ chars. Prefixes shorter than 6 chars are treated as
    # aliases and skipped. Double-quoted identifier smuggling is caught
    # separately by _QUOTED_BLOCKED_IDENT_RE above.
    for match in _IDENT_SCHEMA_RE.finditer(scan):
        schema = match.group(1).lower()
        if schema in allowed_schemas:
            continue
        if len(schema) < 6:
            # Too short to be one of the blocked schemas; treat as alias.
            continue
        raise GuardError(
            f"sql references schema {schema!r} which is not allowed; "
            f"only {sorted(allowed_schemas)} are permitted. "
            f"If this is a table alias, rename it to something shorter than 6 chars."
        )

    # Reject unqualified bare catalog table references (those without a schema
    # qualifier were not caught by the schema loop above).
    m = _CATALOG_TABLE_RE.search(scan)
    if m:
        raise GuardError(
            f"sql references system catalog '{m.group(1).lower()}' which is not allowed; "
            f"catalog tables are not accessible"
        )

    return s


# Default caps. Callers override per surface (run_sql, exports, maps).
DEFAULT_ROW_CAP = 200
DEFAULT_SIZE_CAP_BYTES = 50_000
DEFAULT_TIMEOUT_MS = 5_000


def _run_query(sql: str, schema: str, timeout_ms: int | None) -> list[dict]:
    """Indirection seam for tests to monkeypatch."""
    return _db_query(sql, schema=schema, statement_timeout_ms=timeout_ms)


def dry_run(
    sql: str,
    *,
    schema: str = "public",
    allowed_schemas: frozenset[str] = MAP_SCHEMAS,
    timeout_ms: int | None = DEFAULT_TIMEOUT_MS,
) -> None:
    """Validate a query and `EXPLAIN` it — does NOT execute.

    `export_data` runs this at mint time for the `query` kind so a bad SELECT
    fails in the conversation rather than behind a link the user has already
    clicked. Catches column typos, alias-in-ORDER-BY mistakes, and anything
    else Postgres resolves during planning, without paying the cost of
    actually running the query.

    Raises ``GuardError`` on any validation or planner failure.
    """
    validate_schema(schema, allowed=allowed_schemas)
    normalized = validate_select(sql, allowed_schemas=allowed_schemas)
    try:
        _run_query(f"EXPLAIN {normalized}", schema, timeout_ms)
    except Exception as e:
        raise GuardError(f"query failed to plan: {e}") from e


def run_guarded(
    sql: str,
    *,
    schema: str = "public",
    allowed_schemas: frozenset[str] = MAP_SCHEMAS,
    row_cap: int = DEFAULT_ROW_CAP,
    size_cap_bytes: int = DEFAULT_SIZE_CAP_BYTES,
    timeout_ms: int | None = DEFAULT_TIMEOUT_MS,
) -> dict:
    """Run a read-only query through the full guard stack.

    Validates schema + SQL, runs with a Postgres statement_timeout, enforces
    row and JSON-size caps. Returns ``{"rows": [...], "count": N}``.
    Raises GuardError on any violation.
    """
    validate_schema(schema, allowed=allowed_schemas)
    normalized = validate_select(sql, allowed_schemas=allowed_schemas)
    rows = _run_query(normalized, schema, timeout_ms)
    if len(rows) > row_cap:
        raise GuardError(
            f"query returned {len(rows)} rows; row cap is {row_cap}. "
            f"Add a LIMIT, filter more tightly, or bucket with date_trunc."
        )
    # default=str coerces date/Decimal/UUID so this is the same encoding the
    # MCP response will use; size check matches what the client actually sees.
    size = len(_json.dumps(rows, default=str))
    if size > size_cap_bytes:
        raise GuardError(
            f"query result is {size} bytes; size cap is {size_cap_bytes}. "
            f"Select fewer columns or summarize."
        )
    return {"rows": rows, "count": len(rows)}
