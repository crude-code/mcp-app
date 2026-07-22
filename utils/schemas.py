"""Schema allowlists — single source of truth.

Widget queries (re-run on every render) get a narrower set; agent
exploration via `run_sql` adds `shapes` because PLSS geometry is fine
to peek at but too heavy / too rarely useful to embed in a widget.

If you change either of these, the drift guard in
`tests/test_schema_drift.py` will fail until `prompts/outer/shared_schema.md`
matches.
"""

WIDGET_SCHEMAS = frozenset({"public", "market", "financials", "features"})
EXPLORATION_SCHEMAS = WIDGET_SCHEMAS | frozenset({"shapes"})
