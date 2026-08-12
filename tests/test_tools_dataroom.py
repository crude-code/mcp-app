"""save_dataroom_extraction is a mint now: it returns a one-time upload URL
and moves no data itself. Storage-path behavior (expansion, caps, store
errors) lives with the HTTP handler — see tests/test_uploads.py."""
import json

import pytest

import server.mcp_server as srv


_IDENTITY = {"user_slug": "acme", "user_id": 7}


def test_rejects_none_identity(monkeypatch):
    monkeypatch.setattr(srv, "get_current_identity", lambda: None)
    out = json.loads(srv.save_dataroom_extraction(label="Room"))
    assert out == {"error": "Could not identify user"}


@pytest.mark.parametrize("label", ["", "   "])
def test_rejects_blank_label(monkeypatch, label):
    monkeypatch.setattr(srv, "get_current_identity", lambda: dict(_IDENTITY))
    out = json.loads(srv.save_dataroom_extraction(label=label))
    assert "label is required" in out["error"]


def test_mints_claimable_upload_url(monkeypatch):
    monkeypatch.setattr(srv, "get_current_identity", lambda: dict(_IDENTITY))
    monkeypatch.setenv("CC_UPLOAD_BASE_URL", "https://mcp.example.com")
    out = json.loads(srv.save_dataroom_extraction(label="  Bison Whitetail  "))
    assert out["upload_url"].startswith("https://mcp.example.com/upload/kit/")
    assert out["upload_host"] == "mcp.example.com"
    assert out["expires_in_seconds"] > 0
    token = out["upload_url"].rsplit("/", 1)[1]
    grant = srv._upload_tokens.claim(token, purpose="kit")
    assert grant.user_id == 7
    assert grant.user_slug == "acme"
    assert grant.meta == {"label": "Bison Whitetail", "extraction_id": None,
                          "room_id": None}


def test_resave_binds_extraction_id_to_token(monkeypatch):
    monkeypatch.setattr(srv, "get_current_identity", lambda: dict(_IDENTITY))
    out = json.loads(srv.save_dataroom_extraction(label="Room", extraction_id=" abc-id "))
    token = out["upload_url"].rsplit("/", 1)[1]
    grant = srv._upload_tokens.claim(token, purpose="kit")
    assert grant.meta["extraction_id"] == "abc-id"


def test_each_mint_is_a_fresh_token(monkeypatch):
    monkeypatch.setattr(srv, "get_current_identity", lambda: dict(_IDENTITY))
    first = json.loads(srv.save_dataroom_extraction(label="Room"))
    second = json.loads(srv.save_dataroom_extraction(label="Room"))
    assert first["upload_url"] != second["upload_url"]


def test_room_id_rides_in_kit_token_meta(monkeypatch):
    monkeypatch.setattr(srv, "get_current_identity", lambda: dict(_IDENTITY))
    out = json.loads(srv.save_dataroom_extraction(label="Room", room_id=" r-42 "))
    token = out["upload_url"].rsplit("/", 1)[1]
    assert srv._upload_tokens.claim(token, purpose="kit").meta["room_id"] == "r-42"


# ── open_dataroom ────────────────────────────────────────────────────────────

_SHA = "a" * 64


def test_open_rejects_none_identity(monkeypatch):
    monkeypatch.setattr(srv, "get_current_identity", lambda: None)
    out = json.loads(srv.open_dataroom(label="Room", sha256=_SHA, size_bytes=10))
    assert out == {"error": "Could not identify user"}


@pytest.mark.parametrize("kw,needle", [
    ({"label": " ", "sha256": _SHA, "size_bytes": 10}, "label is required"),
    ({"label": "R", "sha256": "abc", "size_bytes": 10}, "64-char hex"),
    ({"label": "R", "sha256": "Z" * 64, "size_bytes": 10}, "64-char hex"),
    ({"label": "R", "sha256": _SHA, "size_bytes": 0}, "byte count"),
])
def test_open_validates_arguments(monkeypatch, kw, needle):
    monkeypatch.setattr(srv, "get_current_identity", lambda: dict(_IDENTITY))
    out = json.loads(srv.open_dataroom(**kw))
    assert needle in out["error"]


def test_open_known_hash_skips_upload(monkeypatch):
    monkeypatch.setattr(srv, "get_current_identity", lambda: dict(_IDENTITY))
    monkeypatch.setattr(srv._room_store, "find_by_hash",
                        lambda sha: {"room_id": "room-1", "sha256": sha,
                                     "has_initial_extraction": False})
    out = json.loads(srv.open_dataroom(label="Room", sha256=_SHA.upper(), size_bytes=10))
    assert out["status"] == "known"
    assert out["room_id"] == "room-1"
    assert "upload_url" not in out


def test_open_new_hash_mints_room_upload(monkeypatch):
    monkeypatch.setattr(srv, "get_current_identity", lambda: dict(_IDENTITY))
    monkeypatch.setattr(srv._room_store, "find_by_hash", lambda sha: None)
    seen = {}

    def fake_create(**kw):
        seen.update(kw)
        return "room-2"

    monkeypatch.setattr(srv._room_store, "create_pending", fake_create)
    monkeypatch.setenv("CC_UPLOAD_BASE_URL", "https://mcp.example.com")
    out = json.loads(srv.open_dataroom(label=" Hilltop ", sha256=_SHA, size_bytes=999))
    assert out["status"] == "new"
    assert out["room_id"] == "room-2"
    assert out["upload_url"].startswith("https://mcp.example.com/upload/room/")
    assert seen == {"user_id": 7, "label": "Hilltop", "sha256": _SHA, "size_bytes": 999}
    token = out["upload_url"].rsplit("/", 1)[1]
    grant = srv._upload_tokens.claim(token, purpose="room")
    assert grant.meta == {"room_id": "room-2", "sha256": _SHA}
