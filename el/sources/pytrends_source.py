"""Trend source: Google Trends India via PyTrends.

Provides daily trending searches + real-time trends with velocity scores.
Velocity = (recent 2-day avg - baseline 5-day avg) / baseline, using a
7-day hourly interest_over_time window.  No API key required.

pip install pytrends
"""
from __future__ import annotations

import time
from datetime import datetime, timezone

from el import config
from el.logger import get_logger
from el.sources import TrendCandidate

SOURCE_ID = "pytrends"
log = get_logger(__name__)

_DAILY_LIMIT = 50
_REALTIME_LIMIT = 30
_VELOCITY_BATCH = 5      # pytrends max keywords per payload call
_VELOCITY_TOP_N = 25     # only compute velocity for top N daily trends
_CALL_DELAY = 1.5        # seconds between calls to respect rate limit


def _make_client():
    from pytrends.request import TrendReq  # deferred import
    return TrendReq(hl="en-IN", tz=330, timeout=(10, 30), retries=2, backoff_factor=0.1)


def _velocity_batch(client, keywords: list[str]) -> dict[str, float | None]:
    """Return velocity score per keyword (batch of up to 5).

    Compares recent 2-day average vs opening 5-day baseline within a 7-day
    hourly window.  Positive = rising, negative = falling.
    """
    try:
        client.build_payload(keywords, timeframe="now 7-d", geo="IN")
        df = client.interest_over_time()
        if df is None or df.empty:
            return {kw: None for kw in keywords}
        result: dict[str, float | None] = {}
        for kw in keywords:
            if kw not in df.columns:
                result[kw] = None
                continue
            vals = df[kw].values.astype(float)
            if len(vals) < 10:
                result[kw] = None
                continue
            recent = float(vals[-2:].mean())
            baseline = float(vals[:5].mean())
            if baseline < 1:
                result[kw] = 0.5 if recent > 0 else None
            else:
                result[kw] = round((recent - baseline) / baseline, 3)
        return result
    except Exception as exc:
        log.debug("pytrends velocity batch failed: %s", exc)
        return {kw: None for kw in keywords}


def fetch_trends(ctx: dict) -> list[TrendCandidate]:
    try:
        from pytrends.request import TrendReq  # noqa: F401
    except ImportError:
        log.warning("pytrends not installed — run: pip install pytrends")
        return []

    candidates: list[TrendCandidate] = []
    now = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")

    try:
        client = _make_client()

        # ── Daily trending searches ──────────────────────────────────────
        daily_titles: list[str] = []
        try:
            df = client.trending_searches(pn="india")
            daily_titles = df[0].tolist()[:_DAILY_LIMIT]
        except Exception as exc:
            log.warning("pytrends daily trending failed: %s", exc)
        time.sleep(_CALL_DELAY)

        # ── Real-time trending searches ──────────────────────────────────
        realtime_titles: list[str] = []
        try:
            rt = client.realtime_trending_searches(pn="IN")
            for _, row in rt.iterrows():
                title = row.get("title") or row.get("entityNames") or ""
                if isinstance(title, list):
                    title = " ".join(str(t) for t in title)
                title = str(title).strip()
                if title:
                    realtime_titles.append(title)
            realtime_titles = realtime_titles[:_REALTIME_LIMIT]
        except Exception as exc:
            log.warning("pytrends realtime trending failed: %s", exc)
        time.sleep(_CALL_DELAY)

        # ── Velocity for top daily trends ────────────────────────────────
        velocity_map: dict[str, float | None] = {}
        top_for_vel = daily_titles[:_VELOCITY_TOP_N]
        for i in range(0, len(top_for_vel), _VELOCITY_BATCH):
            batch = top_for_vel[i : i + _VELOCITY_BATCH]
            velocity_map.update(_velocity_batch(client, batch))
            if i + _VELOCITY_BATCH < len(top_for_vel):
                time.sleep(_CALL_DELAY)

        # ── Assemble candidates ──────────────────────────────────────────
        seen: set[str] = set()
        for title in daily_titles:
            if title in seen:
                continue
            seen.add(title)
            candidates.append(TrendCandidate(
                title=title,
                source_id=SOURCE_ID,
                velocity=velocity_map.get(title),
                raw_payload={"pytrends_type": "daily"},
                fetched_at=now,
            ))

        for title in realtime_titles:
            if title in seen:
                continue
            seen.add(title)
            candidates.append(TrendCandidate(
                title=title,
                source_id=f"{SOURCE_ID}_realtime",
                velocity=0.5,  # realtime = actively spiking, assign moderate velocity
                raw_payload={"pytrends_type": "realtime"},
                fetched_at=now,
            ))

    except Exception:
        log.exception("pytrends source: unexpected error")

    log.info("pytrends: %d candidates (daily=%d, realtime=%d)",
             len(candidates), len(daily_titles), len(realtime_titles))
    return candidates
