import pytest
from server.maps.catalog import (
    STATIC_LAYERS,
    build_static_layer_sql,
)

EXTENT = "POLYGON((-105 40, -104 40, -104 41, -105 41, -105 40))"


def test_townships_and_sections_registered():
    assert "townships" in STATIC_LAYERS
    assert "sections" in STATIC_LAYERS


def test_build_sql_clips_and_simplifies():
    sql = build_static_layer_sql("sections", EXTENT)
    low = sql.lower()
    assert "shapes.sections" in low
    assert "st_asgeojson" in low
    assert "st_simplify" in low
    assert "st_intersects" in low
    assert EXTENT in sql  # the extent polygon is embedded


def test_build_sql_includes_label_columns():
    sql = build_static_layer_sql("townships", EXTENT)
    assert "display_name" in sql


def test_unknown_layer_raises():
    with pytest.raises(KeyError):
        build_static_layer_sql("counties", EXTENT)
