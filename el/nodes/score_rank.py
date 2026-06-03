"""Fenix Engine — Fetch · Score · Dedupe · Rank (v2).

Reads all pluggable source candidates from ctx["source_candidates"] plus
inline Google News RSS, then:

  1. Scores product-purchase intent via keyword tiers
  2. Applies velocity boost from sources that measure it
  3. Boosts topics confirmed across multiple independent sources
  4. Maps categories using anchor-priority scoring + hard exclusion zones
     (fixes the "clothes for earbuds" bug from naive regex matching)
  5. Dedupes near-duplicates, keeping the higher-scored entry
  6. Sorts by composite score and emits ctx["ranked_payload"]

Downstream Phase 2 nodes consume ctx["ranked_payload"]["trends"].
"""
from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime, timezone

import requests

from el.logger import get_logger
from el.nodes._score_config import (
    CATEGORIES,
    TOPIC_EXCLUSIONS,
    STOPWORDS,
    T1_BUYER,
    T2_RESEARCH,
    T3_AMBIENT,
    NEG,
    normalize_words,
    normalize_topic,
)
from el.sources import TrendCandidate

log = get_logger(__name__)

NEWS_RSS_URL = "https://news.google.com/rss?hl=en-IN&gl=IN&ceid=IN:en"
RSS_TIMEOUT = 30
MAX_RAW_ITEMS = 2000
MAX_NEWS_ITEMS = 100
DEDUPE_OVERLAP_THRESHOLD = 0.70

_RSS_TITLE_RE = re.compile(
    r"<title>(?:<!\[CDATA\[)?([^<\]]+?)(?:\]\]>)?</title>",
    re.IGNORECASE,
)


# ── RSS helpers ───────────────────────────────────────────────────────────────

def parse_youtube(items: list[dict]) -> list[dict]:
    out: list[dict] = []
    for v in items:
        if not isinstance(v, dict):
            continue
        sn = v.get("snippet") or {}
        if not isinstance(sn, dict):
            continue
        title = (sn.get("title") or "").strip()
        if title:
            tags = sn.get("tags") if isinstance(sn.get("tags"), list) else []
            out.append({"topic": title, "source": "youtube_trending",
                        "tags": tags, "velocity": None, "search_volume": None})
    return out


def parse_rss_titles(xml: str, source: str, *, skip_first: int = 1,
                     limit: int | None = None) -> list[dict]:
    matches = _RSS_TITLE_RE.findall(xml or "")
    sliced = matches[skip_first:]
    if limit is not None:
        sliced = sliced[:limit]
    return [
        {"topic": raw.strip(), "source": source, "tags": [],
         "velocity": None, "search_volume": None}
        for raw in sliced if raw.strip()
    ]


# fetch_trends_rss removed 2026-06-03: Google killed the daily Trends RSS endpoint
# (always 404s). Real trend signal comes from pluggable sources + ai_trend_discovery.


def fetch_news_rss() -> list[dict]:
    try:
        r = requests.get(NEWS_RSS_URL, timeout=RSS_TIMEOUT)
        r.raise_for_status()
        return parse_rss_titles(r.text, "google_news_rss", limit=MAX_NEWS_ITEMS)
    except Exception as e:
        log.warning("News RSS failed: %s", e)
        return []


# ── Scoring ───────────────────────────────────────────────────────────────────

def score_intent(topic: str, related: list[str],
                 velocity: float | None = None) -> float:
    """Compute [0, 1] product-purchase intent score with optional velocity boost."""
    haystack = " ".join([topic, *related]).lower()
    s = 0.0
    for p in T1_BUYER:
        if p in haystack:
            s += 0.30
    for p in T2_RESEARCH:
        if p in haystack:
            s += 0.15
    for p in T3_AMBIENT:
        if p in haystack:
            s += 0.10
    for p in NEG:
        if p in haystack:
            s -= 0.20
    base = max(0.0, min(1.0, s))

    if velocity is not None:
        # Rising trends earn up to +0.35; falling down to -0.15
        boost = min(0.35, max(-0.15, velocity * 0.25))
        base = max(0.0, min(1.0, base + boost))

    return round(base, 3)


def map_categories(topic: str, related: list[str]) -> list[str]:
    """Anchor-priority category scoring with hard exclusion zones.

    Each category accumulates a score from:
      - Anchor matches: +4 + 1.5 × anchor_word_count  (high specificity)
      - Keyword matches: +1 per keyword hit

    Topics are removed from consideration if a TOPIC_EXCLUSIONS trigger is
    found in the haystack — this is what prevents "earbuds" → "fashion".

    Returns up to 2 categories when scores are close (second >= 60% of first).
    """
    haystack = " ".join([topic, *related]).lower()

    # Build set of hard-excluded categories for this topic
    excluded: set[str] = set()
    for trigger, excl_cats in TOPIC_EXCLUSIONS.items():
        if trigger in haystack:
            excluded |= excl_cats

    scores: dict[str, float] = defaultdict(float)

    for cat_name, conf in CATEGORIES.items():
        if cat_name in excluded:
            continue
        for anchor in conf["anchors"]:
            if anchor in haystack:
                scores[cat_name] += 4.0 + len(anchor.split()) * 1.5
        for kw in conf["keywords"]:
            if re.search(rf"\b{re.escape(kw)}\b", haystack):
                scores[cat_name] += 1.0

    if not scores:
        return ["uncategorized"]

    ranked = sorted(scores.items(), key=lambda x: (-x[1], -CATEGORIES[x[0]]["priority"]))
    top_cat, top_score = ranked[0]
    result = [top_cat]

    if len(ranked) >= 2:
        second_cat, second_score = ranked[1]
        if top_score > 0 and second_score >= top_score * 0.60:
            result.append(second_cat)

    return result


