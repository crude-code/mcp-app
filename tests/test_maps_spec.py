import pytest
from server.maps.spec import parse_map_spec, MapSpecError

VALID_LAYER = {
    "id": "wells",
    "label": "EOG Wells",
    "geom_type": "line",
    "sql": "SELECT ST_AsGeoJSON(geom) AS geometry, operator FROM public.wells WHERE operator='EOG'",
    "style": {"color_by": "operator"},
    "tooltip": ["operator"],
}


def test_parse_valid_spec_fills_defaults():
    out = parse_map_spec({"layers": [VALID_LAYER]})
    assert out["basemap"] == "osm"
    assert out["view"] == {"fit": "data"}
    assert out["static_layers"] == []
    assert out["layers"][0]["label"] == "EOG Wells"


def test_label_defaults_to_id():
    layer = {**VALID_LAYER}
    del layer["label"]
    out = parse_map_spec({"layers": [layer]})
    assert out["layers"][0]["label"] == "wells"


def test_accepts_auto_geom_type():
    layer = {**VALID_LAYER, "geom_type": "auto"}
    out = parse_map_spec({"layers": [layer]})
    assert out["layers"][0]["geom_type"] == "auto"


def test_rejects_empty_layers():
    with pytest.raises(MapSpecError, match="layers"):
        parse_map_spec({"layers": []})


def test_rejects_bad_geom_type():
    bad = {**VALID_LAYER, "geom_type": "blob"}
    with pytest.raises(MapSpecError, match="geom_type"):
        parse_map_spec({"layers": [bad]})


def test_rejects_missing_sql():
    bad = {**VALID_LAYER}
    del bad["sql"]
    with pytest.raises(MapSpecError, match="sql"):
        parse_map_spec({"layers": [bad]})


def test_rejects_sql_without_geojson():
    bad = {**VALID_LAYER, "sql": "SELECT operator FROM public.wells"}
    with pytest.raises(MapSpecError, match="ST_AsGeoJSON"):
        parse_map_spec({"layers": [bad]})


def test_rejects_bad_basemap():
    with pytest.raises(MapSpecError, match="basemap"):
        parse_map_spec({"layers": [VALID_LAYER], "basemap": "googlemaps"})


def test_rejects_missing_geom_type():
    bad = {**VALID_LAYER}
    del bad["geom_type"]
    with pytest.raises(MapSpecError, match="geom_type"):
        parse_map_spec({"layers": [bad]})


def test_rejects_empty_static_layer_name():
    with pytest.raises(MapSpecError, match="static_layers"):
        parse_map_spec({"layers": [VALID_LAYER], "static_layers": [""]})


def test_rejects_missing_layers_key():
    with pytest.raises(MapSpecError, match="layers"):
        parse_map_spec({})
