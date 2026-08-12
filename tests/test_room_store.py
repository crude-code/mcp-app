"""RoomStore against the live platform.dataroom_rooms table: pending rows
are invisible to hash lookup, completion makes them global, and the
initial-extraction snapshot is write-once."""
import hashlib
import uuid

import pytest

from server.room_store import RoomStore
from tests import VALUATION_TEST_USER_ID


def _fresh_sha() -> str:
    return hashlib.sha256(uuid.uuid4().bytes).hexdigest()


@pytest.mark.db
def test_pending_room_is_not_findable_by_hash():
    store = RoomStore()
    sha = _fresh_sha()
    room_id = store.create_pending(user_id=VALUATION_TEST_USER_ID,
                                   label="Test Room", sha256=sha, size_bytes=123)
    assert len(room_id) == 36
    assert store.find_by_hash(sha) is None


@pytest.mark.db
def test_complete_room_found_by_hash_with_flags():
    store = RoomStore()
    sha = _fresh_sha()
    room_id = store.create_pending(user_id=VALUATION_TEST_USER_ID,
                                   label="Test Room", sha256=sha, size_bytes=123)
    assert store.mark_complete(room_id, storage_key=f"rooms/{sha}.zip") == room_id
    rec = store.find_by_hash(sha)
    assert rec["room_id"] == room_id
    assert rec["storage_key"] == f"rooms/{sha}.zip"
    assert rec["has_initial_extraction"] is False


@pytest.mark.db
def test_initial_extraction_snapshot_is_write_once():
    store = RoomStore()
    sha = _fresh_sha()
    room_id = store.create_pending(user_id=VALUATION_TEST_USER_ID,
                                   label="Test Room", sha256=sha, size_bytes=123)
    store.mark_complete(room_id, storage_key=f"rooms/{sha}.zip")

    first = {"deal": {"name": "v1"}, "wells": []}
    assert store.save_initial_extraction(room_id, first) is True
    # second writer bounces and changes nothing
    assert store.save_initial_extraction(room_id, {"deal": {"name": "v2"}}) is False
    assert store.get_initial_extraction(room_id) == first
    assert store.find_by_hash(sha)["has_initial_extraction"] is True