# ── Deduplication ─────────────────────────────────────────────────────────────

def dedupe(items: list[dict]) -> list[dict]:
    """Remove near-duplicates by word-overlap. Keeps the higher-scoring entry."""
    kept: list[dict] = []
    for cand in items:
        cw = normalize_words(cand["topic"])
        if not cw:
            continue
        dup_idx = -1
        for i, existing in enumerate(kept):
            ew = normalize_words(existing["topic"])
            smaller = min(len(cw), len(ew))
            if not smaller:
                continue
            if len(cw & ew) / smaller > DEDUPE_OVERLAP_THRESHOLD:
                dup_idx = i
                break
        if dup_idx == -1:
            kept.append(cand)
        else:
            existing = kept[dup_idx]
            # Final tiebreaker: when intent/cross-source/velocity are equal, keep the
            # entry carrying richer related-query metadata (better downstream signal).
            cand_score = (
                cand.get("product_intent_score", 0),
                cand.get("cross_source_count", 1),
                cand.get("velocity") or 0.0,
                len(cand.get("related_queries") or []),
            )
            exist_score = (
                existing.get("product_intent_score", 0),
                existing.get("cross_source_count", 1),
                existing.get("velocity") or 0.0,
                len(existing.get("related_queries") or []),
            )
            if cand_score > exist_score:
                kept[dup_idx] = cand
    return kept


# ── Main run ──────────────────────────────────────────────────────────────────

def run(ctx: dict) -> dict:
    # ── 1. Collect all items from every source ───────────────────────────
    yt_items = parse_youtube(ctx.get("youtube_items") or [])

    # Google Trends daily RSS is dead (always 404s) — removed.
    # Google News RSS is still live but duplicates the google_news_india source.
    # Only fetch it as a fallback when no pluggable sources returned candidates,
    # so we don't make a redundant HTTP call on every pipeline run.
    source_candidates: list[TrendCandidate] = ctx.get("source_candidates") or []
    pluggable_items: list[dict] = []
    for tc in source_candidates:
        if tc.source_id in ("youtube",):
            continue  # already in yt_items
        pluggable_items.append({
            "topic": tc.title,
            "source": tc.source_id,
            "tags": tc.raw_payload.get("tags") or [],
            "velocity": tc.velocity,
            "search_volume": tc.search_volume,
        })

    news_items: list[dict] = []
    if not pluggable_items and not yt_items:
        news_items = fetch_news_rss()

    all_raw = (yt_items + news_items + pluggable_items)[:MAX_RAW_ITEMS]

    # ── 2. Cross-source counting ─────────────────────────────────────────
    topic_sources: dict[str, set[str]] = defaultdict(set)
    for item in all_raw:
        norm = normalize_topic(item["topic"])
        topic_sources[norm].add(item["source"])

    # ── 3. Score every item ──────────────────────────────────────────────
    enriched: list[dict] = []
    for item in all_raw:
        related = list(item.get("tags") or [])[:10]
        velocity = item.get("velocity")
        norm = normalize_topic(item["topic"])
        cross_count = len(topic_sources.get(norm, {item["source"]}))

        # Cross-source boost: each additional independent source +0.08 (cap 0.30)
        cross_boost = min(0.30, (cross_count - 1) * 0.08)

        base_score = score_intent(item["topic"], related, velocity=velocity)
        final_score = round(min(1.0, base_score + cross_boost), 3)

        enriched.append({
            "topic": item["topic"],
            "traffic_estimate": item.get("search_volume") or "N/A",
            "source": item["source"],
            "related_queries": related,
            "product_intent_score": final_score,
            "suggested_categories": map_categories(item["topic"], related),
            "velocity": velocity,
            "cross_source_count": cross_count,
        })

    deduped = dedupe(enriched)

    # Sort: intent score -> velocity -> cross-source count
    deduped.sort(key=lambda t: (
        -t["product_intent_score"],
        -(t.get("velocity") or 0.0),
        -t.get("cross_source_count", 1),
    ))
    ranked = [{"rank": i + 1, **t} for i, t in enumerate(deduped)]

    # ── 4. Build and emit payload ────────────────────────────────────────
    all_source_ids = list({
        "youtube_trending", "google_news_rss",
        *{tc.source_id for tc in source_candidates},
    })

    payload = {
        "metadata": {
            "scraped_at": (
                datetime.now(timezone.utc)
                .isoformat(timespec="milliseconds")
                .replace("+00:00", "Z")
            ),
            "geo": "IN",
            "total_topics": len(ranked),
            "sources": all_source_ids,
            "source_counts": {
                "youtube": len(yt_items),
                "google_news_rss": len(news_items),
                "pluggable": len(pluggable_items),
            },
        },
        "trends": ranked,
    }

    log.info(
        "Fenix Rank: %d topics | YT:%d News:%d Pluggable:%d",
        len(ranked), len(yt_items),
        len(news_items), len(pluggable_items),
    )
    ctx["ranked_payload"] = payload
    return ctx
