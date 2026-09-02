"""Chat mode (`CC_CHAT_MODE=1`): a deployment serving a host that cannot render
claude.ai artifacts or the MCP-app map. Responses drop what such a host prints
out verbatim (the deal-sheet template) or can't use (the map token); every
prompt surface gains the chat-only-host note."""
import json
import re
from pathlib import Path

import pytest

import server.mcp_server as srv
import utils.prompts as prompts

_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def identity(monkeypatch):
    monkeypatch.setattr(srv, "get_current_identity",
                        lambda: {"user_slug": "acme", "user_id": 7})


def _stub_valuation(monkeypatch):
    monkeypatch.setattr(srv, "run_valuation_for_run", lambda **kw: {"run_id": "run-9"})
    monkeypatch.setattr(srv, "compose_artifact_payload_for_run", lambda run_id: {
        "facts": {"deal_type": "Minerals / Royalty", "area": "Richland County, MT"},
        "economics": {"npv_at_centers": {"total": 1234.0, "by_status": {"PDP": 1234.0}},
                      "cube": {"strip": {"PDP": {"10": 1234.0}}},
                      "decks": ["strip"], "statuses": []},
        "assumptions": {"price_mode": "strip"},
        "evidence": [],
    })


_PARAMS = {"interest_type": "minerals", "interest": {"decimal": 0.05}}


def test_deal_valuation_chat_mode_ships_no_template(identity, monkeypatch):
    _stub_valuation(monkeypatch)
    monkeypatch.setattr(srv, "_CHAT_MODE", True)
    out = json.loads(srv.deal_valuation(run_id="run-9", params=_PARAMS))
    assert out["surface"] == "deal_sheet_chat"
    for key in ("viewer", "viewer_url", "viewer_sha256"):
        assert key not in out
    assert "cube" not in out["data"]["economics"]
    assert out["data"]["economics"]["npv_at_centers"]["total"] == 1234.0
    assert out["data"]["assumptions"] == {"price_mode": "strip"}
    assert "markdown" in out["presentation"]
    # The whole point: nothing resembling component source in the response.
    assert "import React" not in json.dumps(out)


def test_deal_valuation_default_mode_still_ships_template(identity, monkeypatch):
    _stub_valuation(monkeypatch)
    monkeypatch.setattr(srv, "_CHAT_MODE", False)
    out = json.loads(srv.deal_valuation(run_id="run-9", params=_PARAMS))
    assert out["surface"] == "deal_sheet_artifact"
    assert out["viewer"] and out["viewer_url"] and out["viewer_sha256"]
    assert "cube" in out["data"]["economics"]


_HYDRATED = {
    "title": "Kraken — Richland County", "basemap": "osm", "view": {"fit": "data"},
    "static_layers": [{"id": "sections"}],
    "layers": [{
        "id": "wells", "label": "Kraken wells", "feature_count": 3,
        "geojson": {"type": "FeatureCollection", "features": [
            {"type": "Feature", "geometry": {"type": "Point", "coordinates": [-104.1234567, 47.6543219]},
             "properties": {"well_name": "BISON 1H", "status": "PRODUCING"}},
            {"type": "Feature",
             "geometry": {"type": "LineString", "coordinates": [[-104.2, 47.7], [-104.21, 47.72]]},
             "properties": {"well_name": "BISON 2H", "status": "DUC"}},
            {"type": "Feature", "geometry": None,
             "properties": {"well_name": "NO GEOM", "status": "PERMITTED"}},
        ]},
    }],
}


def test_map_render_chat_mode_returns_rows_not_token(identity, monkeypatch):
    monkeypatch.setattr(srv, "hydrate_map", lambda spec: _HYDRATED)
    monkeypatch.setattr(srv, "_CHAT_MODE", True)
    spec = {"layers": [{"id": "wells", "geom_type": "auto",
                        "sql": "SELECT ST_AsGeoJSON(geom) AS geometry, well_name, status FROM public.wells"}]}
    out = json.loads(srv.map_render(spec=spec))
    assert out["surface"] == "map_table"
    assert "map_token" not in out
    layer = out["layers"][0]
    assert layer["feature_count"] == 3 and layer["rows_shown"] == 3
    assert layer["rows"][0] == {"well_name": "BISON 1H", "status": "PRODUCING",
                                "lng": -104.12346, "lat": 47.65432}
    assert layer["rows"][1]["lng"] == -104.2          # a lateral places at its first vertex
    assert "lng" not in layer["rows"][2]               # no geometry → properties only
    assert out["extent"] == {"min_lng": -104.21, "min_lat": 47.6543219,
                             "max_lng": -104.1234567, "max_lat": 47.72}
    assert out["static_layers"] == ["sections"]
    assert "no map is displayed" in out["presentation"]


