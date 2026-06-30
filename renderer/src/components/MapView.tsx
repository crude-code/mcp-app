import { useEffect, useRef, useState } from "react";
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { AgentChrome } from "./AgentContainer";
import type { Agent, AgentState } from "@/types";

interface MapViewProps {
  mapToken?: string;
  app?: any;
  errorMessage?: string | null;
}

// The map is not an agent, but it renders in the same console chrome as the
// agent tools (code badge + name + DONE/WORKING/ERROR pill), minus the live
// event log — there is nothing to stream.
const GIS_TOOL: Agent = {
  code: "GIS",
  name: "GIS Tool",
  description: "draws wells, units & PLSS sections on an interactive map",
};

// Two-stop ramps for numeric color_by; categorical uses style.colors directly.
const SCHEMES: Record<string, [string, string]> = {
  amber: ["#fde68a", "#b45309"],
  blue: ["#bfdbfe", "#1e3a8a"],
  green: ["#bbf7d0", "#166534"],
  red: ["#fecaca", "#991b1b"],
};
const DEFAULT_COLOR = "#1b3d5c";

// Distinct hues for categorical color_by when no explicit `colors` map is given.
const CATEGORICAL_PALETTE = [
  "#1b3d5c", "#b45309", "#166534", "#991b1b", "#6b21a8",
  "#0e7490", "#a16207", "#9d174d", "#3f6212", "#1e3a8a",
];

// Stable distinct-value -> hue map for a categorical column.
function categoricalColors(fc: any, col: string): Record<string, string> {
  const out: Record<string, string> = {};
  let i = 0;
  for (const f of fc.features || []) {
    const v = f.properties?.[col];
    if (v == null) continue;
    const key = String(v);
    if (!(key in out)) {
      out[key] = CATEGORICAL_PALETTE[i % CATEGORICAL_PALETTE.length];
      i++;
    }
  }
  return out;
}

const OSM_STYLE: any = {
  version: 8,
  sources: {
    osm: {
      type: "raster",
      tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"],
      tileSize: 256,
      attribution: "© OpenStreetMap contributors",
    },
  },
  layers: [{ id: "osm", type: "raster", source: "osm" }],
};

function basemapStyle(basemap: string): any {
  if (basemap === "none") return { version: 8, sources: {}, layers: [] };
  return OSM_STYLE; // "osm" and (v1) "satellite" both use OSM raster
}

function isNumericColumn(fc: any, col: string): boolean {
  const f = (fc.features || []).find((x: any) => x.properties?.[col] != null);
  return typeof f?.properties?.[col] === "number";
}

function numericRange(fc: any, col: string): [number, number] {
  let lo = Infinity, hi = -Infinity;
  for (const f of fc.features || []) {
    const v = f.properties?.[col];
    if (typeof v === "number") { lo = Math.min(lo, v); hi = Math.max(hi, v); }
  }
  if (lo === Infinity) return [0, 1];
  if (lo === hi) hi = lo + 1;
  return [lo, hi];
}

// Build a MapLibre color value (flat string or data-driven expression).
function colorExpr(layer: any): any {
  const style = layer.style || {};
  const col = style.color_by;
  const fc = layer.geojson;
  // Explicit pinned colors (works for numeric- or string-valued columns).
  if (col && style.colors && typeof style.colors === "object" && Object.keys(style.colors).length) {
    const match: any[] = ["match", ["to-string", ["get", col]]];
    for (const [k, v] of Object.entries(style.colors)) match.push(k, v);
    match.push(style.color || DEFAULT_COLOR); // default
    return match;
  }
  // Numeric column → continuous ramp.
  if (col && isNumericColumn(fc, col)) {
    const [lo, hi] = numericRange(fc, col);
    const [c0, c1] = SCHEMES[style.scheme] || SCHEMES.amber;
    return ["interpolate", ["linear"], ["get", col], lo, c0, hi, c1];
  }
  // Categorical column with no explicit colors → auto-assign distinct hues.
  if (col) {
    const colors = categoricalColors(fc, col);
    const entries = Object.entries(colors);
    if (entries.length === 0) return style.color || DEFAULT_COLOR;
    const match: any[] = ["match", ["to-string", ["get", col]]];
    for (const [k, v] of entries) match.push(k, v);
    match.push(style.color || DEFAULT_COLOR);
    return match;
  }
  return style.color || (style.fill && style.fill !== "none" ? style.fill : DEFAULT_COLOR);
}

