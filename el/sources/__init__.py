"""Trend-source protocol + shared types.

Every concrete source lives at `el/sources/<source>.py` with a top-level
`SOURCE_ID` constant and a `fetch_trends(ctx)` function returning a list
of `TrendCandidate`. See docs/superpowers/specs/2026-05-21-sp2-source-expansion-design.md.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class TrendCandidate:
    title: str
    source_id: str
    raw_payload: dict = field(default_factory=dict)
    score_hint: float | None = None
    region: str = "IN"
    fetched_at: str | None = None
    # Fenix engine additions
    velocity: float | None = None       # growth rate vs baseline: 1.0 = +100%
    search_volume: int | None = None    # 0-100 (pytrends scale) or absolute
    cross_source_count: int = 1         # filled in by score_rank after aggregation


@runtime_checkable
class Source(Protocol):
    SOURCE_ID: str
    def fetch_trends(self, ctx: dict) -> list[TrendCandidate]: ...
