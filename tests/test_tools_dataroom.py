import json

import pytest

import server.mcp_server as srv
from server.extraction_transport import ENTITY_LISTS, REVENUE_HEADER


_IDENTITY = {"user_slug": "acme", "user_id": 7}
_SAMPLE = {"deal": {"name": "Test Room"}}


def test_rejects_none_identity(monkeypatch):
    monkeypatch.setattr(srv, "get_current_identity", lambda: None)
    out = json.loads(srv.save_dataroom_extraction(extraction=_SAMPLE))
    assert out == {"error": "Could not identify user"}


@pytest.mark.parametrize("bad", [{}, [], "x", None])
def test_rejects_non_object_extraction(monkeypatch, bad):
    monkeypatch.setattr(srv, "get_current_identity", lambda: dict(_IDENTITY))
    out = json.loads(srv.save_dataroom_extraction(extraction=bad))
    assert "non-empty ExtractionResult" in out["error"]


def test_rejects_oversize_extraction(monkeypatch):
    monkeypatch.setattr(srv, "get_current_identity", lambda: dict(_IDENTITY))
    monkeypatch.setattr(srv, "_MAX_EXTRACTION_BYTES", 10)
    out = json.loads(srv.save_dataroom_extraction(extraction=_SAMPLE))
    assert "too large" in out["error"]


def test_happy_path_mints_and_reports(monkeypatch):
    monkeypatch.setattr(srv, "get_current_identity", lambda: dict(_IDENTITY))
    seen = {}

    def fake_save(**kw):
        seen.update(kw)
        return "11111111-2222-3333-4444-555555555555"

    monkeypatch.setattr(srv._extraction_store, "save", fake_save)
    out = json.loads(srv.save_dataroom_extraction(
        extraction=_SAMPLE, label="  Bison Whitetail  "))
    assert out["extraction_id"] == "11111111-2222-3333-4444-555555555555"
    assert out["label"] == "Bison Whitetail"
    assert out["saved"] is True
    assert out["stored"] == {key: 0 for key in ENTITY_LISTS}
    assert seen["user_id"] == 7
    assert seen["extraction"] == _SAMPLE
    assert seen["label"] == "Bison Whitetail"
    assert seen["extraction_id"] is None           # first save: no id passed


def test_resave_passes_extraction_id_through(monkeypatch):
    monkeypatch.setattr(srv, "get_current_identity", lambda: dict(_IDENTITY))
    seen = {}

    def fake_save(**kw):
        seen.update(kw)
        return kw["extraction_id"]

    monkeypatch.setattr(srv._extraction_store, "save", fake_save)
    out = json.loads(srv.save_dataroom_extraction(
        extraction=_SAMPLE, extraction_id="abc-id"))
    assert out["extraction_id"] == "abc-id"
    assert seen["extraction_id"] == "abc-id"


def test_csv_kit_expands_before_store(monkeypatch):
    monkeypatch.setattr(srv, "get_current_identity", lambda: dict(_IDENTITY))
    seen = {}

    def fake_save(**kw):
        seen.update(kw)
        return "id-1"

    monkeypatch.setattr(srv._extraction_store, "save", fake_save)
    csv_text = (",".join(REVENUE_HEADER) + "\n"
                + "05-1,,2025-10-01,2025-12-25,OIL,oil,3605,bbl,68.4,"
                + "246582,11346,4190,231046,0.656,W,Falcon,1,1,\n")
    out = json.loads(srv.save_dataroom_extraction(
        extraction={"deal": {"title": "x"}, "revenue_observations": []},
        revenue_csv=csv_text,
        sources={"1": ["Check Stubs/x.pdf", "page:{n}"]},
    ))
    assert out["saved"] is True
    assert out["stored"]["revenue_observations"] == 1
    # the store received the EXPANDED canonical rows, not CSV
    row = seen["extraction"]["revenue_observations"][0]
    assert row["gross_revenue"] == 246582.0
    assert row["provenance"] == {"source_file": "Check Stubs/x.pdf",
                                 "source_locator": "page:1", "notes": None}


def test_transport_error_surfaces_as_error(monkeypatch):
    monkeypatch.setattr(srv, "get_current_identity", lambda: dict(_IDENTITY))
    out = json.loads(srv.save_dataroom_extraction(
        extraction={"deal": {"title": "x"}},
        revenue_csv="bad,header\n1,2\n", sources={}))
    assert "header line must be exactly" in out["error"]


@pytest.mark.parametrize("exc", [LookupError("id not found for this user"),
                                 ValueError("malformed extraction_id: 'x'")])
def test_store_rejections_surface_as_error(monkeypatch, exc):
    monkeypatch.setattr(srv, "get_current_identity", lambda: dict(_IDENTITY))

    def boom(**kw):
        raise exc

    monkeypatch.setattr(srv._extraction_store, "save", boom)
    out = json.loads(srv.save_dataroom_extraction(extraction=_SAMPLE, extraction_id="x"))
    assert out == {"error": str(exc)}
