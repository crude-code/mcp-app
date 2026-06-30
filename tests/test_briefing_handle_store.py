"""Tests for the per-token briefing handle store."""
import time

from utils.briefing_handle_store import BriefingHandleStore


def test_mint_and_fetch_round_trip():
    store = BriefingHandleStore(ttl_seconds=60.0)
    spec = {"kind": "briefing", "headline": "Test"}
    token = store.mint(user_slug="alice", spec=spec)
    assert isinstance(token, str) and len(token) >= 16
    fetched = store.fetch(user_slug="alice", token=token)
    assert fetched == spec


def test_fetch_wrong_user_returns_none():
    store = BriefingHandleStore(ttl_seconds=60.0)
    token = store.mint(user_slug="alice", spec={"x": 1})
    assert store.fetch(user_slug="bob", token=token) is None


def test_fetch_unknown_token_returns_none():
    store = BriefingHandleStore(ttl_seconds=60.0)
    assert store.fetch(user_slug="alice", token="nope") is None


def test_expired_token_returns_none():
    store = BriefingHandleStore(ttl_seconds=0.05)
    token = store.mint(user_slug="alice", spec={"x": 1})
    time.sleep(0.1)
    assert store.fetch(user_slug="alice", token=token) is None


def test_fetch_is_idempotent():
    """Renderer may re-mount; same token must fetch the same spec until TTL."""
    store = BriefingHandleStore(ttl_seconds=60.0)
    token = store.mint(user_slug="alice", spec={"x": 1})
    assert store.fetch(user_slug="alice", token=token) == {"x": 1}
    assert store.fetch(user_slug="alice", token=token) == {"x": 1}
