"""server/accounts.py — the retired mint lane + the surviving RateLimiter.

The in-chat account mint was retired in the 2026-08 CrudeDocs
simplification: GET /new-account must always answer {"status":
"unavailable"} (old copied prompts' scripted fallback narrates the signup
form on that status) and must never touch the database.
"""

from server.accounts import RateLimiter, handle_new_account


def test_handle_always_returns_unavailable():
    assert handle_new_account("1.2.3.4") == {"status": "unavailable"}


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
