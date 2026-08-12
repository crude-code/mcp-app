"""UploadTokenStore semantics: mint/claim/consume, TTL, purpose scoping.
Single-use-on-success is the load-bearing property — a claim must never
consume (retries within TTL are legal), and a consumed token must never
claim again."""
import pytest

from server.upload_tokens import UploadTokenStore


@pytest.fixture
def store():
    return UploadTokenStore(ttl_seconds=60.0)


def _mint(store, **kw):
    defaults = dict(user_id=7, user_slug="acme", purpose="kit")
    defaults.update(kw)
    return store.mint(**defaults)


def test_mint_then_claim_returns_grant(store):
    token = _mint(store, meta={"label": "Room"})
    grant = store.claim(token, purpose="kit")
    assert grant.user_id == 7
    assert grant.user_slug == "acme"
    assert grant.meta == {"label": "Room"}


def test_claim_does_not_consume(store):
    token = _mint(store)
    assert store.claim(token, purpose="kit") is not None
    assert store.claim(token, purpose="kit") is not None


def test_consume_retires_token(store):
    token = _mint(store)
    store.consume(token)
    assert store.claim(token, purpose="kit") is None


def test_unknown_token_claims_none(store):
    assert store.claim("nope", purpose="kit") is None


def test_purpose_mismatch_claims_none(store):
    token = _mint(store, purpose="room")
    assert store.claim(token, purpose="kit") is None
    assert store.claim(token, purpose="room") is not None


def test_expired_token_claims_none(monkeypatch):
    store = UploadTokenStore(ttl_seconds=10.0)
    now = 1000.0
    monkeypatch.setattr("server.upload_tokens.time.monotonic", lambda: now)
    token = _mint(store)
    assert store.claim(token, purpose="kit") is not None
    monkeypatch.setattr("server.upload_tokens.time.monotonic", lambda: now + 11.0)
    assert store.claim(token, purpose="kit") is None


def test_tokens_are_unique(store):
    assert _mint(store) != _mint(store)
