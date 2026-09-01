"""trace() telemetry: records the right attempt row, and never breaks a tool call.

The fail-open behaviour is the whole point of these tests — if telemetry can
propagate an exception, a Supabase outage becomes a CrudeCode outage.
"""

import time
from datetime import datetime, timezone

import pytest

from utils import log as log_mod
from utils import tool_call_log


@pytest.fixture
def captured(monkeypatch):
    """Capture record() calls instead of writing to Supabase."""
    rows = []
    monkeypatch.setattr(tool_call_log, "record", lambda **kw: rows.append(kw))
    return rows


def test_records_an_attempt(captured):
    with log_mod.trace("run_sql", user="jane-doe"):
        pass

    assert len(captured) == 1
    row = captured[0]
    assert row["tool_name"] == "run_sql"
    assert row["user_slug"] == "jane-doe"
    assert row["uncaught_error_type"] is None
    assert row["duration_ms"] >= 0
    assert row["request_id"]


def test_started_at_is_the_start_not_the_end(captured):
    """The insert happens after the tool returns, so started_at must be
    captured at entry. A DB-side DEFAULT now() would be wrong by the whole
    duration."""
    before = datetime.now(timezone.utc)
    with log_mod.trace("run_valuation", user="jane-doe"):
        time.sleep(0.05)
    after = datetime.now(timezone.utc)

    started_at = captured[0]["started_at"]
    assert started_at.tzinfo is not None
    assert before <= started_at <= after
    # It must precede the end of the call by roughly the measured duration.
    assert (after - started_at).total_seconds() * 1000 >= captured[0]["duration_ms"]


def test_request_id_is_wide_enough_to_correlate(captured):
    """8 hex chars is 32 bits; collisions become likely in the tens of
    thousands of calls, and this id is now the join key to cc.log."""
    assert len(captured[0]["request_id"] if captured else "") == 0
    with log_mod.trace("map", user="jane-doe"):
        pass
    assert len(captured[-1]["request_id"]) >= 16


def test_no_success_column_is_recorded(captured):
    """Guards the design decision. Every handler catches inside the context and
    returns {"error": ...}, so a success flag sourced from here would be a lie.
    If someone adds one, this fails and they have to read 002-tool-calls.sql."""
    with log_mod.trace("run_sql", user="jane-doe"):
        pass
    assert "ok" not in captured[0]
    assert "success" not in captured[0]


def test_swallowed_handler_error_is_not_misreported_as_an_error(captured):
    """Mirrors the real handler shape: the error never escapes the context."""
    with log_mod.trace("run_sql", user="jane-doe"):
        try:
            raise ValueError("guard rejected the query")
        except ValueError:
            result = {"error": "guard rejected the query"}

    assert result["error"]
    # trace() genuinely cannot see this, and must not pretend otherwise.
    assert captured[0]["uncaught_error_type"] is None


def test_escaped_error_records_class_name_only(captured):
    class GuardError(Exception):
        pass

    with pytest.raises(GuardError):
        with log_mod.trace("run_sql", user="jane-doe"):
            raise GuardError("sql references platform.users -- 42 rows")

    row = captured[0]
    assert row["uncaught_error_type"] == "GuardError"
    # The message must not appear anywhere in the row.
    assert not any("platform" in str(v) for v in row.values())


def test_missing_user_context_is_tolerated(captured):
    with log_mod.trace("get_skill"):
        pass
    assert captured[0]["user_slug"] is None


def test_telemetry_failure_does_not_break_a_successful_call(monkeypatch):
    monkeypatch.setattr(
        tool_call_log, "record",
        lambda **kw: (_ for _ in ()).throw(RuntimeError("supabase unreachable")),
    )
    with log_mod.trace("run_sql", user="jane-doe"):
        pass  # must not raise


def test_telemetry_failure_does_not_mask_the_real_error(monkeypatch):
    monkeypatch.setattr(
        tool_call_log, "record",
        lambda **kw: (_ for _ in ()).throw(RuntimeError("supabase unreachable")),
    )

    class GuardError(Exception):
        pass

    # The caller must still see GuardError, not RuntimeError.
    with pytest.raises(GuardError):
        with log_mod.trace("run_sql", user="jane-doe"):
            raise GuardError("nope")


def test_request_id_contextvar_is_reset_even_if_telemetry_fails(monkeypatch):
    monkeypatch.setattr(
        tool_call_log, "record",
        lambda **kw: (_ for _ in ()).throw(RuntimeError()),
    )
    with log_mod.trace("map", user="jane-doe"):
        pass
    assert log_mod.request_id.get("-") == "-"


