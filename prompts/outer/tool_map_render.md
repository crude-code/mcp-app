Render an interactive map inline in the chat thread. You supply the data as one or
more layers; the server runs each layer's query into geometry and draws it.
Synchronous — no agent, no waiting.

**Author and verify every layer query with `run_sql` first.** All SQL and schema
guidance lives in `run_sql`'s description (the full schema reference is appended
to it) — this tool repeats none of it on purpose, so there is one place for
column names, not several that can drift.
Build each layer's SELECT in `run_sql`, confirm it returns rows with the columns
you want, then pass that exact verified query here. Never hand `map_render` a query you
haven't run.

Call `map(spec)` where `spec` is:

{
  "title": "EOG — Weld County",
  "basemap": "osm",                 // "osm" (default) | "satellite" (v1: renders as osm) | "none"
  "view": { "fit": "data" },         // default; or { "center": [lng,lat], "zoom": 8 }
  "static_layers": ["townships", "sections"],
  "layers": [
    {
      "id": "wells",
      "label": "EOG Wells",
      "geom_type": "auto",          // point | line | polygon | auto
      "sql": "<a SELECT you already verified in run_sql>",
      "style": { "color_by": "<a column your sql selects>" },
      "tooltip": ["<columns your sql selects>"]
    }
  ]
}

Each layer's `sql` — the one thing you author — has three map-specific requirements
(everything else about writing SQL is in `run_sql`):
- It must select `ST_AsGeoJSON(geom) AS geometry`, plus every column your `style`
  and `tooltip` reference.
- It may read `public` / `market` / `financials` / `features` — NOT `shapes`.
- Get the column names right in `run_sql` before you call this tool; `map_render` will not
  teach them to you and a wrong column just fails.

Rules:
- `static_layers` are reference geometry (townships, sections). Just NAME them — the
  server writes + clips their SQL. Don't write SQL for them. (`counties` has no
  geometry yet; omit it.)
- `geom_type` is required. Use **`auto` for wells** — well geometry is mixed (a
  LINESTRING lateral where a directional survey exists, else a POINT surface
  location); `auto` draws each well by whatever geometry it has in ONE layer. Do
  NOT split wells by geometry type or filter geometry out. Use point/line/polygon
  only when a layer is uniformly one type.
- `style.color_by` colors features by one of the columns your sql selects: NUMERIC
  → gradient (`scheme`: amber/blue/green/red, default amber); CATEGORICAL (text) →
  a distinct color per value automatically. Omit `color_by` for a flat color.
  Optional `colors` pins exact hues for known category values, e.g.
  `"colors": {"PRODUCING":"#2e7d32","DUC":"#f59e0b","PERMITTED":"#1565c0"}`.
- `tooltip` lists columns shown on hover (each must be selected by your sql). Omit
  for draw-only layers.
- Array order = draw order (first = bottom). Put base data under highlights.

To change a map (add/swap a layer, recolor), call `map_render` again with the full layer
stack — a fresh map renders; there is no in-place editing.

Returns `{ surface, map_token, title, layers, static_layers }`. The map draws
itself; narrate what it shows (layer labels + feature counts).
