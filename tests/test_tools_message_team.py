import json

import pytest

import server.mcp_server as srv


_IDENTITY = {"user_slug": "acme", "user_id": 7, "user_name": "Ace",
             "user_email": "ace@acme.com", "org_name": "Acme"}


@pytest.fixture
def wired(monkeypatch):
    """Identity + store + SES all faked; returns the capture dict."""
    seen = {"saved": None, "emailed": [], "marked": [], "recent": 0}
    monkeypatch.setattr(srv, "get_current_identity", lambda: dict(_IDENTITY))
    monkeypatch.setattr(srv._team_messages, "count_recent",
                        lambda uid, minutes: seen["recent"])
    def fake_save(**kw):
        seen["saved"] = kw
        return "33333333-4444-5555-6666-777777777777"
    monkeypatch.setattr(srv._team_messages, "save", fake_save)
    monkeypatch.setattr(srv._team_messages, "mark_emailed",
                        lambda mid: seen["marked"].append(mid))
    monkeypatch.setattr(srv, "send_notification",
                        lambda subject, body: seen["emailed"].append((subject, body)))
    return seen


def test_rejects_none_identity(monkeypatch):
    monkeypatch.setattr(srv, "get_current_identity", lambda: None)
    out = json.loads(srv.message_team(subject="s", body="b"))
    assert out == {"error": "Could not identify user"}


def test_requires_subject_and_body(wired):
    assert "required" in json.loads(srv.message_team(subject=" ", body="b"))["error"]
    assert "required" in json.loads(srv.message_team(subject="s", body=""))["error"]


def test_rejects_unknown_category(wired):
    out = json.loads(srv.message_team(subject="s", body="b", category="rant"))
    assert "category must be one of" in out["error"]
    assert "data_request" in out["error"]


def test_rate_limit_blocks_before_insert(wired):
    wired["recent"] = 10
    out = json.loads(srv.message_team(subject="s", body="b"))
    assert "rate limit" in out["error"]
    assert wired["saved"] is None            # nothing inserted past the cap


def test_happy_path_tags_identity_and_context(wired):
    out = json.loads(srv.message_team(
        subject="Add Oklahoma wells", body="user wants OCC data",
        category="data_request", context={"run_id": "r-9"}))
    assert out["success"] is True
    assert out["email_sent"] is True
    assert out["message_id"] == "33333333-4444-5555-6666-777777777777"

    assert wired["saved"]["user_id"] == 7
    assert wired["saved"]["category"] == "data_request"
    assert wired["saved"]["context"] == {"run_id": "r-9"}

    (subject, body), = wired["emailed"]
    assert subject == "[data_request] [ace@acme.com] Add Oklahoma wells"
    assert "From: Ace <ace@acme.com>" in body
    assert "Org: Acme" in body
    assert '"run_id": "r-9"' in body
    assert body.endswith("user wants OCC data")
    assert wired["marked"] == [out["message_id"]]


def test_ses_failure_still_files_successfully(wired, monkeypatch):
    def boom(subject, body):
        raise RuntimeError("SES down")
    monkeypatch.setattr(srv, "send_notification", boom)
    out = json.loads(srv.message_team(subject="s", body="b", category="bug"))
    assert out["success"] is True
    assert out["email_sent"] is False        # deferred, not failed
    assert wired["saved"] is not None        # the row is the record
    assert wired["marked"] == []
