"""server/accounts.py — the retired mint lane.

The in-chat account mint was retired in the 2026-08 CrudeDocs
simplification: GET /new-account must always answer {"status":
"unavailable"} (old copied prompts' scripted fallback narrates the signup
form on that status) and must never touch the database.
"""

from server.accounts import handle_new_account


def test_handle_always_returns_unavailable():
    assert handle_new_account("1.2.3.4") == {"status": "unavailable"}
