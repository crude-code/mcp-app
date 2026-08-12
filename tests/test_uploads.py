"""HTTP upload lane: the kit handler must run the same expand-then-store
path the old inline tool call did, gated by one-time tokens. Exercised
through a real Starlette app (fresh FastMCP instance + TestClient) so the
route wiring — path params, status codes, streaming echo — is what's
actually tested."""
import hashlib
import json

import pytest
from fastmcp import FastMCP
from starlette.testclient import TestClient

import server.uploads as uploads
from server.extraction_transport import ENTITY_LISTS, REVENUE_HEADER
from server.upload_tokens import UploadTokenStore


class FakeExtractionStore:
    def __init__(self):
        self.calls = []
        self.raise_exc = None

    def save(self, **kw):
        if self.raise_exc is not None:
            raise self.raise_exc
        self.calls.append(kw)
        return "11111111-2222-3333-4444-555555555555"


@pytest.fixture
def rig():
    mcp = FastMCP("upload-test")
    tokens = UploadTokenStore(ttl_seconds=60.0)
    store = FakeExtractionStore()
    uploads.register_upload_routes(mcp, tokens=tokens, extraction_store=store)
    client = TestClient(mcp.http_app())
    return client, tokens, store


def _kit_token(tokens, **meta):
    defaults = {"label": "Bison Whitetail", "extraction_id": None}
    defaults.update(meta)
    return tokens.mint(user_id=7, user_slug="acme", purpose="kit", meta=defaults)


_SAMPLE_KIT = {"extraction": {"deal": {"name": "Test Room"}},
               "revenue_csv": None, "production_csv": None, "sources": {}}


def test_bad_token_is_410(rig):
    client, _, store = rig
    r = client.post("/upload/kit/not-a-token", json=_SAMPLE_KIT)
    assert r.status_code == 410
    assert store.calls == []


def test_happy_path_stores_and_consumes(rig):
    client, tokens, store = rig
    token = _kit_token(tokens)
    r = client.post(f"/upload/kit/{token}", json=_SAMPLE_KIT)
    assert r.status_code == 200
    body = r.json()
    assert body["saved"] is True
    assert body["extraction_id"] == "11111111-2222-3333-4444-555555555555"
    assert body["label"] == "Bison Whitetail"
    assert body["stored"] == {key: 0 for key in ENTITY_LISTS}
    assert store.calls[0]["user_id"] == 7
    assert store.calls[0]["extraction_id"] is None
    # single-use on success: the same URL must not work twice
    r2 = client.post(f"/upload/kit/{token}", json=_SAMPLE_KIT)
    assert r2.status_code == 410
    assert len(store.calls) == 1


def test_csv_kit_expands_before_store(rig):
    client, tokens, store = rig
    token = _kit_token(tokens)
    csv_text = (",".join(REVENUE_HEADER) + "\n"
                + "05-1,,2025-10-01,2025-12-25,OIL,oil,3605,bbl,68.4,"
                + "246582,11346,4190,231046,0.656,W,Falcon,1,1,\n")
    kit = {"extraction": {"deal": {"title": "x"}, "revenue_observations": []},
           "revenue_csv": csv_text, "production_csv": None,
           "sources": {"1": ["Check Stubs/x.pdf", "page:{n}"]}}
    r = client.post(f"/upload/kit/{token}", json=kit)
    assert r.status_code == 200
    assert r.json()["stored"]["revenue_observations"] == 1
    row = store.calls[0]["extraction"]["revenue_observations"][0]
    assert row["gross_revenue"] == 246582.0
    assert row["provenance"] == {"source_file": "Check Stubs/x.pdf",
                                 "source_locator": "page:1", "notes": None}


def test_transport_error_is_422_and_token_survives(rig):
    client, tokens, store = rig
    token = _kit_token(tokens)
    kit = {"extraction": {"deal": {"title": "x"}},
           "revenue_csv": "bad,header\n1,2\n", "production_csv": None, "sources": {}}
    r = client.post(f"/upload/kit/{token}", json=kit)
    assert r.status_code == 422
    assert "header line must be exactly" in r.json()["error"]
    # a failed upload must not burn the token — the fixed kit retries the same URL
    r2 = client.post(f"/upload/kit/{token}", json=_SAMPLE_KIT)
    assert r2.status_code == 200


def test_non_json_body_is_400(rig):
    client, tokens, _ = rig
    token = _kit_token(tokens)
    r = client.post(f"/upload/kit/{token}", content=b"not json")
    assert r.status_code == 400


@pytest.mark.parametrize("kit", [
    {"revenue_csv": None},                       # no extraction at all
    {"extraction": {}},                          # empty extraction
    {"extraction": "text"},                      # wrong type
])
def test_missing_extraction_is_400(rig, kit):
    client, tokens, _ = rig
    token = _kit_token(tokens)
    r = client.post(f"/upload/kit/{token}", json=kit)
    assert r.status_code == 400


def test_oversize_expanded_extraction_is_413(rig, monkeypatch):
    client, tokens, _ = rig
    monkeypatch.setattr(uploads, "MAX_EXTRACTION_BYTES", 10)
    token = _kit_token(tokens)
    r = client.post(f"/upload/kit/{token}", json=_SAMPLE_KIT)
    assert r.status_code == 413


def test_store_rejection_is_409_and_token_survives(rig):
    client, tokens, store = rig
    store.raise_exc = LookupError("extraction_id x not found for this user")
    token = _kit_token(tokens, extraction_id="x")
    r = client.post(f"/upload/kit/{token}", json=_SAMPLE_KIT)
    assert r.status_code == 409
    assert "not found" in r.json()["error"]
    store.raise_exc = None
    assert client.post(f"/upload/kit/{token}", json=_SAMPLE_KIT).status_code == 200


def test_resave_meta_reaches_store(rig):
    client, tokens, store = rig
    token = _kit_token(tokens, extraction_id="abc-id", label="Room v2")
    r = client.post(f"/upload/kit/{token}", json=_SAMPLE_KIT)
    assert r.status_code == 200
    assert store.calls[0]["extraction_id"] == "abc-id"
    assert store.calls[0]["label"] == "Room v2"


def test_echo_reports_bytes_and_sha256(rig):
    client, tokens, _ = rig
    token = _kit_token(tokens)
    blob = b"x" * 100_000
    r = client.post(f"/upload/echo/{token}", content=blob)
    assert r.status_code == 200
    assert r.json() == {"bytes_received": 100_000,
                        "sha256": hashlib.sha256(blob).hexdigest()}
    # echo probes never consume — repeatable on one token within TTL
    assert client.post(f"/upload/echo/{token}", content=b"y").status_code == 200


def test_echo_requires_valid_token(rig):
    client, _, _ = rig
    assert client.post("/upload/echo/nope", content=b"x").status_code == 410
