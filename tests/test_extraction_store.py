import uuid

import pytest

from server.extraction_store import ExtractionStore
from tests import VALUATION_TEST_USER_ID


@pytest.mark.db
def test_find_for_user_room_returns_newest_own_row():
    store = ExtractionStore()
    room_id = str(uuid.uuid4())
    assert store.find_for_user_room(VALUATION_TEST_USER_ID, room_id) is None
    store.save(user_id=VALUATION_TEST_USER_ID, extraction={"deal": {"name": "v1"}},
               label="first", room_id=room_id)
    eid2 = store.save(user_id=VALUATION_TEST_USER_ID, extraction={"deal": {"name": "v2"}},
                      label="second", room_id=room_id)
    rec = store.find_for_user_room(VALUATION_TEST_USER_ID, room_id)
    assert rec["extraction_id"] == eid2
    # another user's rows never surface
    assert store.find_for_user_room(VALUATION_TEST_USER_ID + 1, room_id) is None


_SAMPLE = {"deal": {"name": "Test Room"}, "wells": [{"api": "05-123-45678"}]}


@pytest.mark.db
def test_save_mints_uuid_and_round_trips():
    store = ExtractionStore()
    eid = store.save(user_id=VALUATION_TEST_USER_ID, extraction=_SAMPLE, label="Test Room")
    assert len(eid) == 36                          # uuid4 string
    rec = store.get(eid)
    assert rec["extraction"] == _SAMPLE
    assert rec["label"] == "Test Room"
    assert rec["user_id"] == VALUATION_TEST_USER_ID


@pytest.mark.db
def test_resave_updates_in_place():
    store = ExtractionStore()
    eid = store.save(user_id=VALUATION_TEST_USER_ID, extraction=_SAMPLE, label="v1")
    corrected = {**_SAMPLE, "extraction_notes": ["fixed NRI"]}
    eid2 = store.save(user_id=VALUATION_TEST_USER_ID, extraction=corrected,
                      label="v2", extraction_id=eid)
    assert eid2 == eid                             # same row, not a duplicate
    rec = store.get(eid)
    assert rec["extraction"] == corrected
    assert rec["label"] == "v2"


@pytest.mark.db
def test_resave_unknown_id_raises():
    store = ExtractionStore()
    with pytest.raises(LookupError, match="not found"):
        store.save(user_id=VALUATION_TEST_USER_ID, extraction=_SAMPLE,
                   extraction_id=str(uuid.uuid4()))


@pytest.mark.db
def test_resave_scoped_to_owner():
    store = ExtractionStore()
    eid = store.save(user_id=VALUATION_TEST_USER_ID, extraction=_SAMPLE)
    # another user_id cannot overwrite the row (update path never inserts,
    # so no orphan row is created for the foreign id)
    with pytest.raises(LookupError, match="not found"):
        store.save(user_id=VALUATION_TEST_USER_ID + 1, extraction=_SAMPLE,
                   extraction_id=eid)


def test_resave_malformed_id_raises():
    store = ExtractionStore()
    with pytest.raises(ValueError, match="malformed extraction_id"):
        store.save(user_id=VALUATION_TEST_USER_ID, extraction=_SAMPLE,
                   extraction_id="not-a-uuid")


@pytest.mark.db
def test_get_returns_none_for_missing():
    store = ExtractionStore()
    assert store.get(str(uuid.uuid4())) is None


# ── pointer-stub (blob) mode ─────────────────────────────────────────────────

import json

from server.extraction_store import STORAGE_KEY_FIELD, is_pointer_stub


class _FakeBlobs:
    def __init__(self, configured=True):
        self._configured = configured
        self.objects = {}

    def configured(self):
        return self._configured

    def put_bytes(self, key, data, **kw):
        self.objects[key] = data

    def get_bytes(self, key):
        return self.objects[key]


def test_row_payload_wraps_and_pushes_in_blob_mode():
    blobs = _FakeBlobs()
    store = ExtractionStore(blobs)
    row = json.loads(store._to_row_payload("eid-1", _SAMPLE))
    assert row[STORAGE_KEY_FIELD] == "extractions/eid-1.json"
    assert json.loads(blobs.objects["extractions/eid-1.json"]) == _SAMPLE


def test_stub_passthrough_never_double_wraps():
    """dataroom_open copies a room's snapshot stub into a first-time holder's
    row — the stub must be stored as-is, pointing at the room's object."""
    blobs = _FakeBlobs()
    store = ExtractionStore(blobs)
    stub = {STORAGE_KEY_FIELD: "extractions/room-r1-e1.json"}
    assert is_pointer_stub(stub)
    assert json.loads(store._to_row_payload("eid-2", stub)) == stub
    assert blobs.objects == {}


def test_inline_when_blob_unconfigured():
    store = ExtractionStore(_FakeBlobs(configured=False))
    assert json.loads(store._to_row_payload("eid-3", _SAMPLE)) == _SAMPLE
    assert json.loads(ExtractionStore()._to_row_payload("eid-4", _SAMPLE)) == _SAMPLE


def test_get_payload_resolves_stub(monkeypatch):
    blobs = _FakeBlobs()
    blobs.objects["extractions/e9.json"] = json.dumps(_SAMPLE).encode()
    store = ExtractionStore(blobs)
    monkeypatch.setattr(store, "get", lambda eid: {
        "extraction_id": eid,
        "extraction": {STORAGE_KEY_FIELD: "extractions/e9.json"}})
    assert store.get_payload("e9") == _SAMPLE


def test_get_payload_passes_inline_rows_through(monkeypatch):
    store = ExtractionStore()
    monkeypatch.setattr(store, "get", lambda eid: {"extraction": _SAMPLE})
    assert store.get_payload("any") == _SAMPLE


@pytest.mark.db
def test_blob_mode_round_trip_against_supabase():
    """Full round trip through real Supabase Storage: save writes a pointer
    row + object, get() shows the stub, get_payload returns the original."""
    from server.blob_store import SupabaseBlobStore
    blobs = SupabaseBlobStore()
    if not blobs.configured():
        pytest.skip("SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY not set")
    store = ExtractionStore(blobs)
    eid = store.save(user_id=VALUATION_TEST_USER_ID, extraction=_SAMPLE,
                     label="blob round trip")
    try:
        rec = store.get(eid)
        assert rec["extraction"][STORAGE_KEY_FIELD] == f"extractions/{eid}.json"
        assert store.get_payload(eid) == _SAMPLE
    finally:
        # The session purge deletes the row; the object would outlive it.
        import httpx
        httpx.delete(f"{blobs._base}/storage/v1/object/{blobs.bucket}/extractions/{eid}.json",
                     headers=blobs._headers(), timeout=30.0)
