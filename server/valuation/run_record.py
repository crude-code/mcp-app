"""Durable per-deal state. Server-minted run_id, JSONB stage columns,
scoped by user_id. Backed by platform.valuation_runs in Supabase."""
import json
import uuid

from utils.platform import _query


_VALID_STAGES = {"wells", "forecast", "economics", "briefing_spec"}


class ValuationRunStore:
    def new_run(self, *, user_id: int, case_file: dict) -> str:
        """Mint a new run_id and insert a pending row. Returns the run_id as a UUID string."""
        run_id = str(uuid.uuid4())
        _query(
            """
            INSERT INTO platform.valuation_runs (run_id, user_id, status, case_file)
            VALUES (%s, %s, 'pending', %s::jsonb)
            """,
            params=[run_id, user_id, json.dumps(case_file)],
        )
        return run_id

    def write_stage(self, run_id: str, *, stage: str, payload: dict) -> None:
        """Write payload to a JSONB stage column. Raises ValueError on unknown stage."""
        if stage not in _VALID_STAGES:
            raise ValueError(f"unknown stage: {stage!r}; must be one of {sorted(_VALID_STAGES)}")
        _query(
            f"""
            UPDATE platform.valuation_runs
            SET {stage} = %s::jsonb, updated_at = now()
            WHERE run_id = %s
            """,
            params=[json.dumps(payload), run_id],
        )

    def update_case_file(self, run_id: str, case_file: dict) -> None:
        """Overwrite the run's case_file (the order form) and invalidate every
        stage the new terms make stale: briefing_spec and economics always
        (old numbers must never be served as the updated valuation)."""
        _query(
            f"""
            UPDATE platform.valuation_runs
            SET case_file = %s::jsonb, status = 'pending', updated_at = now(),
                briefing_spec = NULL, economics = NULL
            WHERE run_id = %s
            """,
            params=[json.dumps(case_file), run_id],
        )

    def read_stage(self, run_id: str, *, stage: str) -> dict | None:
        """Read a JSONB stage column. Returns None if run doesn't exist or stage is null."""
        if stage not in _VALID_STAGES:
            raise ValueError(f"unknown stage: {stage!r}; must be one of {sorted(_VALID_STAGES)}")
        rows = _query(
            f"SELECT {stage} AS payload FROM platform.valuation_runs WHERE run_id = %s",
            params=[run_id],
        )
        if not rows:
            return None
        payload = rows[0]["payload"]
        if payload is None:
            return None
        if isinstance(payload, str):                # psycopg sometimes returns text
            payload = json.loads(payload)
        return payload

    def get(self, run_id: str) -> dict | None:
        """Return the full record as a dict, or None if not found."""
        rows = _query(
            "SELECT * FROM platform.valuation_runs WHERE run_id = %s",
            params=[run_id],
        )
        if not rows:
            return None
        rec = rows[0]
        # psycopg returns uuid columns as uuid.UUID objects — normalise to str
        if rec.get("run_id") is not None:
            rec["run_id"] = str(rec["run_id"])
        return rec

    def mark_complete(self, run_id: str) -> None:
        """Set status='complete' — the run produced a briefing and finished.

        Without this, a successful run stays at the 'pending' minted by
        ``new_run`` (only ``mark_error`` ever moved it off), so the durable
        record couldn't distinguish done from in-flight from failed."""
        _query(
            "UPDATE platform.valuation_runs SET status = 'complete', updated_at = now() "
            "WHERE run_id = %s",
            params=[run_id],
        )

    def mark_error(self, run_id: str, *, error: str) -> None:
        """Set status='error' + error message."""
        _query(
            "UPDATE platform.valuation_runs SET status = 'error', error = %s, updated_at = now() "
            "WHERE run_id = %s",
            params=[error, run_id],
        )
