"""Shared pytest fixtures for the EI Plugins test suite."""

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


@pytest.fixture
def fake_identity() -> dict:
    """Identity payload matching what resolve_identity returns."""
    return {
        "user_id": 9999,
        "user_slug": "test-user",
        "user_name": "Test User",
        "user_email": "test@example.com",
        "user_username": "tester",
        "user_notes": None,
        "user_last_login": None,
        "org_name": "Test Org",
    }


def pytest_addoption(parser):
    parser.addoption("--run-network", action="store_true",
                     help="Run tests marked @pytest.mark.network (hit live APIs)")


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
            "DELETE FROM platform.team_messages WHERE user_id = %s",
            params=[VALUATION_TEST_USER_ID],
        )
    except Exception:
        pass  # no Supabase env (CI without creds) — nothing was minted either


def pytest_collection_modifyitems(config, items):
    """Auto-skip db/anthropic/network tests if prerequisites are missing."""
    skip_db = pytest.mark.skip(reason="EI_DB_URL not set")
    skip_anthropic = pytest.mark.skip(reason="ANTHROPIC_API_KEY not set")
    skip_network = pytest.mark.skip(reason="needs --run-network")
    has_db = bool(os.environ.get("EI_DB_URL"))
    has_anthropic = bool(os.environ.get("ANTHROPIC_API_KEY"))
    run_network = config.getoption("--run-network")
    for item in items:
        if "db" in item.keywords and not has_db:
            item.add_marker(skip_db)
        if "anthropic" in item.keywords and not has_anthropic:
            item.add_marker(skip_anthropic)
        if "network" in item.keywords and not run_network:
            item.add_marker(skip_network)
