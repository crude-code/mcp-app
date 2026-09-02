"""Unit tests for utils.sql_guard — validator and guarded executor."""

import pytest

from utils.sql_guard import GuardError, validate_select


def test_rejects_insert():
    with pytest.raises(GuardError, match="must start with SELECT or WITH"):
        validate_select("INSERT INTO foo VALUES (1)")


def test_rejects_empty():
    with pytest.raises(GuardError, match="empty"):
        validate_select("")


def test_rejects_whitespace_only():
    with pytest.raises(GuardError, match="empty"):
        validate_select("   \n  ")


def test_rejects_multi_statement():
    with pytest.raises(GuardError, match="single statement"):
        validate_select("SELECT 1; SELECT 2")


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT 1 UNION ALL DELETE FROM wells",
        "WITH x AS (SELECT 1) INSERT INTO t SELECT * FROM x",
        "SELECT 1 /* hiding */ DROP TABLE wells",
        "SELECT * FROM wells; TRUNCATE wells",
        # Note: GRANT inside a line comment (-- GRANT) is stripped and NOT
        # flagged — comments are removed before keyword scanning so that
        # legitimate schema references inside comments don't false-positive.
    ],
)
def test_rejects_forbidden_keywords(sql):
    with pytest.raises(GuardError):
        validate_select(sql)


def test_allows_with_cte():
    assert validate_select("WITH x AS (SELECT 1) SELECT * FROM x").startswith("WITH")


def test_strips_trailing_semicolon():
    assert validate_select("SELECT 1;") == "SELECT 1"


from utils.schemas import WIDGET_SCHEMAS
from utils.sql_guard import validate_schema


def test_widget_schemas():
    assert WIDGET_SCHEMAS == frozenset({"public", "market", "financials", "features"})


def test_validate_schema_accepts_allowed():
    validate_schema("public")
    validate_schema("market")


@pytest.mark.parametrize("bad", ["shapes", "platform", "pg_catalog", "information_schema", ""])
def test_validate_schema_rejects_others(bad):
    with pytest.raises(GuardError, match="schema"):
        validate_schema(bad)


def test_rejects_cross_schema_reference_to_blocked_schema():
    with pytest.raises(GuardError, match="schema"):
        validate_select("SELECT * FROM platform.users")


def test_rejects_pg_catalog_reference():
    with pytest.raises(GuardError, match="schema"):
        validate_select("SELECT * FROM pg_catalog.pg_tables")


def test_rejects_information_schema_reference():
    with pytest.raises(GuardError, match="schema"):
        validate_select("SELECT * FROM information_schema.tables")


def test_allows_explicit_public_and_market():
    validate_select("SELECT * FROM public.wells")
    validate_select("SELECT * FROM market.spot_prices")


def test_allows_short_table_aliases_in_joins():
    # Real-world: aliasing tables and qualifying columns by alias must not
    # false-flag the alias as a blocked schema.
    validate_select(
        "SELECT w.operator, SUM(p.oil_bbl) FROM public.wells w "
        "JOIN public.production p ON p.well_api = w.well_api "
        "GROUP BY w.operator"
    )
    validate_select(
        "SELECT sp.wti_price, bp.gas_price FROM market.spot_prices sp "
        "JOIN market.benchmark_prices bp ON bp.price_month = sp.price_date"
    )
    # Single-char alias on a self-join.
    validate_select(
        "SELECT a.well_api, b.well_api FROM public.wells a JOIN public.wells b ON a.state = b.state"
    )


def test_still_rejects_longer_blocked_schemas():
    # The new short-prefix bypass must NOT let through real blocked schemas,
    # which are all 6+ chars.
    import pytest
    from utils.sql_guard import GuardError
    for sql in (
        "SELECT * FROM platform.users",
        "SELECT * FROM shapes.basins",
        "SELECT * FROM custom_schema.secrets",
    ):
        with pytest.raises(GuardError):
            validate_select(sql)


from utils.sql_guard import run_guarded


ROW_CAP = 3
SIZE_CAP = 200  # bytes


def test_run_guarded_returns_rows_under_caps(monkeypatch):
    fake_rows = [{"x": 1}, {"x": 2}]
    monkeypatch.setattr("utils.sql_guard._run_query", lambda sql, schema, timeout_ms: fake_rows)
    result = run_guarded("SELECT 1 AS x", schema="public", row_cap=ROW_CAP, size_cap_bytes=SIZE_CAP)
    assert result == {"rows": fake_rows, "count": 2}


