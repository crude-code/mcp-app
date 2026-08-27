"""Pure core of the profile-claim lane: normalization + the update decision."""

from server.user_profile import (
    NAME_MAX, email_is_locked, normalize_email, normalize_name, plan_update,
    profile_state,
)


ANON = {"email": None, "name": "CrudeDoc visitor", "notes": {}}
CLAIMED = {"email": "ace@acme.com", "name": "Ace",
           "notes": {"email_source": "in_chat"}}
SIGNED_UP = {"email": "ace@acme.com", "name": "Ace", "notes": {}}


def test_normalizers():
    assert normalize_email("  Ace@Acme.COM ") == "ace@acme.com"
    assert normalize_name("  Ace   B  ") == "Ace B"


def test_lock_only_applies_to_signup_sourced_email():
    assert email_is_locked(ANON) is False            # nothing to protect
    assert email_is_locked(CLAIMED) is False         # attached in chat, fixable
    assert email_is_locked(SIGNED_UP) is True        # arrived with the account


def test_lock_tolerates_notes_as_json_string():
    row = {"email": "a@b.co", "name": "A", "notes": '{"email_source": "in_chat"}'}
    assert email_is_locked(row) is False


def test_empty_call_is_not_a_plan():
    assert "error" in plan_update(current=ANON, email="  ", name="")


def test_rejects_malformed_email():
    for bad in ["ace", "ace@acme", "a b@acme.com", "@acme.com"]:
        out = plan_update(current=ANON, email=bad)
        assert "not a valid email" in out["error"], bad


def test_attaches_to_anonymous_account():
    out = plan_update(current=ANON, email=" Ace@Acme.com ")
    assert out["email"] == "ace@acme.com"
    assert out["changed"] == ["email"]
    assert out["name"] is None                       # untouched


def test_same_email_is_a_no_op_not_an_error():
    out = plan_update(current=CLAIMED, email="ACE@acme.com")
    assert out["changed"] == []
    assert out["email"] is None


def test_in_chat_email_can_be_corrected():
    out = plan_update(current=CLAIMED, email="ace@acme.io")
    assert out["email"] == "ace@acme.io"
    assert out["changed"] == ["email"]


def test_signup_email_cannot_be_reassigned():
    out = plan_update(current=SIGNED_UP, email="attacker@evil.com")
    assert "can't be changed from chat" in out["error"]


def test_signup_row_still_accepts_a_name_change():
    out = plan_update(current=SIGNED_UP, name="Ace B")
    assert out["changed"] == ["name"]
    assert out["email"] is None


def test_name_length_cap():
    assert "longer than" in plan_update(current=ANON, name="x" * (NAME_MAX + 1))["error"]
    assert plan_update(current=ANON, name="x" * NAME_MAX)["changed"] == ["name"]


def test_both_fields_at_once():
    out = plan_update(current=ANON, email="ace@acme.com", name="Ace")
    assert out["changed"] == ["email", "name"]


def test_profile_state_reports_placeholder_and_verification():
    state = profile_state(ANON)
    assert state == {
        "success": True, "email": None, "name": "CrudeDoc visitor",
        "email_attached": False, "email_verified": False, "email_locked": False,
        "name_is_placeholder": True, "changed": [],
    }
    claimed = profile_state(CLAIMED, changed=["email"])
    assert claimed["email_attached"] is True
    assert claimed["name_is_placeholder"] is False
    # Never verified — there is no verification lane.
    assert claimed["email_verified"] is False
