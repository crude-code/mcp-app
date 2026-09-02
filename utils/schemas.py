"""Schema allowlists — single source of truth.

Map data layers get the narrower set (`MAP_SCHEMAS`): geometry comes from the
server's own catalog, so a layer query has no business in `shapes`. It is
also `sql_guard`'s default, the safe one. `run_sql` and the export lane pass
`EXPLORATION_SCHEMAS`, which adds `shapes` because PLSS geometry is fine to
peek at in chat.

If you change either of these, the drift guard in
`tests/test_schema_drift.py` will fail until `prompts/outer/shared_schema.md`
matches.
"""

MAP_SCHEMAS = frozenset({"public", "market", "financials", "features"})
EXPLORATION_SCHEMAS = MAP_SCHEMAS | frozenset({"shapes"})
