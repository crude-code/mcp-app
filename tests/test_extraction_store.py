import uuid

import pytest

from server.extraction_store import ExtractionStore
from tests import VALUATION_TEST_USER_ID


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


@pytest.mark.db
def test_list_for_user_is_index_only():
    store = ExtractionStore()
    eid = store.save(user_id=VALUATION_TEST_USER_ID, extraction=_SAMPLE, label="idx")
    rows = store.list_for_user(VALUATION_TEST_USER_ID)
    mine = [r for r in rows if r["extraction_id"] == eid]
    assert mine and mine[0]["label"] == "idx"
    assert "extraction" not in mine[0]             # no payload blob in the index
