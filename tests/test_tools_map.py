import json
from server import mcp_server


VALID_SPEC = {
    "layers": [{
        "id": "wells", "geom_type": "line",
        "sql": "SELECT ST_AsGeoJSON(geom) AS geometry FROM public.wells",
    }]
}


def test_map_rejects_without_identity(no_identity):
    out = json.loads(mcp_server.map_render(spec=VALID_SPEC))
    assert "error" in out


def test_map_rejects_bad_spec(identity):
    out = json.loads(mcp_server.map_render(spec={"layers": []}))
    assert "error" in out
    assert "layers" in out["error"]


def test_map_happy_path_returns_token(identity, monkeypatch):
    monkeypatch.setattr(mcp_server, "hydrate_map", lambda spec: {
        "title": "T", "basemap": "osm", "view": {"fit": "data"},
        "static_layers": [],
        "layers": [{"id": "wells", "label": "Wells", "geojson": {"features": []},
                    "feature_count": 3}],
    })
    out = json.loads(mcp_server.map_render(spec=VALID_SPEC))
    assert out["surface"] == "map"
    assert out["map_token"]
    assert out["layers"] == [{"id": "wells", "label": "Wells", "feature_count": 3}]


def test_map_read_full_returns_spec(identity, monkeypatch):
    token = mcp_server._map_handles.mint(
        user_slug="test-slug", spec={"title": "T", "layers": []}
    )
    out = json.loads(mcp_server.map_read_full(token=token))
    assert out["spec"]["title"] == "T"


def test_map_read_full_unknown_token(identity):
    out = json.loads(mcp_server.map_read_full(token="nope"))
    assert "error" in out


def test_map_read_full_rejects_other_users_token(identity):
    # identity = "test-slug"; mint under a different slug
    token = mcp_server._map_handles.mint(
        user_slug="other-slug", spec={"title": "secret", "layers": []}
    )
    out = json.loads(mcp_server.map_read_full(token=token))
    assert "error" in out
