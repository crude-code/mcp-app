"""Validation for the `map` tool's spec — the contract outer Claude emits.

Pure, no DB. Raises MapSpecError with a Claude-readable message on any
structural problem so the tool can bounce it back as {"error": ...}.
"""
from __future__ import annotations

GEOM_TYPES = {"point", "line", "polygon", "auto"}
BASEMAPS = {"osm", "satellite", "none"}


class MapSpecError(ValueError):
    """Raised when a map spec is structurally invalid."""


def parse_map_spec(raw: dict) -> dict:
    if not isinstance(raw, dict):
        raise MapSpecError("map spec must be an object")

    layers = raw.get("layers")
    if not isinstance(layers, list) or not layers:
        raise MapSpecError("map spec needs a non-empty `layers` array")

    basemap = raw.get("basemap", "osm")
    if basemap not in BASEMAPS:
        raise MapSpecError(f"basemap must be one of {sorted(BASEMAPS)}")

    static = raw.get("static_layers", [])
    if not isinstance(static, list) or not all(isinstance(s, str) and s for s in static):
        raise MapSpecError("static_layers must be an array of non-empty layer names")

    return {
        "title": raw.get("title") or "",
        "basemap": basemap,
        "view": raw.get("view") or {"fit": "data"},
        "static_layers": static,
        "layers": [_parse_layer(i, lyr) for i, lyr in enumerate(layers)],
    }


def _parse_layer(idx: int, lyr: dict) -> dict:
    if not isinstance(lyr, dict):
        raise MapSpecError(f"layer #{idx} must be an object")
    lid = lyr.get("id")
    if not lid or not isinstance(lid, str):
        raise MapSpecError(f"layer #{idx} needs a string `id`")
    geom = lyr.get("geom_type")
    if not geom:
        raise MapSpecError(f"layer '{lid}' needs a geom_type (point/line/polygon)")
    if geom not in GEOM_TYPES:
        raise MapSpecError(
            f"layer '{lid}': geom_type must be one of {sorted(GEOM_TYPES)}"
        )
    sql = lyr.get("sql")
    if not sql or not isinstance(sql, str):
        raise MapSpecError(f"layer '{lid}' needs a `sql` string")
    if "st_asgeojson" not in sql.lower():
        raise MapSpecError(
            f"layer '{lid}' sql must select geometry as "
            f"ST_AsGeoJSON(geom) AS geometry"
        )
    tooltip = lyr.get("tooltip") or []
    if not isinstance(tooltip, list) or not all(isinstance(t, str) for t in tooltip):
        raise MapSpecError(f"layer '{lid}': tooltip must be an array of field names")
    return {
        "id": lid,
        "label": lyr.get("label") or lid,
        "geom_type": geom,
        "sql": sql,
        "style": lyr.get("style") or {},
        "tooltip": tooltip,
    }
