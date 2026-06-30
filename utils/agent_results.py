# utils/agent_results.py
"""Durable, user-scoped home for an agent run's renderable spec.

One row per agent run, keyed by the run's uuid run_id — the universal
identity every agent already owns (valuation's run_id; a freshly-minted uuid
for data_analyst). Backed by platform.agent_results in Supabase. Mirrors the
shape of server.valuation.run_record.ValuationRunStore (direct _query, no
in-memory cache).

The renderer's live path still reads the in-memory briefing handle by token;
this store is the durable, restart-surviving copy read by run_id (see
get_briefing_by_run).
"""
import json

from utils.platform import _query


class AgentResultStore:
    def save(self, *, run_id: str, agent_type: str, user_id: int, spec: dict) -> None:
        """Upsert the renderable spec for a run. Re-runs (same run_id) overwrite."""
        _query(
            """
            INSERT INTO platform.agent_results (run_id, user_id, agent_type, spec)
            VALUES (%s, %s, %s, %s::jsonb)
            ON CONFLICT (run_id) DO UPDATE
              SET spec = excluded.spec,
                  agent_type = excluded.agent_type,
                  user_id = excluded.user_id,
                  updated_at = now()
            """,
            params=[run_id, user_id, agent_type, json.dumps(spec, default=str)],
        )

    def get(self, *, run_id: str, user_id: int) -> dict | None:
        """Return the renderable spec for this run, scoped to the user.

        Returns None if the run doesn't exist or belongs to another user."""
        rows = _query(
            "SELECT spec FROM platform.agent_results WHERE run_id = %s AND user_id = %s",
            params=[run_id, user_id],
        )
        if not rows:
            return None
        spec = rows[0]["spec"]
        if spec is None:
            return None
        if isinstance(spec, str):                # psycopg sometimes returns text
            spec = json.loads(spec)
        return spec
