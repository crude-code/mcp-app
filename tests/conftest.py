"""Shared pytest fixtures for the Crude Code test suite."""

import os
import sys
from pathlib import Path

import pytest

# Load environment variables early so they're available during collection
from utils.env import load_env
load_env()

# Make the repo importable without installing the package
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests import VALUATION_TEST_USER_ID


@pytest.fixture(scope="session", autouse=True)
def _purge_valuation_test_rows():
    """Delete every platform.valuation_runs / platform.dataroom_extractions row
    minted by tests (sentinel user_id 9999). Runs at session teardown so the
    activity digest never sees phantom rows from a pytest run. yield-based so
    it fires even when tests fail."""
    yield
    try:
        from utils.platform import _query
        _query(
            "DELETE FROM platform.valuation_runs WHERE user_id = %s",
            params=[VALUATION_TEST_USER_ID],
        )
        _query(
            "DELETE FROM platform.dataroom_extractions WHERE user_id = %s",
            params=[VALUATION_TEST_USER_ID],
        )
        _query(
            "DELETE FROM platform.dataroom_rooms WHERE uploaded_by_user_id = %s",
            params=[VALUATION_TEST_USER_ID],
        )
        _query(
            "DELETE FROM platform.team_messages WHERE user_id = %s",
            params=[VALUATION_TEST_USER_ID],
        )
    except Exception:
        pass  # no Supabase env (CI without creds) — nothing was minted either


def pytest_collection_modifyitems(config, items):
    """Auto-skip `db` tests when there is no database to hit."""
    if os.environ.get("CC_DB_URL") or os.environ.get("EI_DB_URL"):
        return
    skip_db = pytest.mark.skip(reason="CC_DB_URL not set")
    for item in items:
        if "db" in item.keywords:
            item.add_marker(skip_db)


@pytest.fixture
def identity(monkeypatch):
    """A resolved caller for tool tests — the shape resolve_identity returns."""
    import server.mcp_server as srv
    monkeypatch.setattr(srv, "get_current_identity",
                        lambda: {"user_id": 7, "user_slug": "test-slug",
                                 "user_name": "Test User", "user_email": "test@example.com",
                                 "org_name": "Test Org"})


@pytest.fixture
def no_identity(monkeypatch):
    import server.mcp_server as srv
    monkeypatch.setattr(srv, "get_current_identity", lambda: None)
