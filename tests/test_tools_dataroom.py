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
    assert grant.meta == {"label": "Bison Whitetail", "extraction_id": None}


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
