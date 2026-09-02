"""Server-owned catalog of static (reference) map layers.

Claude names these; the server owns the SQL, the style, and the spatial clip
to the data-layer extent. These queries touch `shapes.*` (which a Claude-authored
data-layer query may NOT) and so run as trusted server queries via
utils.db.query — never through the SQL guard.

`counties` is intentionally absent: there is no county-polygon geometry table
yet. Unknown names passed in `static_layers` are ignored at hydrate time.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class StaticLayerDef:
    table: str
    geom_type: str                      # always "polygon" for v1
    label_cols: tuple[str, ...]
    simplify_tol: float                 # ST_Simplify tolerance, in degrees
    style: dict = field(default_factory=dict)


STATIC_LAYERS: dict[str, StaticLayerDef] = {
    "townships": StaticLayerDef(
        table="shapes.townships",
        geom_type="polygon",
        label_cols=("display_name",),
        simplify_tol=0.0005,
        style={"fill": "none", "line": "#888888", "width": 1},
    ),
    "sections": StaticLayerDef(
        table="shapes.sections",
        geom_type="polygon",
        label_cols=("section_number",),
        simplify_tol=0.0002,
        style={"fill": "none", "line": "#bbbbbb", "width": 0.5},
    ),
}


def build_static_layer_sql(name: str, extent_wkt: str, srid: int = 4326) -> str:
    """Clipped + simplified GeoJSON query for a named static layer.

    `extent_wkt` is a WKT polygon (the padded data-layer bounding box) built
    server-side from numeric coordinates — not user text — so embedding it in
    the SQL string is safe. Raises KeyError for an unknown layer name.
    """
    if name not in STATIC_LAYERS:
        raise KeyError(name)
    d = STATIC_LAYERS[name]
    label_select = "".join(f", {c}" for c in d.label_cols)
    return (
        f"SELECT ST_AsGeoJSON(ST_Simplify(geom, {d.simplify_tol})) AS geometry"
        f"{label_select} "
        f"FROM {d.table} "
        f"WHERE geom IS NOT NULL "
        f"AND ST_Intersects(geom, ST_GeomFromText('{extent_wkt}', {srid}))"
    )