function addLayer(map: maplibregl.Map, layer: any) {
  const srcId = `src-${layer.id}`;
  if (map.getSource(srcId)) return;
  map.addSource(srcId, { type: "geojson", data: layer.geojson } as any);
  const style = layer.style || {};
  const color = colorExpr(layer);

  const addLine = (id: string, width: number) =>
    map.addLayer({
      id, type: "line", source: srcId,
      paint: { "line-color": color, "line-width": width },
    });
  const addCircle = (id: string, radius: number) =>
    map.addLayer({
      id, type: "circle", source: srcId,
      paint: {
        "circle-color": color,
        "circle-radius": radius,
        "circle-stroke-width": 1,
        "circle-stroke-color": "#ffffff",
      },
    });

  if (layer.geom_type === "polygon") {
    if (style.fill && style.fill !== "none") {
      map.addLayer({
        id: layer.id, type: "fill", source: srcId,
        paint: { "fill-color": color, "fill-opacity": style.opacity ?? 0.25 },
      });
    }
    map.addLayer({
      id: `${layer.id}-outline`, type: "line", source: srcId,
      paint: {
        "line-color": style.line || (typeof color === "string" ? color : DEFAULT_COLOR),
        "line-width": style.width ?? 1,
      },
    });
  } else if (layer.geom_type === "line") {
    addLine(layer.id, style.width ?? 2);
  } else if (layer.geom_type === "auto") {
    // Mixed geometry from ONE source (e.g. wells.geom: LINESTRING lateral where a
    // survey exists, else a POINT surface location). A line sub-layer draws the
    // laterals and a circle sub-layer draws the points — MapLibre renders only
    // the features whose geometry matches each sub-layer's type.
    addLine(layer.id, style.width ?? 2);
    addCircle(`${layer.id}-pt`, 5);
  } else {
    // point
    addCircle(layer.id, style.width ?? 5);
  }
}

// All MapLibre sub-layer ids a logical layer produced (line/circle/fill share the
// layer id; polygons add `-outline`, `auto` adds `-pt`). Used by toggle + tooltip.
function sublayerIds(map: maplibregl.Map, layerId: string): string[] {
  return [layerId, `${layerId}-outline`, `${layerId}-pt`].filter((id) => map.getLayer(id));
}

