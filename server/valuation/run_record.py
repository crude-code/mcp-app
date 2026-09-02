"""Durable per-deal state. Server-minted run_id, JSONB stage columns,
scoped by user_id. Backed by platform.valuation_runs in Supabase.

Three stages are live: `forecast` (deal_forecast_wells' merge target),
`economics` and `wells` (both written by deal_valuation). The table also
carries `briefing_spec`, `pdp_forecast`, `pud_forecast` and a `status` that
stays 'pending' — columns from retired designs that nothing here reads or
writes; dropping them is a migration, not a code change."""
import json
import uuid

from utils.platform import _query


_VALID_STAGES = {"wells", "forecast", "economics"}


class RunAccessError(LookupError):
    """The run_id is unknown, or the run belongs to another user."""


def require_run_owner(store, run_id: str, user_id: int | None) -> dict:
    """Load ``run_id`` and prove ``user_id`` owns it; the record on success,
    ``RunAccessError`` otherwise.

    Every path that reads or writes a run by id goes through here — the
    forecast merge, the valuation, and both ends of the export lane. Run ids
    are unguessable UUIDs, but they travel in tool responses, deal sheets and
    download links, so holding one is not proof of ownership. ``store`` is
    duck-typed (anything with ``get``) so tests can pass an in-memory fake.
    """
    rec = store.get(run_id)
    if rec is None:
        raise RunAccessError(f"unknown run_id: {run_id}")
    owner = rec.get("user_id")
    if owner is None or user_id is None or int(owner) != int(user_id):
        raise RunAccessError("run_id belongs to another user")
    return rec


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