def test_run_guarded_rejects_over_row_cap(monkeypatch):
    monkeypatch.setattr(
        "utils.sql_guard._run_query",
        lambda sql, schema, timeout_ms: [{"x": i} for i in range(ROW_CAP + 1)],
    )
    with pytest.raises(GuardError, match="row cap"):
        run_guarded("SELECT x FROM t", schema="public", row_cap=ROW_CAP, size_cap_bytes=SIZE_CAP)


def test_run_guarded_rejects_over_size_cap(monkeypatch):
    big = [{"x": "a" * 500}]
    monkeypatch.setattr("utils.sql_guard._run_query", lambda sql, schema, timeout_ms: big)
    with pytest.raises(GuardError, match="size cap"):
        run_guarded("SELECT x FROM t", schema="public", row_cap=ROW_CAP, size_cap_bytes=SIZE_CAP)


def test_run_guarded_passes_schema_and_timeout(monkeypatch):
    captured = {}

    def fake(sql, schema, timeout_ms):
        captured["sql"] = sql
        captured["schema"] = schema
        captured["timeout_ms"] = timeout_ms
        return []

    monkeypatch.setattr("utils.sql_guard._run_query", fake)
    run_guarded(
        "SELECT 1",
        schema="market",
        row_cap=ROW_CAP,
        size_cap_bytes=SIZE_CAP,
        timeout_ms=5000,
    )
    assert captured == {"sql": "SELECT 1", "schema": "market", "timeout_ms": 5000}


def test_run_guarded_validates_schema():
    with pytest.raises(GuardError, match="schema"):
        run_guarded("SELECT 1", schema="shapes", row_cap=3, size_cap_bytes=SIZE_CAP)


def test_run_guarded_validates_sql():
    with pytest.raises(GuardError, match="INSERT"):
        run_guarded("INSERT INTO t VALUES (1)", schema="public", row_cap=3, size_cap_bytes=SIZE_CAP)


# ---------------------------------------------------------------------------
# New bypass-closure tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("sql", [
    'SELECT * FROM "platform"."users"',
    'SELECT * FROM "pg_catalog".pg_tables',
    'SELECT * FROM "information_schema".tables',
    'SELECT * FROM "PLATFORM".users',
    'SELECT "pg_tables".tablename FROM "pg_tables"',
])
def test_rejects_quoted_blocked_schema_identifiers(sql):
    with pytest.raises(GuardError):
        validate_select(sql)


@pytest.mark.parametrize("sql", [
    "SELECT * FROM pg_class",
    "SELECT relname FROM pg_tables",
    "SELECT usename FROM pg_user",
    "SELECT * FROM pg_settings",
    "SELECT * FROM pg_stat_activity",
    "SELECT * FROM pg_shadow",
    "SELECT * FROM pg_authid",
])
def test_rejects_unqualified_catalog_tables(sql):
    with pytest.raises(GuardError, match="catalog"):
        validate_select(sql)


@pytest.mark.parametrize("sql", [
    "SELECT pg_read_file('/etc/passwd')",
    "SELECT pg_ls_dir('/tmp')",
    "SELECT pg_sleep(100)",
    "SELECT pg_terminate_backend(1)",
    "SELECT set_config('search_path', 'platform', false)",
    "SELECT lo_import('/etc/passwd')",
])
def test_rejects_dangerous_functions(sql):
    with pytest.raises(GuardError, match="function"):
        validate_select(sql)


def test_rejects_dollar_quoted_smuggled_keyword():
    # Dollar-quoted strings should be stripped; any attempt to hide a
    # forbidden keyword inside one should not slip through to the scanner.
    # The outer statement also contains DROP, which the keyword scanner
    # must still catch after stripping.
    with pytest.raises(GuardError):
        validate_select("SELECT 1; $tag$ DROP TABLE x $tag$; DROP TABLE wells")


def test_allows_column_named_pg_something():
    # A column named `pg_id` on a user table should not false-positive;
    # it's a bare column that starts with pg_ but isn't on the catalog blocklist.
    validate_select("SELECT pg_id FROM public.wells")


def test_allows_legitimate_current_timestamp_and_version():
    # Not all pg_* functions are dangerous. `current_timestamp` and
    # `version()` must still work.
    validate_select("SELECT version()")
    validate_select("SELECT current_timestamp")
