"""Port of n8n node `Fetch . Score . Dedupe . Rank`.

Reads ctx["youtube_items"] (set by `youtube_trending`), additionally fetches
Google Trends Daily RSS (geo=IN) and Google News RSS (en-IN), then scores
product-purchase intent, maps each topic to one or more product categories,
dedupes near-duplicates by word overlap, sorts by score, and emits the
ranked payload at ctx["ranked_payload"].

Downstream Phase 2 nodes consume `ctx["ranked_payload"]["trends"]`.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

import requests

from el.logger import get_logger

log = get_logger(__name__)

TRENDS_RSS_URL = "https://trends.google.com/trends/trendingsearches/daily/rss?geo=IN"
NEWS_RSS_URL = "https://news.google.com/rss?hl=en-IN&gl=IN&ceid=IN:en"
RSS_TIMEOUT = 30
MAX_RAW_ITEMS = 1000
MAX_NEWS_ITEMS = 100
DEDUPE_OVERLAP_THRESHOLD = 0.70

T1_BUYER = (
    "buy", "price", "cheap", "best", "review", "order", "shop", "deal",
    "discount", "sale", "offer", "coupon", "promo code", "clearance",
    "cash on delivery", "cod", "free shipping", "emi", "in stock",
    "where to buy", "lowest price", "cheap price", "wholesale", "bulk",
    "dropship", "distributor", "under 500", "under 1000",
)
T2_RESEARCH = (
    "alternative to", "similar to", "replacement for", "specs",
    "specifications", "features", "dimensions", "unboxing", "hands on",
    "teardown", "pros and cons", "is it worth it", "buying guide",
    "top 10", "top 5", "tier list", "ranking", "benchmarks", "reddit",
    "quora", "combo", "kit", "pack", "vs", "comparison",
)
T3_AMBIENT = (
    "wireless", "portable", "new", "latest", "trending", "india 2026",
    "original", "authentic", "genuine", "fake vs real", "refurbished",
    "second hand", "used", "open box", "warranty", "return policy",
    "customer service", "size chart", "colors", "variants", "edition",
    "flash sale", "limited time", "lightning deal", "restock", "sold out",
    "in stock tracker", "pre-order", "launch date", "release date",
    "early access", "near me",
)
NEG = (
    "how to", "tutorial", "diy", "repair", "fix", "not working", "error",
    "broken", "manual", "pdf", "driver download", "free download",
)

CAT: dict[str, tuple[str, ...]] = {
    "electronics": ("wireless", "bluetooth", "earbuds", "phone", "laptop", "usb",
                    "charger", "led", "power bank", "smartwatch", "speaker",
                    "monitor", "cable", "adapter", "tablet", "camera"),
    "fashion": ("shirt", "dress", "kurta", "saree", "sneakers", "watch", "bag",
                "sunglasses", "jeans", "t-shirt", "jacket", "shoes", "hoodie",
                "heels", "wallet", "belt"),
    "home": ("kitchen", "decor", "organizer", "cleaning", "storage", "fan",
             "cooler", "light", "bottle", "bedsheet", "pillow", "cookware",
             "blender", "mop", "towel", "vacuum"),
    "fitness": ("gym", "yoga", "protein", "supplement", "band", "tracker",
                "cycle", "dumbbells", "mat", "creatine", "whey", "treadmill",
                "resistance", "shaker", "massager"),
    "beauty": ("skincare", "hair", "serum", "moisturizer", "lipstick",
               "foundation", "sunscreen", "shampoo", "perfume", "lotion",
               "concealer", "trimmer", "face wash", "makeup", "cleanser"),
    "accessories": ("case", "cover", "stand", "holder", "mount", "strap",
                    "tempered glass", "sleeve", "skin", "guard", "ring",
                    "tripod", "grip", "hub"),
    "automotive": ("car", "bike", "helmet", "dashcam", "tyre", "wax", "polish",
                   "wiper", "gps", "inflator", "mat", "coolant", "scratch",
                   "jump starter", "perfume"),
    "baby_and_kids": ("toy", "puzzle", "lego", "diaper", "stroller", "wipes",
                      "pacifier", "onesie", "rattle", "plush", "scooter",
                      "doll", "action figure", "bottle"),
    "pets": ("dog", "cat", "food", "collar", "leash", "bed", "litter", "treats",
             "aquarium", "grooming", "cage", "harness", "shampoo", "bowl"),
    "office_and_stationery": ("book", "notebook", "pen", "desk", "chair",
                              "printer", "paper", "marker", "folder", "diary",
                              "planner", "stapler", "calculator", "ink"),
    "health_and_medical": ("thermometer", "massager", "vitamins", "mask",
                           "sanitizer", "first aid", "scale", "oximeter",
                           "braces", "monitor", "inhaler", "test kit", "support"),
    "tools_and_hardware": ("drill", "screwdriver", "wrench", "saw", "tape",
                           "hammer", "screws", "pliers", "multimeter", "ladder",
                           "glue", "toolkit", "nails", "hinge"),
    "grocery_and_food": ("coffee", "tea", "snacks", "chocolate", "dry fruits",
                         "oil", "rice", "spices", "honey", "noodles", "sauce",
                         "cereal", "pasta", "biscuit"),
}

STOPWORDS = frozenset({
    "a", "an", "the", "in", "of", "for", "with", "is", "are", "was", "were",
    "and", "or", "on", "at", "to", "by", "from",
})

_RSS_TITLE_RE = re.compile(
    r"<title>(?:<!\[CDATA\[)?([^<\]]+?)(?:\]\]>)?</title>",
    re.IGNORECASE,
)
_WORD_SPLIT_RE = re.compile(r"\W+")


def parse_youtube(items: list[dict]) -> list[dict]:
    """Map YouTube `videos.list` items to the internal {topic, source, tags} shape."""
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
                        "tags": tags})
    return out


def parse_rss_titles(xml: str, source: str, *, skip_first: int = 1,
                     limit: int | None = None) -> list[dict]:
    """Extract <title> entries from an RSS feed.

    Skips the first N matches (typically the channel title) and keeps the
    next `limit` (or all). Mirrors the original n8n regex behavior exactly.
    """
    matches = _RSS_TITLE_RE.findall(xml or "")
    sliced = matches[skip_first:]
    if limit is not None:
        sliced = sliced[:limit]
    out: list[dict] = []
    for raw in sliced:
        title = raw.strip()
        if title:
            out.append({"topic": title, "source": source, "tags": []})
    return out


def fetch_trends() -> list[dict]:
    try:
        r = requests.get(TRENDS_RSS_URL, timeout=RSS_TIMEOUT)
        r.raise_for_status()
        return parse_rss_titles(r.text, "google_trends_daily")
    except Exception as e:  # pragma: no cover - exercised via mocks
        log.warning("Trends RSS failed: %s", e)
        return []


def fetch_news() -> list[dict]:
    try:
        r = requests.get(NEWS_RSS_URL, timeout=RSS_TIMEOUT)
        r.raise_for_status()
        return parse_rss_titles(r.text, "google_news_rss", limit=MAX_NEWS_ITEMS)
    except Exception as e:  # pragma: no cover - exercised via mocks
        log.warning("News RSS failed: %s", e)
        return []


def score_intent(topic: str, related: list[str]) -> float:
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
    return round(max(0.0, min(1.0, s)), 3)


def map_categories(topic: str, related: list[str]) -> list[str]:
    haystack = " ".join([topic, *related]).lower()
    found: list[str] = []
    for cat, kws in CAT.items():
        for kw in kws:
            if re.search(rf"\b{re.escape(kw)}\b", haystack):
                found.append(cat)
                break
    return found or ["uncategorized"]


def normalize_words(text: str) -> set[str]:
    return {w for w in _WORD_SPLIT_RE.split(text.lower())
            if w and w not in STOPWORDS}


def dedupe(items: list[dict]) -> list[dict]:
    """Remove near-duplicates by word-overlap ratio against the smaller set.

    Threshold is strictly > 0.70. When a duplicate is detected, the kept
    entry is replaced iff the candidate has more `related_queries`.
    """
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
            overlap = len(cw & ew)
            if overlap / smaller > DEDUPE_OVERLAP_THRESHOLD:
                dup_idx = i
                break
        if dup_idx == -1:
            kept.append(cand)
        elif len(cand.get("related_queries") or []) > len(
            kept[dup_idx].get("related_queries") or []
        ):
            kept[dup_idx] = cand
    return kept


def run(ctx: dict) -> dict:
    yt_items = parse_youtube(ctx.get("youtube_items") or [])
    trends_items = fetch_trends()
    news_items = fetch_news()

    raw = (yt_items + trends_items + news_items)[:MAX_RAW_ITEMS]
    enriched = []
    for item in raw:
        related = list(item.get("tags") or [])[:10]
        enriched.append({
            "topic": item["topic"],
            "traffic_estimate": "N/A",
            "source": item["source"],
            "related_queries": related,
            "product_intent_score": score_intent(item["topic"], related),
            "suggested_categories": map_categories(item["topic"], related),
        })

    deduped = dedupe(enriched)
    deduped.sort(key=lambda t: t["product_intent_score"], reverse=True)
    ranked = [{"rank": i + 1, **t} for i, t in enumerate(deduped)]

    payload = {
        "metadata": {
            "scraped_at": datetime.now(timezone.utc)
                .isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "geo": "IN",
            "total_topics": len(ranked),
            "sources": ["google_trends_daily", "youtube_trending", "google_news_rss"],
        },
        "trends": ranked,
    }

    log.info(
        "Fetch.Score.Dedupe.Rank: %d topics | YT:%d Trends:%d News:%d",
        len(ranked), len(yt_items), len(trends_items), len(news_items),
    )
    ctx["ranked_payload"] = payload
    return ctx
