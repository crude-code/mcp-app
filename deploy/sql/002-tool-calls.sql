-- Durable per-tool-call telemetry: platform.tool_calls.
--
-- Apply against SUPABASE_DATABASE_URL:
--   psql "$SUPABASE_DATABASE_URL" -f deploy/sql/002-tool-calls.sql
-- Additive and idempotent — safe to re-run.
--
-- Why this exists: platform.agent_sessions used to carry per-call timing and
-- outcome, and it stopped being written when the inner-agent surface was
-- removed. Since then trace() has written to logs/cc.log only, so run_sql,
-- map, get_skill and export_data leave no durable trace at all and questions
-- like "how many people ever completed a workflow" are unanswerable.
--
-- Deliberately narrow. No arguments, no result payloads, no error messages:
-- run_sql's arguments ARE user queries, and raw exception text routinely
-- carries row values, so storing either would recreate the data-governance
-- problem in a new table. tool_name + user + time answers the usage questions.
--
-- user_slug, not user_id: trace() is handed a slug by every call site and
-- get_skill never resolves an integer id at all. Storing the slug keeps the
-- write off the identity path; join to platform.users(slug) to attribute.
--
-- ── On the absence of a success column ──────────────────────────────────────
-- There is deliberately no `ok`. Every tool handler catches its own errors
-- INSIDE the trace() context and returns {"error": ...} as a JSON string, so
-- nothing reaches trace() to observe. Several failures aren't exceptions at
-- all — missing-label and unknown-kind are plain early returns. A success
-- column populated from trace() would therefore read true for every failure
-- in the system, which is worse than having no column.
--
-- So this table records ATTEMPTS. `uncaught_error_type` is named for exactly
-- what it can observe: the rare exception that escapes a handler. Per-call
-- success needs a layer that can see the returned payload; that's a later
-- change, and until then completion is measured by joining attempts here to
-- durable artifacts (e.g. save_dataroom_extraction attempts vs rows in
-- platform.dataroom_extractions).

CREATE TABLE IF NOT EXISTS platform.tool_calls (
    id                  bigserial   PRIMARY KEY,
    request_id          text        NOT NULL,
    tool_name           text        NOT NULL,
    user_slug           text,
    -- Wall time the tool STARTED, supplied by the caller. No DEFAULT now():
    -- the insert happens in trace()'s finally, after the tool returns, so a
    -- server-side default would stamp the END of the call and be wrong by the
    -- full duration on anything slow.
    started_at          timestamptz NOT NULL,
    duration_ms         integer,
    -- When the row was written. Together with started_at + duration_ms this
    -- exposes telemetry lag, which is how you tell a slow tool from a slow
    -- analytics DB.
    recorded_at         timestamptz NOT NULL DEFAULT now(),
    -- Exception class name only (e.g. 'PoolTimeout'), never str(e). NULL is
    -- the normal case and does NOT imply the call succeeded — see above.
    uncaught_error_type text
);

-- Usage over time, the query this table exists for.
CREATE INDEX IF NOT EXISTS tool_calls_started_at
    ON platform.tool_calls (started_at DESC);

-- Per-user funnels and retention.
CREATE INDEX IF NOT EXISTS tool_calls_user_started
    ON platform.tool_calls (user_slug, started_at DESC);

-- Per-tool volume.
CREATE INDEX IF NOT EXISTS tool_calls_tool_started
    ON platform.tool_calls (tool_name, started_at DESC);

-- Correlate a row back to logs/cc.log, which holds the detail this table omits.
CREATE INDEX IF NOT EXISTS tool_calls_request_id
    ON platform.tool_calls (request_id);
