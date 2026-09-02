import json

import pytest

from server.team_messages import CATEGORIES, TeamMessageStore
from tests import VALUATION_TEST_USER_ID
from utils.platform import _query


def _row(message_id):
    rec = _query("SELECT * FROM platform.team_messages WHERE message_id = %s", [message_id])[0]
    if isinstance(rec.get("context"), str):
        rec["context"] = json.loads(rec["context"])
    return rec


@pytest.mark.db
def test_save_and_get_round_trip():
    store = TeamMessageStore()
    mid = store.save(user_id=VALUATION_TEST_USER_ID, category="data_request",
                     subject="Add Oklahoma wells", body="OCC data please",
                     context={"run_id": "r-1"})
    assert len(mid) == 36
    rec = _row(mid)
    assert rec["user_id"] == VALUATION_TEST_USER_ID
    assert rec["category"] == "data_request"
    assert rec["subject"] == "Add Oklahoma wells"
    assert rec["context"] == {"run_id": "r-1"}
    assert rec["email_sent"] is False
    assert rec["status"] == "new"


@pytest.mark.db
def test_mark_emailed_flips_flag():
    store = TeamMessageStore()
    mid = store.save(user_id=VALUATION_TEST_USER_ID, category="bug",
                     subject="s", body="b")
    store.mark_emailed(mid)
    assert _row(mid)["email_sent"] is True


@pytest.mark.db
def test_count_recent_scopes_to_user_and_window():
    store = TeamMessageStore()
    before = store.count_recent(VALUATION_TEST_USER_ID, minutes=60)
    store.save(user_id=VALUATION_TEST_USER_ID, category="other",
               subject="s", body="b")
    assert store.count_recent(VALUATION_TEST_USER_ID, minutes=60) == before + 1
    # a zero-width window sees nothing; a foreign user sees nothing
    assert store.count_recent(VALUATION_TEST_USER_ID, minutes=0) == 0
    assert store.count_recent(-1) == 0


def test_categories_are_the_contract():
    assert CATEGORIES == {"bug", "feedback", "feature_request",
                          "data_request", "other"}
