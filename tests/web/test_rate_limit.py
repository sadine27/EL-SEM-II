"""SP4 — token-bucket rate limiter tests."""
from __future__ import annotations

from el.web.rate_limit import TokenBucket


class _ManualClock:
    def __init__(self, t: float = 0.0):
        self.t = t

    def __call__(self) -> float:
        return self.t

    def advance(self, dt: float) -> None:
        self.t += dt


def test_allows_up_to_capacity_then_blocks():
    clock = _ManualClock()
    tb = TokenBucket(capacity=3, refill_per_sec=1.0, clock=clock)

    for _ in range(3):
        allowed, retry = tb.try_consume("ip1")
        assert allowed is True
        assert retry == 0.0

    allowed, retry = tb.try_consume("ip1")
    assert allowed is False
    assert retry > 0.0


def test_refills_over_time():
    clock = _ManualClock()
    tb = TokenBucket(capacity=2, refill_per_sec=1.0, clock=clock)
    tb.try_consume("ip1")
    tb.try_consume("ip1")
    allowed, _ = tb.try_consume("ip1")
    assert allowed is False

    clock.advance(1.5)  # 1.5 tokens refill → at least 1 full token available
    allowed, retry = tb.try_consume("ip1")
    assert allowed is True
    assert retry == 0.0


def test_refill_caps_at_capacity():
    clock = _ManualClock()
    tb = TokenBucket(capacity=2, refill_per_sec=1.0, clock=clock)
    tb.try_consume("ip1")
    clock.advance(1000.0)  # huge sleep — should not exceed capacity

    for _ in range(2):
        allowed, _ = tb.try_consume("ip1")
        assert allowed is True
    allowed, _ = tb.try_consume("ip1")
    assert allowed is False


def test_keys_are_independent():
    clock = _ManualClock()
    tb = TokenBucket(capacity=1, refill_per_sec=1.0, clock=clock)
    assert tb.try_consume("a")[0] is True
    assert tb.try_consume("a")[0] is False
    assert tb.try_consume("b")[0] is True


def test_retry_after_is_time_until_one_token():
    clock = _ManualClock()
    tb = TokenBucket(capacity=1, refill_per_sec=2.0, clock=clock)  # 0.5s/token
    tb.try_consume("ip1")
    allowed, retry = tb.try_consume("ip1")
    assert allowed is False
    assert 0.4 <= retry <= 0.6


def test_per_minute_factory():
    """Convenience constructor used by app middleware."""
    clock = _ManualClock()
    tb = TokenBucket.per_minute(30, clock=clock)
    assert tb.capacity == 30
    assert abs(tb.refill_per_sec - 30 / 60.0) < 1e-9
