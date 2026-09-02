from utils.rate_limit import RateLimiter


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
