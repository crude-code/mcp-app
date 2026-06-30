# Crude Code — MCP Server & Renderer

An oil & gas data-analytics platform built as a [Model Context
Protocol](https://modelcontextprotocol.io) server plus an inline renderer that
draws results directly inside the host chat app (Claude Desktop / claude.ai).

The design principle: **the model does the thinking; the server does the
deterministic work.** There are no inner agents. The host model explores a
Postgres database with a guarded, read-only SQL tool, then publishes finished
deliverables — data briefings, well valuations, and maps — by handing the server
a spec it validates, hydrates, and renders.

## What's in here

| Path | What it is |
|------|------------|
| `server/` | FastMCP server (`mcp_server.py`), the valuation engine (`valuation/`), and maps (`maps/`) |
| `renderer/` | Inline React + TypeScript app (Vite, Tailwind) built to a single `dist/app.html` |
| `prompts/` | Model-facing prompts and the shared DB-schema reference |
| `utils/` | SQL guard, spec validation/hydration, handle stores, identity, logging |
| `tests/` | Pytest suite covering the tools, engine, maps, and guards |

See [`CLAUDE.md`](./CLAUDE.md) for the full architecture reference.

## The tools

- **`run_sql`** — guarded, SELECT-only, capped exploration query
- **`run_data_analysis`** — validates + hydrates a model-authored briefing spec and renders it inline
- **`forecast_wells`** / **`run_valuation`** — well-decline forecasting and economics, producing an interactive deal sheet
- **`export_valuation_xlsx`** — a live, editable Excel model of a valuation run
- **`map`** — a MapLibre GL well/unit/PLSS map

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

For frontend iteration without the host app:

```bash
cd renderer && npm run dev   # http://localhost:5173/preview.html
```

This renders the real components against committed fixtures with hot reload.

## License

[Apache 2.0](./LICENSE).