def test_record_is_a_noop_without_a_configured_db(monkeypatch):
    monkeypatch.delenv("SUPABASE_DATABASE_URL", raising=False)
    assert tool_call_log.enabled() is False
    # Returns without importing utils.platform or opening a connection.
    tool_call_log.record(
        request_id="abc", tool_name="run_sql", user_slug="x",
        started_at=datetime.now(timezone.utc), duration_ms=1,
    )


def test_kill_switch(monkeypatch):
    monkeypatch.setenv("SUPABASE_DATABASE_URL", "postgresql://unused")
    monkeypatch.setenv("CC_TOOL_CALL_LOG", "0")
    assert tool_call_log.enabled() is False


def _stub_platform(monkeypatch, pool):
    """Inject a fake utils.platform so these tests don't need the DB driver."""
    import sys
    import types

    stub = types.ModuleType("utils.platform")
    stub._get_pool = lambda: pool
    monkeypatch.setitem(sys.modules, "utils.platform", stub)


@pytest.fixture
def live_telemetry(monkeypatch):
    """Telemetry enabled, circuit closed, warning state reset."""
    monkeypatch.setenv("SUPABASE_DATABASE_URL", "postgresql://unused")
    monkeypatch.delenv("CC_TOOL_CALL_LOG", raising=False)
    monkeypatch.setattr(tool_call_log, "_circuit_open_until", 0.0)
    monkeypatch.setattr(tool_call_log, "_warned", False)


class _FakeConn:
    def __init__(self, statements):
        self.statements = statements

    def execute(self, sql, params=None):
        self.statements.append((sql, params))

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _FakePool:
    def __init__(self, statements, fail=False):
        self.statements = statements
        self.fail = fail
        self.timeouts = []

    def connection(self, timeout=None):
        self.timeouts.append(timeout)
        if self.fail:
            raise RuntimeError("pool exhausted")
        return _FakeConn(self.statements)


def test_statement_timeout_is_set_before_the_insert(live_telemetry, monkeypatch):
    statements = []
    pool = _FakePool(statements)
    _stub_platform(monkeypatch, pool)

    tool_call_log.record(
        request_id="abc", tool_name="run_sql", user_slug="x",
        started_at=datetime.now(timezone.utc), duration_ms=1,
    )

    assert pool.timeouts == [tool_call_log.POOL_WAIT_SECONDS]
    assert len(statements) == 2
    first, second = statements[0][0], statements[1][0]
    assert "statement_timeout" in first
    assert str(tool_call_log.STATEMENT_TIMEOUT_MS) in first
    assert second.strip().upper().startswith("INSERT")
    # Ordering is the point: a timeout set after the INSERT protects nothing.
    assert statements.index((first, None)) == 0


def test_budgets_stay_small(live_telemetry):
    assert tool_call_log.POOL_WAIT_SECONDS <= 2.0
    assert tool_call_log.STATEMENT_TIMEOUT_MS <= 2_000


def test_pool_failure_is_swallowed_and_bounded(live_telemetry, monkeypatch):
    pool = _FakePool([], fail=True)
    _stub_platform(monkeypatch, pool)

    # Must not raise.
    tool_call_log.record(
        request_id="abc", tool_name="run_sql", user_slug="x",
        started_at=datetime.now(timezone.utc), duration_ms=1,
    )
    assert pool.timeouts == [tool_call_log.POOL_WAIT_SECONDS]


def test_circuit_opens_after_a_failure(live_telemetry, monkeypatch):
    """Bounding each attempt isn't enough: without a circuit, every call during
    an outage still pays the full budget."""
    pool = _FakePool([], fail=True)
    _stub_platform(monkeypatch, pool)

    kw = dict(request_id="abc", tool_name="run_sql", user_slug="x",
              started_at=datetime.now(timezone.utc), duration_ms=1)

    tool_call_log.record(**kw)
    assert len(pool.timeouts) == 1

    # Subsequent calls return immediately without touching the pool.
    for _ in range(5):
        tool_call_log.record(**kw)
    assert len(pool.timeouts) == 1


def test_circuit_closes_after_the_cooldown(live_telemetry, monkeypatch):
    pool = _FakePool([], fail=True)
    _stub_platform(monkeypatch, pool)
    kw = dict(request_id="abc", tool_name="run_sql", user_slug="x",
              started_at=datetime.now(timezone.utc), duration_ms=1)

    tool_call_log.record(**kw)
    assert len(pool.timeouts) == 1

    # Pretend the cooldown elapsed.
    monkeypatch.setattr(tool_call_log, "_circuit_open_until", 0.0)
    tool_call_log.record(**kw)
    assert len(pool.timeouts) == 2


def test_a_tool_call_still_works_while_the_circuit_is_open(live_telemetry, monkeypatch):
    _stub_platform(monkeypatch, _FakePool([], fail=True))
    with log_mod.trace("run_sql", user="jane-doe"):
        pass
    with log_mod.trace("run_sql", user="jane-doe"):
        pass  # neither may raise
