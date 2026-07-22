from server.maps.hydrate import (
    _rows_to_featurecollection,
    _bbox_of,
    _extent_wkt,
)


def test_rows_to_featurecollection_parses_geometry_string():
    rows = [
        {"geometry": '{"type":"Point","coordinates":[-104.5,40.1]}', "operator": "EOG"},
        {"geometry": '{"type":"Point","coordinates":[-104.6,40.2]}', "operator": "OXY"},
    ]
    fc = _rows_to_featurecollection(rows)
    assert fc["type"] == "FeatureCollection"
    assert len(fc["features"]) == 2
    assert fc["features"][0]["geometry"]["coordinates"] == [-104.5, 40.1]
    assert fc["features"][0]["properties"] == {"operator": "EOG"}


def test_rows_to_featurecollection_skips_null_geometry():
    rows = [{"geometry": None, "operator": "EOG"}]
    fc = _rows_to_featurecollection(rows)
    assert fc["features"] == []


def test_bbox_of_line_features():
    fc = {
        "features": [
            {"geometry": {"type": "LineString",
                          "coordinates": [[-105, 40], [-104, 41]]}},
        ]
    }
    assert _bbox_of(fc) == (-105, 40, -104, 41)


def test_bbox_of_empty_is_none():
    assert _bbox_of({"features": []}) is None


def test_extent_wkt_pads_and_closes_ring():
    wkt = _extent_wkt((-105, 40, -104, 41), pad=1.0)
    assert wkt.startswith("POLYGON((")
    assert "-106 39" in wkt   # min padded by 1.0
    assert "-103 42" in wkt   # max padded by 1.0


import server.maps.hydrate as hydrate_mod
from server.maps.hydrate import hydrate_map, MapHydrateError
import pytest


def _spec():
    return {
        "title": "EOG", "basemap": "osm", "view": {"fit": "data"},
        "static_layers": ["sections", "counties"],   # counties unknown -> ignored
        "layers": [{
            "id": "wells", "label": "EOG Wells", "geom_type": "line",
            "sql": "SELECT ST_AsGeoJSON(geom) AS geometry, operator FROM public.wells",
            "style": {}, "tooltip": ["operator"],
        }],
    }


def test_hydrate_map_builds_data_and_static_layers(monkeypatch):
    captured = {}

    def fake_run_guarded(*a, **k):
        captured.update(k)
        return {
            "rows": [{"geometry": '{"type":"LineString","coordinates":[[-105,40],[-104,41]]}',
                      "operator": "EOG"}],
            "count": 1,
        }

    monkeypatch.setattr(hydrate_mod, "run_guarded", fake_run_guarded)
    monkeypatch.setattr(hydrate_mod, "query", lambda sql: [
        {"geometry": '{"type":"Polygon","coordinates":[[[-105,40],[-104,40],[-104,41],[-105,41],[-105,40]]]}',
         "section_number": "12"},
    ])

    out = hydrate_map(_spec())

    # Security invariant: data SQL runs under WIDGET_SCHEMAS (excludes shapes),
    # never EXPLORATION_SCHEMAS.
    assert captured["allowed_schemas"] is hydrate_mod.WIDGET_SCHEMAS

    assert out["layers"][0]["feature_count"] == 1
    assert out["layers"][0]["geojson"]["features"][0]["properties"]["operator"] == "EOG"
    assert [s["id"] for s in out["static_layers"]] == ["sections"]
    assert out["static_layers"][0]["feature_count"] == 1


def test_hydrate_map_skips_static_when_no_data_geometry(monkeypatch):
    monkeypatch.setattr(hydrate_mod, "run_guarded", lambda *a, **k: {"rows": [], "count": 0})
    calls = []
    monkeypatch.setattr(hydrate_mod, "query", lambda sql: calls.append(sql) or [])
    out = hydrate_map(_spec())
    assert out["static_layers"] == []
    assert calls == []   # no extent -> no static queries run


def test_hydrate_map_wraps_guard_error(monkeypatch):
    def boom(*a, **k):
        raise hydrate_mod.GuardError("row cap")
    monkeypatch.setattr(hydrate_mod, "run_guarded", boom)
    with pytest.raises(MapHydrateError, match="wells"):
        hydrate_map(_spec())