function escapeHtml(s: any): string {
  return String(s ?? "—")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function wireTooltip(map: maplibregl.Map, layer: any, popup: maplibregl.Popup) {
  if (!layer.tooltip || layer.tooltip.length === 0) return;
  // Wire every sub-layer the logical layer produced (e.g. an `auto` wells layer
  // has both a line and a circle sub-layer that should both show the tooltip).
  for (const id of sublayerIds(map, layer.id)) {
    map.on("mousemove", id, (e: any) => {
      map.getCanvas().style.cursor = "pointer";
      const p = e.features?.[0]?.properties || {};
      const html = layer.tooltip
        .map((f: string) => `<div><b>${escapeHtml(f)}</b>: ${escapeHtml(p[f])}</div>`)
        .join("");
      popup.setLngLat(e.lngLat).setHTML(html).addTo(map);
    });
    map.on("mouseleave", id, () => {
      map.getCanvas().style.cursor = "";
      popup.remove();
    });
  }
}

function fitView(map: maplibregl.Map, spec: any) {
  const view = spec.view || {};
  if (view.center && typeof view.zoom === "number") {
    map.setCenter(view.center);
    map.setZoom(view.zoom);
    return;
  }
  const b = new maplibregl.LngLatBounds();
  let any = false;
  const extend = (coords: any) => {
    if (Array.isArray(coords) && typeof coords[0] === "number") {
      b.extend(coords as [number, number]); any = true;
    } else if (Array.isArray(coords)) coords.forEach(extend);
  };
  for (const layer of spec.layers || []) {
    for (const f of layer.geojson?.features || []) extend(f.geometry?.coordinates);
  }
  if (any) map.fitBounds(b, { padding: 40, duration: 0 });
}

export function MapView({ mapToken, app, errorMessage }: MapViewProps) {
  const [spec, setSpec] = useState<any | null>(null);
  const [fetchError, setFetchError] = useState<string | null>(null);
  const [hidden, setHidden] = useState<Record<string, boolean>>({});
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);

  // Fetch the full hydrated spec once.
  useEffect(() => {
    if (!app || !mapToken || spec) return;
    let cancelled = false;
    (async () => {
      try {
        const res = await app.callServerTool({
          name: "get_map_full", arguments: { token: mapToken },
        });
        if (cancelled) return;
        const text = (res?.content ?? [])
          .filter((c: any) => c.type === "text")
          .map((c: any) => c.text || "").join("");
        const data = text ? JSON.parse(text) : {};
        if (data.error) setFetchError(data.error);
        else if (data.spec) setSpec(data.spec);
        else setFetchError("map not available");
      } catch (e: any) {
        if (!cancelled) setFetchError(String(e?.message ?? e));
      }
    })();
    return () => { cancelled = true; };
  }, [app, mapToken, spec]);

  // Init MapLibre once the spec is in hand. Static layers first (bottom).
  useEffect(() => {
    if (!spec || !containerRef.current || mapRef.current) return;
    const map = new maplibregl.Map({
      container: containerRef.current,
      style: basemapStyle(spec.basemap),
      center: [-98.5, 39.5],
      zoom: 4,
    });
    map.addControl(new maplibregl.NavigationControl(), "top-right");
    mapRef.current = map;
    const popup = new maplibregl.Popup({ closeButton: false, closeOnClick: false });

    map.on("load", () => {
      for (const layer of spec.static_layers || []) addLayer(map, layer);
      for (const layer of spec.layers || []) addLayer(map, layer);
      for (const layer of spec.layers || []) wireTooltip(map, layer, popup);
      fitView(map, spec);
      map.resize();
    });

    // The iframe container has no dimensions at mount — force resizes so tiles load.
    const t = setTimeout(() => map.resize(), 100);
    const ro = new ResizeObserver(() => map.resize());
    ro.observe(containerRef.current);

    return () => {
      clearTimeout(t);
      ro.disconnect();
      map.remove();
      mapRef.current = null;
    };
  }, [spec]);

  // Apply layer visibility toggles.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !spec) return;
    const all = [...(spec.static_layers || []), ...(spec.layers || [])];
    for (const layer of all) {
      const vis = hidden[layer.id] ? "none" : "visible";
      for (const id of sublayerIds(map, layer.id)) {
        map.setLayoutProperty(id, "visibility", vis);
      }
    }
  }, [hidden, spec]);

  const err = errorMessage ?? fetchError;
  // working: still fetching the spec · done: map ready · error: surfaced by chrome.
  const state: AgentState = err ? "error" : spec ? "done" : "working";

  const allLayers = spec ? [...(spec.static_layers || []), ...(spec.layers || [])] : [];

  // Body is only built once the spec lands; while working, AgentChrome shows its
  // own spinner, and the map container mounts (triggering init) on the done render.
  const body = spec ? (
    <div>
      {spec.title && (
        <div style={{
          padding: "10px 14px", fontSize: 13, fontWeight: 600,
          color: "var(--text-primary)", borderBottom: "1px solid var(--border-default)",
        }}>
          {spec.title}
        </div>
      )}
      <div style={{ position: "relative" }}>
        <div ref={containerRef} style={{ width: "100%", height: 480 }} />
        {/* Layer toggle */}
        <div style={{
          position: "absolute", top: 10, left: 10, background: "var(--bg-surface)",
          border: "1px solid var(--border-default)", borderRadius: 6, padding: "8px 10px",
          fontSize: 12, maxWidth: 200,
        }}>
          {allLayers.map((l: any) => (
            <label key={l.id} style={{
              display: "flex", alignItems: "center", gap: 6, cursor: "pointer",
              color: "var(--text-primary)", padding: "2px 0",
            }}>
              <input
                type="checkbox"
                checked={!hidden[l.id]}
                onChange={() => setHidden((h) => ({ ...h, [l.id]: !h[l.id] }))}
              />
              {l.label}
            </label>
          ))}
        </div>
        {/* Legend for any data layer with categorical color pins */}
        <Legend layers={spec.layers || []} />
      </div>
    </div>
  ) : null;

  return (
    <AgentChrome agent={GIS_TOOL} state={state} errorMessage={err}>
      {body}
    </AgentChrome>
  );
}

function Legend({ layers }: { layers: any[] }) {
  const seen = new Set<string>();
  const entries: { label: string; color: string }[] = [];
  for (const l of layers) {
    const style = l.style || {};
    const col = style.color_by;
    let colors: Record<string, string> | null = null;
    if (style.colors && typeof style.colors === "object" && Object.keys(style.colors).length) {
      colors = style.colors;
    } else if (col && !isNumericColumn(l.geojson, col)) {
      colors = categoricalColors(l.geojson, col);
    }
    if (!colors) continue;
    for (const [k, v] of Object.entries(colors)) {
      if (seen.has(k)) continue;
      seen.add(k);
      entries.push({ label: k, color: v as string });
    }
  }
  if (entries.length === 0) return null;
  return (
    <div style={{
      position: "absolute", bottom: 10, left: 10, background: "var(--bg-surface)",
      border: "1px solid var(--border-default)", borderRadius: 6, padding: "8px 10px",
      fontSize: 11, color: "var(--text-primary)", maxHeight: 180, overflowY: "auto",
    }}>
      {entries.map((e) => (
        <div key={e.label} style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <span style={{ width: 12, height: 12, background: e.color, display: "inline-block", borderRadius: 2 }} />
          {e.label}
        </div>
      ))}
    </div>
  );
}
