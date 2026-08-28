"""server/accounts.py — the retired mint lane + the surviving RateLimiter.

The in-chat account mint was retired in the 2026-08 CrudeDocs
simplification: GET /new-account must always answer {"status":
"unavailable"} (old copied prompts' scripted fallback narrates the signup
form on that status) and must never touch the database.
"""

from server import accounts
from server.accounts import RateLimiter, handle_new_account


def test_handle_always_returns_unavailable():
    assert handle_new_account("1.2.3.4") == {"status": "unavailable"}


def test_handle_returns_a_fresh_dict_each_call():
    # Callers must not be able to mutate the module-level payload.
    out = handle_new_account("1.2.3.4")
    out["status"] = "created"
    assert handle_new_account("1.2.3.4") == {"status": "unavailable"}


def test_mint_lane_is_gone_and_module_touches_no_db():
    # The retirement contract: no mint entry point, no platform import —
    # there is no code path left that could insert a users row.
    assert not hasattr(accounts, "mint_account")
    assert not hasattr(accounts, "_platform")


def test_rate_limiter_blocks_after_limit():
    t = [0.0]
    rl = RateLimiter(limit=3, window_s=60, now_fn=lambda: t[0])
    assert all(rl.allow("ip") for _ in range(3))
    assert not rl.allow("ip")
    assert rl.allow("other-ip")  # per-key isolation
    t[0] = 61.0
    assert rl.allow("ip")  # window expired


def test_rate_limiter_default_window():
    # update_user constructs RateLimiter(limit=N) with no window — keep the
    # one-hour default that call site relies on.
    assert RateLimiter(limit=1).window_s == 3600
