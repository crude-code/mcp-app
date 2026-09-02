"""Tests for the per-token map handle store."""
from utils.map_handle_store import MapHandleStore


def test_mint_and_fetch_round_trip():
    store = MapHandleStore(ttl_seconds=60.0)
    spec = {"title": "Weld County", "layers": []}
    token = store.mint(user_slug="alice", spec=spec)
    assert isinstance(token, str) and len(token) >= 16
    assert store.fetch(user_slug="alice", token=token) == spec


def test_fetch_wrong_user_returns_none():
    store = MapHandleStore(ttl_seconds=60.0)
    token = store.mint(user_slug="alice", spec={"x": 1})
    assert store.fetch(user_slug="bob", token=token) is None


def test_fetch_unknown_token_returns_none():
    store = MapHandleStore(ttl_seconds=60.0)
    assert store.fetch(user_slug="alice", token="nope") is None


def test_expired_token_returns_none(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr("utils.map_handle_store.time.monotonic", lambda: now[0])
    store = MapHandleStore(ttl_seconds=60.0)
    token = store.mint(user_slug="alice", spec={"x": 1})
    now[0] += 61.0
    assert store.fetch(user_slug="alice", token=token) is None


def test_fetch_is_idempotent():
    """Renderer may re-mount; same token must fetch the same spec until TTL."""
    store = MapHandleStore(ttl_seconds=60.0)
    token = store.mint(user_slug="alice", spec={"x": 1})
    assert store.fetch(user_slug="alice", token=token) == {"x": 1}
    assert store.fetch(user_slug="alice", token=token) == {"x": 1}
