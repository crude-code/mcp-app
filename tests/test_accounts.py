"""server/accounts.py — anonymous account minting for the CrudeDocs funnel."""

import json

import pytest

from server import accounts
from server.accounts import RateLimiter, handle_new_account, mint_account


class FakeDB:
    """Captures _query calls; scripted responses by SQL prefix."""

    def __init__(self, org_exists=True, slug_taken_first=False):
        self.calls = []
        self.org_exists = org_exists
        self.slug_checks = 0
        self.slug_taken_first = slug_taken_first

    def __call__(self, sql, params=None):
        self.calls.append((sql, params))
        s = sql.strip().upper()
        if s.startswith("SELECT ID FROM ORGANIZATIONS"):
            return [{"id": 7}] if self.org_exists else []
        if s.startswith("INSERT INTO ORGANIZATIONS"):
            return [{"id": 8}]
        if s.startswith("SELECT 1 FROM USERS"):
            self.slug_checks += 1
            if self.slug_taken_first and self.slug_checks == 1:
                return [{"?column?": 1}]
            return []
        if s.startswith("INSERT INTO USERS"):
            return []
        raise AssertionError(f"unexpected SQL: {sql}")


@pytest.fixture
def db(monkeypatch):
    fake = FakeDB()
    monkeypatch.setattr(accounts._platform, "_query", fake)
    return fake


def test_mint_returns_typed_state(db):
    out = mint_account()
    assert out["status"] == "created"
    assert out["shared"] is False
    assert out["expires_at"] is None
    assert out["mcp_url"].startswith("https://mcp.crudecode.dev/")
    assert out["mcp_url"].endswith("/mcp")
    slug = out["mcp_url"].split("/")[-2]
    assert len(slug) == 12 and int(slug, 16) >= 0  # 12-hex


def test_mint_inserts_anonymous_user_row(db):
    mint_account()
    insert = next(c for c in db.calls if c[0].strip().upper().startswith("INSERT INTO USERS"))
    sql, params = insert
    assert "email" in sql and "NULL" in sql  # email is never populated at mint
    org_id, user_key, name, slug, notes = params
    assert org_id == 7
    assert name == accounts.PLACEHOLDER_NAME
    meta = json.loads(notes)
    assert meta["source"] == "crudedoc"
    assert "minted_at" in meta


def test_mint_creates_org_when_missing(monkeypatch):
    fake = FakeDB(org_exists=False)
    monkeypatch.setattr(accounts._platform, "_query", fake)
    mint_account()
    assert any(c[0].strip().upper().startswith("INSERT INTO ORGANIZATIONS") for c in fake.calls)


def test_mint_retries_taken_slug(monkeypatch):
    fake = FakeDB(slug_taken_first=True)
    monkeypatch.setattr(accounts._platform, "_query", fake)
    out = mint_account()
    assert fake.slug_checks == 2
    assert out["status"] == "created"


def test_mcp_base_override(db, monkeypatch):
    monkeypatch.setenv("CC_PUBLIC_MCP_BASE", "https://mcp-dev.crudecode.dev/")
    out = mint_account()
    assert out["mcp_url"].startswith("https://mcp-dev.crudecode.dev/")


def test_rate_limiter_blocks_after_limit():
    t = [0.0]
    rl = RateLimiter(limit=3, window_s=60, now_fn=lambda: t[0])
    assert all(rl.allow("ip") for _ in range(3))
    assert not rl.allow("ip")
    assert rl.allow("other-ip")  # per-key isolation
    t[0] = 61.0
    assert rl.allow("ip")  # window expired


def test_handle_returns_unavailable_on_rate_limit(db):
    rl = RateLimiter(limit=0)
    assert handle_new_account("1.2.3.4", rl) == {"status": "unavailable"}
    assert not any(c[0].strip().upper().startswith("INSERT INTO USERS") for c in db.calls)


def test_handle_returns_unavailable_on_db_error(monkeypatch):
    def boom(sql, params=None):
        raise RuntimeError("db down")

    monkeypatch.setattr(accounts._platform, "_query", boom)
    out = handle_new_account("1.2.3.4", RateLimiter())
    assert out == {"status": "unavailable"}
