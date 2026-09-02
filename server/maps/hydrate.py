"""Hydrate a validated map spec into GeoJSON the renderer can draw.

Data layers run Claude's SQL through the guard (data schemas only, geometry
caps). Static layers run trusted catalog queries clipped to the combined
data extent.
"""
from __future__ import annotations

import json as _json

from utils.db import query
from utils.schemas import MAP_SCHEMAS
from utils.sql_guard import run_guarded, GuardError
from server.maps.catalog import STATIC_LAYERS, build_static_layer_sql

# Geometry is far bulkier than tabular rows — sql_guard's default 200-row / 50 KB cap
# would reject any real map. These caps bound payload size after the static
# layers are already spatially clipped to the data extent.
MAP_ROW_CAP = 5000
MAP_SIZE_CAP_BYTES = 4_000_000
MAP_TIMEOUT_MS = 15_000


class MapHydrateError(ValueError):
    """Raised when a data layer fails its guarded query."""


def _rows_to_featurecollection(rows: list[dict]) -> dict:
    features = []
    for row in rows:
        raw_geom = row.get("geometry")
        if not raw_geom:
            continue
        geom = _json.loads(raw_geom) if isinstance(raw_geom, str) else raw_geom
        props = {k: v for k, v in row.items() if k != "geometry"}
        features.append({"type": "Feature", "geometry": geom, "properties": props})
    return {"type": "FeatureCollection", "features": features}


def bbox_of(fc: dict):
    minx = miny = float("inf")
    maxx = maxy = float("-inf")
    seen = False

    def walk(coords):
        nonlocal minx, miny, maxx, maxy, seen
        if (
            isinstance(coords, (list, tuple))
            and len(coords) >= 2
            and isinstance(coords[0], (int, float))
            and isinstance(coords[1], (int, float))
        ):
            x, y = coords[0], coords[1]
            minx, miny = min(minx, x), min(miny, y)
            maxx, maxy = max(maxx, x), max(maxy, y)
            seen = True
        elif isinstance(coords, (list, tuple)):
            for c in coords:
                walk(c)

    for f in fc.get("features", []):
        walk((f.get("geometry") or {}).get("coordinates", []))
    return (minx, miny, maxx, maxy) if seen else None


def _extent_wkt(bbox, pad: float = 0.02) -> str:
    minx, miny, maxx, maxy = bbox
    minx, miny, maxx, maxy = minx - pad, miny - pad, maxx + pad, maxy + pad

    def _fmt(v: float) -> str:
        return f"{v:g}"

    return (
        f"POLYGON(({_fmt(minx)} {_fmt(miny)}, {_fmt(maxx)} {_fmt(miny)}, "
        f"{_fmt(maxx)} {_fmt(maxy)}, {_fmt(minx)} {_fmt(maxy)}, "
        f"{_fmt(minx)} {_fmt(miny)}))"
    )


def hydrate_map(spec: dict) -> dict:
    """Validated spec -> hydrated spec with per-layer GeoJSON.

    Returns the spec shape the renderer draws: data + static layers each
    carrying `geojson` (FeatureCollection) and `feature_count`.
    """
    data_layers = []
    boxes = []
    for layer in spec["layers"]:
        try:
            result = run_guarded(
                layer["sql"],
                schema="public",
                allowed_schemas=MAP_SCHEMAS,
                row_cap=MAP_ROW_CAP,
                size_cap_bytes=MAP_SIZE_CAP_BYTES,
                timeout_ms=MAP_TIMEOUT_MS,
            )
        except GuardError as e:
            raise MapHydrateError(f"layer '{layer['id']}': {e}") from e
        fc = _rows_to_featurecollection(result["rows"])
        box = bbox_of(fc)
        if box:
            boxes.append(box)
        data_layers.append(
            {**layer, "geojson": fc, "feature_count": len(fc["features"])}
        )

    static_layers = []
    if boxes:
        merged = (
            min(b[0] for b in boxes),
            min(b[1] for b in boxes),
            max(b[2] for b in boxes),
            max(b[3] for b in boxes),
        )
        extent = _extent_wkt(merged)
        for name in spec.get("static_layers", []):
            if name not in STATIC_LAYERS:
                continue  # unknown name (e.g. counties — no geometry table yet)
            rows = query(build_static_layer_sql(name, extent))
            fc = _rows_to_featurecollection(rows)
            d = STATIC_LAYERS[name]
            static_layers.append({
                "id": name,
                "label": name.title(),
                "geom_type": d.geom_type,
                "style": d.style,
                "geojson": fc,
                "feature_count": len(fc["features"]),
            })

    return {
        "title": spec["title"],
        "basemap": spec["basemap"],
        "view": spec["view"],
        "static_layers": static_layers,
        "layers": data_layers,
    }
