# Crude Code — MCP Server & Renderer

An oil & gas data-analytics platform built as a [Model Context
Protocol](https://modelcontextprotocol.io) server plus an inline renderer that
draws results directly inside the host chat app (Claude Desktop / claude.ai).

The design principle: **the model does the thinking; the server does the
deterministic work.** There are no inner agents. The host model explores a
Postgres database with a guarded, read-only SQL tool, then publishes finished
deliverables as claude.ai artifacts it builds itself — from raw `run_sql`
data, or from `run_valuation`'s payload plus a frozen deal-sheet template.
Maps are the one surface the server still renders: it hands the renderer a
spec it validates, hydrates, and serves once.

## What's in here

| Path | What it is |
|------|------------|
| `server/` | FastMCP server (`mcp_server.py`), the valuation engine (`valuation/`), and maps (`maps/`) |
| `renderer/` | Inline React + TypeScript app (Vite, Tailwind) built to a single `dist/app.html` |
| `prompts/` | Model-facing prompts and the shared DB-schema reference |
| `utils/` | SQL guard, map handle store, identity, logging |
| `tests/` | Pytest suite covering the tools, engine, maps, and guards |

See [`CLAUDE.md`](./CLAUDE.md) for the full architecture reference.

## The tools

- **`run_sql`** — guarded, SELECT-only, capped exploration query
- **`forecast_wells`** / **`run_valuation`** — well-decline forecasting and economics, returning the data behind a claude.ai deal-sheet artifact
- **`map`** — a MapLibre GL well/unit/PLSS map
- **`get_skill`** — fetches a packaged, occasional-use procedure (e.g. dataroom extraction)

## Requirements

- Python 3.11+ and a virtualenv (`.venv`)
- Node 20+ (for the renderer build)
- A Postgres database whose schema matches `utils/schemas.py` and
  `prompts/inner/shared_schema.md`. **Populating that database (primary-source
  ingestion) is out of scope for this repo** — point `EI_DB_URL` at your own.

## Quick start

```bash
# 1. Python deps
python -m venv .venv
.venv/bin/pip install -r requirements.txt

# 2. Configure environment
cp .env.example .env   # then fill in EI_DB_URL and SUPABASE_DATABASE_URL

# 3. Run the MCP server (port 9000, /mcp endpoint)
.venv/bin/python server/mcp_server.py

# 4. Build the renderer
cd renderer && npm install && npm run build   # -> dist/app.html
```

## Testing

```bash
.venv/bin/pytest -q
```

Tests that need a database, the Anthropic API, or network access auto-skip when
the corresponding environment variable is unset.

## License

[Apache 2.0](./LICENSE).
