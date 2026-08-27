# Crude Code Renderer

The inline MCP app that renders inside the host chat client (Claude Desktop /
claude.ai). Today it renders one surface: the `map_render` tool's MapLibre GL
well/unit/PLSS map, fetched fully hydrated from the server via
`map_read_full(map_token)`.

## Build

```bash
npm install
npm run build   # tsc -b + vite → dist/app.html (a single self-contained file)
```

The MCP server reads `dist/app.html` at startup and serves it to the host —
there is no standalone browser target. See the root [`README.md`](../README.md)
and [`CLAUDE.md`](../CLAUDE.md) for the full architecture.