def test_map_render_chat_mode_caps_rows(identity, monkeypatch):
    many = {**_HYDRATED, "layers": [{
        "id": "wells", "label": "Wells", "feature_count": 500,
        "geojson": {"type": "FeatureCollection", "features": [
            {"type": "Feature", "geometry": {"type": "Point", "coordinates": [-104.0, 47.0]},
             "properties": {"n": i}} for i in range(500)]},
    }]}
    monkeypatch.setattr(srv, "hydrate_map", lambda spec: many)
    monkeypatch.setattr(srv, "_CHAT_MODE", True)
    out = json.loads(srv.map_render(spec={"layers": [{"id": "w", "geom_type": "point",
                                                      "sql": "SELECT ST_AsGeoJSON(geom) AS geometry FROM public.wells"}]}))
    layer = out["layers"][0]
    assert layer["feature_count"] == 500
    assert layer["rows_shown"] == srv._CHAT_MAP_ROW_CAP == len(layer["rows"])


def test_map_render_default_mode_unchanged(identity, monkeypatch):
    monkeypatch.setattr(srv, "hydrate_map", lambda spec: _HYDRATED)
    monkeypatch.setattr(srv, "_CHAT_MODE", False)
    out = json.loads(srv.map_render(spec={"layers": [{"id": "w", "geom_type": "auto",
                                                      "sql": "SELECT ST_AsGeoJSON(geom) AS geometry FROM public.wells"}]}))
    assert out["surface"] == "map" and out["map_token"]
    assert "rows" not in out["layers"][0]


# ---- prompt surfaces ---------------------------------------------------------

def test_chat_mode_reads_the_environment(monkeypatch):
    monkeypatch.delenv("CC_CHAT_MODE", raising=False)
    assert prompts.chat_mode() is False
    for v in ("1", "true", "YES", " on "):
        monkeypatch.setenv("CC_CHAT_MODE", v)
        assert prompts.chat_mode() is True, v
    monkeypatch.setenv("CC_CHAT_MODE", "0")
    assert prompts.chat_mode() is False


def test_prompt_surfaces_gain_the_note_only_in_chat_mode(monkeypatch):
    note = prompts.chat_mode_note()
    assert note.startswith("## Chat-only host")
    monkeypatch.delenv("CC_CHAT_MODE", raising=False)
    plain = (prompts.compose_outer_system_prompt(), prompts.compose_run_sql_doc(),
             prompts.tool_doc("outer/tool_deal_valuation.md"), prompts.tool_doc("outer/tool_map_render.md"))
    assert all("Chat-only host" not in s for s in plain)
    monkeypatch.setenv("CC_CHAT_MODE", "1")
    chatty = (prompts.compose_outer_system_prompt(), prompts.compose_run_sql_doc(),
              prompts.tool_doc("outer/tool_deal_valuation.md"), prompts.tool_doc("outer/tool_map_render.md"))
    for s in chatty:
        assert s.rstrip().endswith(note.rstrip()), s[-200:]
    # Appended, never prepended: the first sentence still carries routing keywords.
    assert chatty[2].startswith(prompts.load("outer/tool_deal_valuation.md")[:80])


def test_note_names_the_chat_surfaces_the_server_emits():
    note = prompts.chat_mode_note()
    assert 'surface: "deal_sheet_chat"' in note
    assert 'surface: "map_table"' in note


# ---- deploy wiring -------------------------------------------------------------

def test_dev_env_sets_chat_mode_and_deploy_dev_installs_it():
    dev_env = (_ROOT / "deploy" / "dev.env").read_text()
    assert re.search(r"^CC_CHAT_MODE=1$", dev_env, re.M)
    script = (_ROOT / "deploy-dev.sh").read_text()
    assert "DEV_ENV_REPO=deploy/dev.env" in script
    assert "DEV_ENV_LIVE=/home/ubuntu/crudecode-dev/.env" in script
    assert '[ "$NEEDS_RESTART" = "1" ] || [ "$ENV_CHANGED" = "1" ]' in script
    # Prod must never pick this up.
    assert "dev.env" not in (_ROOT / "deploy.sh").read_text()
