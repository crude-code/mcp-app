import pytest
from server.valuation.run_record import ValuationRunStore
from tests import VALUATION_TEST_USER_ID


@pytest.mark.db
def test_new_run_returns_uuid():
    store = ValuationRunStore()
    run_id = store.new_run(user_id=VALUATION_TEST_USER_ID, case_file={"interest_type": "wi"})
    assert len(run_id) == 36                       # uuid4 string


@pytest.mark.db
def test_write_then_read_stage():
    store = ValuationRunStore()
    run_id = store.new_run(user_id=VALUATION_TEST_USER_ID, case_file={"interest_type": "wi"})
    store.write_stage(run_id, stage="wells", payload={"asset_list": ["42-x-1"]})
    rec = store.read_stage(run_id, stage="wells")
    assert rec == {"asset_list": ["42-x-1"]}


@pytest.mark.db
def test_read_stage_returns_none_for_unset_stage():
    store = ValuationRunStore()
    run_id = store.new_run(user_id=VALUATION_TEST_USER_ID, case_file={"interest_type": "wi"})
    # Stage never written
    assert store.read_stage(run_id, stage="forecast") is None


@pytest.mark.db
def test_read_stage_returns_none_for_missing_run():
    store = ValuationRunStore()
    import uuid
    nonexistent = str(uuid.uuid4())
    assert store.read_stage(nonexistent, stage="wells") is None


def test_write_stage_rejects_unknown_stage():
    store = ValuationRunStore()
    with pytest.raises(ValueError, match="unknown stage"):
        store.write_stage("any-uuid", stage="bogus", payload={})


def test_read_stage_rejects_unknown_stage():
    store = ValuationRunStore()
    with pytest.raises(ValueError, match="unknown stage"):
        store.read_stage("any-uuid", stage="bogus")


@pytest.mark.db
def test_mark_complete_sets_status():
    store = ValuationRunStore()
    run_id = store.new_run(user_id=VALUATION_TEST_USER_ID, case_file={})
    assert store.get(run_id)["status"] == "pending"   # minted as pending
    store.mark_complete(run_id)
    assert store.get(run_id)["status"] == "complete"


@pytest.mark.db
def test_mark_error_sets_status_and_message():
    store = ValuationRunStore()
    run_id = store.new_run(user_id=VALUATION_TEST_USER_ID, case_file={})
    store.mark_error(run_id, error="something failed")
    rec = store.get(run_id)
    assert rec["status"] == "error"
    assert rec["error"] == "something failed"


@pytest.mark.db
def test_get_returns_full_record():
    store = ValuationRunStore()
    run_id = store.new_run(user_id=VALUATION_TEST_USER_ID, case_file={"foo": "bar"})
    rec = store.get(run_id)
    assert rec is not None
    assert rec["run_id"] == run_id
    assert rec["user_id"] == VALUATION_TEST_USER_ID
    assert rec["status"] == "pending"


@pytest.mark.db
def test_get_returns_none_for_missing_run():
    import uuid
    store = ValuationRunStore()
    assert store.get(str(uuid.uuid4())) is None


@pytest.mark.db
def test_update_case_file_clears_briefing_and_economics():
    store = ValuationRunStore()
    run_id = store.new_run(user_id=VALUATION_TEST_USER_ID, case_file={"interest_type": "wi"})
    store.write_stage(run_id, stage="forecast", payload={"f": 1})
    store.write_stage(run_id, stage="economics", payload={"e": 1})
    store.write_stage(run_id, stage="briefing_spec", payload={"old": "spec"})
    store.update_case_file(run_id, {"interest_type": "wi", "economics_overrides": {"oil_price": 80}})
    assert store.read_stage(run_id, stage="briefing_spec") is None   # never serve stale
    assert store.read_stage(run_id, stage="economics") is None       # must re-price
    assert store.read_stage(run_id, stage="forecast") == {"f": 1}    # forecast survives terms change
