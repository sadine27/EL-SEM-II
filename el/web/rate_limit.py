"""SP4 — in-memory token-bucket rate limiter.

Per-key bucket. Lazy refill on each call (no background thread). Good enough
for single-process MVP; SP8 may swap in a Redis backend for multi-worker
deployments.
"""
from __future__ import annotations

import time
from dataclasses import dataclass


@dataclass
class _BucketState:
    tokens: float
    last_refill_ts: float


class TokenBucket:
    """Per-key token bucket. Not thread-safe (FastAPI default is single-event-loop)."""

    def __init__(self, *, capacity: int, refill_per_sec: float, clock=time.monotonic):
        if capacity <= 0:
            raise ValueError("capacity must be > 0")
        if refill_per_sec <= 0:
            raise ValueError("refill_per_sec must be > 0")
        self.capacity = capacity
        self.refill_per_sec = refill_per_sec
        self._clock = clock
        self._buckets: dict[str, _BucketState] = {}

    @classmethod
    def per_minute(cls, requests_per_minute: int, *, clock=time.monotonic) -> "TokenBucket":
        return cls(
            capacity=requests_per_minute,
            refill_per_sec=requests_per_minute / 60.0,
            clock=clock,
        )

    def try_consume(self, key: str, tokens: int = 1) -> tuple[bool, float]:
        now = self._clock()
        bucket = self._buckets.get(key)
        if bucket is None:
            bucket = _BucketState(tokens=float(self.capacity), last_refill_ts=now)
            self._buckets[key] = bucket
        else:
            elapsed = now - bucket.last_refill_ts
            bucket.tokens = min(
                float(self.capacity),
                bucket.tokens + elapsed * self.refill_per_sec,
            )
            bucket.last_refill_ts = now

        if bucket.tokens >= tokens:
            bucket.tokens -= tokens
            return True, 0.0

        deficit = tokens - bucket.tokens
        retry_after = deficit / self.refill_per_sec
        return False, retry_after
