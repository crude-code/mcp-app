"""The update_user tool: identity, the read path, uniqueness, notification."""

import json

import pytest

import server.mcp_server as srv
from utils.rate_limit import RateLimiter


_IDENTITY = {"user_slug": "anon1", "user_id": 7, "user_name": "CrudeDoc visitor",
             "user_email": None, "org_name": "CrudeDoc Signups"}


@pytest.fixture
def wired(monkeypatch):
    """Identity, store and SES faked; fresh limiter so tests don't leak."""
    seen = {"row": {"id": 7, "email": None, "name": "CrudeDoc visitor",
                    "notes": {}},
            "applied": None, "emailed": [], "owner": None}
    monkeypatch.setattr(srv, "get_current_identity", lambda: dict(_IDENTITY))
    monkeypatch.setattr(srv, "_update_user_limiter", RateLimiter(limit=20))
    monkeypatch.setattr(srv._user_profiles, "read", lambda uid: seen["row"])
    monkeypatch.setattr(srv._user_profiles, "email_owner",
                        lambda email: seen["owner"])

    def fake_apply(**kw):
        seen["applied"] = kw
    monkeypatch.setattr(srv._user_profiles, "apply", fake_apply)
    monkeypatch.setattr(srv, "send_notification",
                        lambda subject, body: seen["emailed"].append(subject))
    return seen


def test_rejects_none_identity(monkeypatch):
    monkeypatch.setattr(srv, "get_current_identity", lambda: None)
    out = json.loads(srv.update_user(email="a@b.co"))
    assert out == {"error": "Could not identify user"}


def test_no_args_reads_without_writing(wired):
    out = json.loads(srv.update_user())
    assert out["email_attached"] is False
    assert out["name_is_placeholder"] is True
    assert out["changed"] == []
    assert wired["applied"] is None              # a read never writes


def test_attach_writes_and_reports_change(wired):
    out = json.loads(srv.update_user(email=" Ace@Acme.com "))
    assert out["changed"] == ["email"]
    assert out["email"] == "ace@acme.com"
    assert out["email_attached"] is True
    assert out["email_verified"] is False        # nothing was verified
    assert wired["applied"] == {"user_id": 7, "email": "ace@acme.com",
                                "name": None}


def test_claiming_an_anonymous_account_notifies_the_team(wired):
    srv.update_user(email="ace@acme.com")
    assert len(wired["emailed"]) == 1
    assert "claimed" in wired["emailed"][0]


def test_correcting_an_attached_email_does_not_re_notify(wired):
    wired["row"] = {"id": 7, "email": "typo@acme.com", "name": "Ace",
                    "notes": {"email_source": "in_chat"}}
    out = json.loads(srv.update_user(email="ace@acme.com"))
    assert out["changed"] == ["email"]
    assert wired["emailed"] == []                # only a first claim notifies


def test_email_on_another_account_is_refused_before_writing(wired):
    wired["owner"] = 99
    out = json.loads(srv.update_user(email="ace@acme.com"))
    assert "already on another CrudeCode account" in out["error"]
    assert wired["applied"] is None


def test_reclaiming_own_address_is_not_a_collision(wired):
    wired["row"] = {"id": 7, "email": None, "name": "Ace", "notes": {}}
    wired["owner"] = 7                            # the row is its own owner
    out = json.loads(srv.update_user(email="ace@acme.com"))
    assert out["changed"] == ["email"]


def test_signup_email_is_locked(wired):
    wired["row"] = {"id": 7, "email": "real@corp.com", "name": "Ace",
                    "notes": {}}
    out = json.loads(srv.update_user(email="attacker@evil.com"))
    assert "message_team" in out["error"]
    assert wired["applied"] is None


def test_no_op_update_succeeds_without_writing(wired):
    wired["row"] = {"id": 7, "email": "ace@acme.com", "name": "Ace",
                    "notes": {"email_source": "in_chat"}}
    out = json.loads(srv.update_user(email="ace@acme.com", name="Ace"))
    assert out["success"] is True
    assert out["changed"] == []
    assert wired["applied"] is None


def test_write_is_rate_limited_but_read_is_not(wired, monkeypatch):
    monkeypatch.setattr(srv, "_update_user_limiter", RateLimiter(limit=2))
    assert "changed" in json.loads(srv.update_user(name="A"))
    assert "changed" in json.loads(srv.update_user(name="B"))
    assert "rate limit" in json.loads(srv.update_user(name="C"))["error"]
    assert json.loads(srv.update_user())["success"] is True


def test_mail_failure_never_fails_the_claim(wired, monkeypatch):
    def boom(subject, body):
        raise RuntimeError("SES down")
    monkeypatch.setattr(srv, "send_notification", boom)
    out = json.loads(srv.update_user(email="ace@acme.com"))
    assert out["changed"] == ["email"]           # the row is what matters


def test_notes_returned_as_a_json_string_still_attach(wired):
    """Some drivers hand jsonb back as text; the merge after a successful
    write must not be the thing that fails the call."""
    wired["row"] = {"id": 7, "email": None, "name": "Ace", "notes": '{"seen": 1}'}
    out = json.loads(srv.update_user(email="ace@acme.com"))
    assert out["changed"] == ["email"]
    assert out["email_locked"] is False           # in_chat source recorded
