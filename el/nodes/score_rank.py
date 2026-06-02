"""Fenix Engine — Fetch · Score · Dedupe · Rank (v2).

Reads all pluggable source candidates from ctx["source_candidates"] plus
inline Google Trends RSS and Google News RSS, then:

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
from el.sources import TrendCandidate

log = get_logger(__name__)

TRENDS_RSS_URL = "https://trends.google.com/trends/trendingsearches/daily/rss?geo=IN"
NEWS_RSS_URL = "https://news.google.com/rss?hl=en-IN&gl=IN&ceid=IN:en"
RSS_TIMEOUT = 30
MAX_RAW_ITEMS = 2000
MAX_NEWS_ITEMS = 100
DEDUPE_OVERLAP_THRESHOLD = 0.70

# ── Intent keyword tiers ──────────────────────────────────────────────────────
T1_BUYER = (
    "buy", "price", "cheap", "best", "review", "order", "shop", "deal",
    "discount", "sale", "offer", "coupon", "promo code", "clearance",
    "cash on delivery", "cod", "free shipping", "emi", "in stock",
    "where to buy", "lowest price", "wholesale", "bulk",
    "dropship", "under 500", "under 1000", "₹", "rs.",
    "amazon", "flipkart", "meesho", "myntra", "nykaa", "ajio", "snapdeal",
)
T2_RESEARCH = (
    "alternative to", "similar to", "replacement for", "specs",
    "specifications", "features", "unboxing", "hands on",
    "pros and cons", "is it worth it", "buying guide",
    "top 10", "top 5", "tier list", "ranking", "benchmarks",
    "combo", "kit", "pack", "vs", "comparison",
)
T3_AMBIENT = (
    "wireless", "portable", "new", "latest", "trending", "2026",
    "original", "authentic", "genuine", "refurbished",
    "open box", "warranty", "return policy",
    "flash sale", "limited time", "lightning deal", "restock",
    "pre-order", "launch date", "release date", "near me",
)
NEG = (
    "how to", "tutorial", "diy", "repair", "fix", "not working", "error",
    "broken", "manual", "pdf", "driver download", "free download",
    "arrested", "died", "death", "funeral", "war", "blast", "attack",
    "accident", "protest", "politics", "election",
)

# ── Category configuration ────────────────────────────────────────────────────
# anchors  → high-specificity terms; each match scores +4 + 1.5 × word_count
# keywords → regular terms; each match scores +1
# priority → tie-breaker when two categories score identically
#
CATEGORIES: dict[str, dict] = {
    "electronics": {
        "priority": 10,
        "anchors": {
            "earbuds", "tws", "airpods", "airbuds", "neckband", "true wireless",
            "noise cancelling", "anc headphone", "gaming headset",
            "smartphone", "5g phone", "4g phone", "iphone", "samsung galaxy",
            "android phone", "foldable phone",
            "laptop", "macbook", "chromebook", "gaming laptop", "ultrabook",
            "power bank", "powerbank", "fast charger", "wireless charger",
            "smartwatch", "mi band", "galaxy watch", "fitness tracker",
            "fire tv stick", "android tv", "smart tv",
            "mechanical keyboard", "gaming mouse", "gaming chair", "gaming monitor",
            "router", "wifi extender", "mesh wifi", "wifi 6",
            "graphics card", "gpu", "processor", "cpu", "ssd", "nvme",
            "ram", "ddr5", "ddr4",
            "action camera", "gopro", "security camera", "cctv", "doorbell camera",
            "electric scooter", "ev charger",
            "kindle", "e-reader",
        },
        "keywords": {
            "wireless", "bluetooth", "phone", "usb", "charger",
            "monitor", "cable", "adapter", "tablet", "camera", "speaker",
            "headphone", "keyboard", "mouse", "display", "screen",
            "gaming", "pc", "computer", "drone", "projector", "tv",
            "earphone", "audio", "microphone", "webcam", "led",
            "hard disk", "pendrive", "memory card", "sdcard",
        },
    },
    "fashion": {
        "priority": 8,
        "anchors": {
            "kurta", "saree", "salwar", "dupatta", "lehenga", "churidar",
            "ethnic wear", "western wear", "ootd", "outfit of the day",
            "streetwear", "athleisure", "activewear", "fast fashion",
            "fashion week", "runway look", "kurti set",
        },
        "keywords": {
            "shirt", "dress", "jeans", "sneakers", "sunglasses",
            "t-shirt", "jacket", "shoes", "hoodie", "heels", "wallet",
            "fashion", "style", "clothing", "apparel", "wear", "outfit",
            "boots", "sandals", "cap", "hat", "scarf", "leggings",
            "blouse", "blazer", "trouser", "skirt", "tights",
        },
    },
    "home": {
        "priority": 7,
        "anchors": {
            "air purifier", "water purifier", "ro filter", "air fryer",
            "instant pot", "electric pressure cooker", "induction cooktop",
            "washing machine", "refrigerator", "microwave oven",
            "robot vacuum", "air conditioner", "ceiling fan",
            "smart bulb", "led strip light", "diffuser", "humidifier",
        },
        "keywords": {
            "kitchen", "decor", "organizer", "cleaning", "storage", "fan",
            "cooler", "light", "bottle", "bedsheet", "pillow", "cookware",
            "blender", "mop", "towel", "vacuum", "mixer", "grinder",
            "curtain", "mattress", "furniture", "lamp",
        },
    },
    "fitness": {
        "priority": 7,
        "anchors": {
            "whey protein", "creatine monohydrate", "mass gainer",
            "pre workout", "bcaa", "protein powder", "vegan protein",
            "yoga mat", "resistance band", "gym gloves", "lifting straps",
            "treadmill", "elliptical", "rowing machine", "stationary bike",
            "dumbbells set", "barbell", "pull up bar", "ab roller",
            "foam roller", "massage gun",
        },
        "keywords": {
            "gym", "yoga", "protein", "supplement", "band", "tracker",
            "cycle", "dumbbells", "mat", "creatine", "whey",
            "resistance", "shaker", "massager", "fitness", "workout",
            "exercise", "training", "sports", "running", "weight",
        },
    },
    "beauty": {
        "priority": 8,
        "anchors": {
            "vitamin c serum", "hyaluronic acid", "niacinamide",
            "spf 50", "spf 30", "sunscreen", "retinol", "salicylic acid",
            "hair serum", "hair oil", "scalp treatment",
            "bb cream", "cc cream", "setting powder", "baking powder",
            "lip gloss", "lip liner", "kajal", "eyeliner", "mascara",
            "face pack", "sheet mask", "under eye cream", "eye cream",
            "beard oil", "beard grooming", "hair growth oil",
        },
        "keywords": {
            "skincare", "hair", "serum", "moisturizer", "lipstick",
            "sunscreen", "shampoo", "perfume", "lotion",
            "trimmer", "face wash", "makeup", "cleanser", "toner",
            "conditioner", "cream", "gel", "essence", "mist",
            "nail", "beauty", "glow", "brightening",
        },
    },
    "accessories": {
        "priority": 6,
        "anchors": {
            "phone case", "mobile case", "laptop bag", "laptop sleeve",
            "screen protector", "tempered glass", "phone stand",
            "smartwatch strap", "watch band", "watch strap",
            "camera bag", "tripod", "lens filter", "gimbal",
            "cable organizer", "charging cable", "data cable",
        },
        "keywords": {
            "case", "cover", "stand", "holder", "mount", "strap",
            "sleeve", "skin", "guard", "ring", "grip", "hub", "dock",
            "pouch", "lanyard", "clip", "protector",
        },
    },
    "automotive": {
        "priority": 7,
        "anchors": {
            "dashcam", "dash cam", "car mount", "car charger", "car air purifier",
            "bike helmet", "riding jacket", "riding gloves", "motorbike",
            "tyre inflator", "tyre pressure gauge",
            "jump starter", "car polish", "car wax", "paint protection",
            "seat cover", "steering wheel cover", "car organizer",
        },
        "keywords": {
            "car", "bike", "helmet", "tyre", "wax", "polish",
            "wiper", "gps", "inflator", "coolant",
            "automotive", "vehicle", "driving", "motor",
        },
    },
    "baby_and_kids": {
        "priority": 7,
        "anchors": {
            "baby monitor", "baby carrier", "diaper bag",
            "stroller", "pram", "baby walker", "baby swing",
            "lego set", "action figure", "board game", "card game",
            "fidget spinner", "rubik cube", "slime kit", "kinetic sand",
        },
        "keywords": {
            "toy", "puzzle", "lego", "diaper", "stroller", "wipes",
            "pacifier", "onesie", "rattle", "plush", "scooter",
            "doll", "baby", "kids", "child", "toddler",
            "infant", "newborn", "school", "drawing",
        },
    },
    "pets": {
        "priority": 7,
        "anchors": {
            "dog food", "cat food", "dry kibble", "wet pet food",
            "pet collar", "dog harness", "cat tree", "pet carrier",
            "automatic pet feeder", "aquarium setup", "fish tank",
        },
        "keywords": {
            "dog", "cat", "litter", "treats", "aquarium",
            "grooming", "cage", "harness", "pet", "puppy",
            "kitten", "fish", "bird", "hamster",
        },
    },
    "office_and_stationery": {
        "priority": 6,
        "anchors": {
            "standing desk", "monitor arm", "ergonomic chair",
            "whiteboard", "bulletin board",
            "fountain pen", "gel pen set", "notebook journal", "planner book",
        },
        "keywords": {
            "notebook", "pen", "desk", "chair",
            "printer", "paper", "marker", "folder", "diary",
            "planner", "stapler", "calculator", "ink", "office",
            "stationery", "filing", "binder",
        },
    },
    "health_and_medical": {
        "priority": 8,
        "anchors": {
            "blood pressure monitor", "glucose monitor", "pulse oximeter",
            "electric massager", "neck massager", "back massager",
            "first aid kit", "vitamin d3", "omega 3", "multivitamin",
            "immunity booster", "n95 mask", "surgical mask",
            "pain relief patch", "orthopaedic support",
        },
        "keywords": {
            "thermometer", "vitamins", "mask",
            "sanitizer", "first aid", "scale", "oximeter",
            "braces", "inhaler", "test kit", "health", "medical",
            "medicine", "immune", "digestion",
        },
    },
    "tools_and_hardware": {
        "priority": 6,
        "anchors": {
            "cordless drill", "power drill", "impact driver",
            "angle grinder", "jigsaw", "circular saw",
            "multimeter", "soldering iron", "oscilloscope",
            "toolbox set", "tool kit",
        },
        "keywords": {
            "drill", "screwdriver", "wrench", "saw", "tape",
            "hammer", "screws", "pliers", "ladder",
            "glue", "nails", "hinge", "tools", "hardware",
        },
    },
    "grocery_and_food": {
        "priority": 6,
        "anchors": {
            "cold pressed oil", "organic honey", "protein bar", "energy bar",
            "energy drink", "zero sugar drink", "keto snacks",
            "instant noodles", "ready to eat", "makhana", "roasted makhana",
            "dark chocolate", "mixed nuts", "trail mix", "dried fruits",
        },
        "keywords": {
            "coffee", "tea", "snacks", "chocolate", "dry fruits",
            "oil", "rice", "spices", "honey", "noodles", "sauce",
            "cereal", "pasta", "biscuit", "food", "drink", "beverage",
            "grocery", "organic", "natural",
        },
    },
    # Fan merchandise / event-driven trends (e.g. a team wins → fans buy jerseys).
    # Kept distinct from `fashion` so downstream curation can target merch directly.
    "sports_and_merch": {
        "priority": 9,
        "anchors": {
            "team jersey", "cricket jersey", "football jersey", "fan jersey",
            "ipl jersey", "rcb jersey", "csk jersey", "mi jersey",
            "world cup jersey", "fan merchandise", "fan merch", "official merch",
            "team merchandise", "signed memorabilia", "collectible figure",
            "limited edition drop", "anime figure", "funko pop",
        },
        "keywords": {
            "jersey", "merch", "merchandise", "memorabilia", "collectible",
            "fan", "supporter", "fandom", "poster", "flag", "scarf", "mug",
            "hoodie", "tshirt", "cap", "wristband", "keychain", "sticker",
            "figurine", "trophy", "replica",
        },
    },
}

# ── Hard exclusion zones ──────────────────────────────────────────────────────
# If ANY trigger term appears in the topic+tags haystack, those categories are
# completely removed from consideration regardless of keyword matches.
TOPIC_EXCLUSIONS: dict[str, set[str]] = {
    # Electronic product anchors exclude lifestyle/food categories
    "earbuds": {"fashion", "home", "grocery_and_food", "beauty", "pets"},
    "tws": {"fashion", "home", "grocery_and_food", "beauty"},
    "airpods": {"fashion", "home", "grocery_and_food", "beauty"},
    "neckband": {"fashion", "home", "grocery_and_food"},
    "smartphone": {"fashion", "home", "beauty", "grocery_and_food"},
    "laptop": {"fashion", "home", "beauty", "grocery_and_food"},
    "powerbank": {"fashion", "home", "beauty", "grocery_and_food"},
    "power bank": {"fashion", "home", "beauty", "grocery_and_food"},
    # Fashion anchors exclude electronics
    "kurta": {"electronics", "automotive", "tools_and_hardware"},
    "saree": {"electronics", "automotive", "tools_and_hardware"},
    "lehenga": {"electronics", "automotive", "tools_and_hardware"},
    "dress": {"electronics", "automotive", "tools_and_hardware"},
    # Food/fitness
    "recipe": {"electronics", "fashion", "automotive", "tools_and_hardware"},
    "protein powder": {"fashion", "automotive", "tools_and_hardware", "office_and_stationery"},
    # Entertainment — prevent media titles from mapping to product categories
    "cricket match": {"electronics", "beauty", "grocery_and_food"},
    "ipl 2026": {"electronics", "beauty", "grocery_and_food"},
    # Fan merch — a "jersey"/"merch" topic is apparel-adjacent, not electronics/food
    "jersey": {"electronics", "grocery_and_food", "tools_and_hardware", "automotive"},
    "merchandise": {"electronics", "grocery_and_food", "tools_and_hardware", "automotive"},
    "fan merch": {"electronics", "grocery_and_food", "tools_and_hardware", "automotive"},
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
_PUNCT_RE = re.compile(r"[^\w\s]")


# ── RSS helpers (kept for inline Trends + News RSS) ───────────────────────────

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


def fetch_trends_rss() -> list[dict]:
    try:
        r = requests.get(TRENDS_RSS_URL, timeout=RSS_TIMEOUT)
        r.raise_for_status()
        return parse_rss_titles(r.text, "google_trends_daily")
    except Exception as e:
        log.warning("Trends RSS failed: %s", e)
        return []


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

    Returns up to 2 categories when scores are close (second ≥ 60% of first).
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

def normalize_words(text: str) -> set[str]:
    return {w for w in _WORD_SPLIT_RE.split(text.lower())
            if w and w not in STOPWORDS}


def _normalize_topic(title: str) -> str:
    return _PUNCT_RE.sub("", title.lower()).strip()


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
    trends_items = fetch_trends_rss()
    news_items = fetch_news_rss()

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

    all_raw = (yt_items + trends_items + news_items + pluggable_items)[:MAX_RAW_ITEMS]

    # ── 2. Cross-source counting ─────────────────────────────────────────
    topic_sources: dict[str, set[str]] = defaultdict(set)
    for item in all_raw:
        norm = _normalize_topic(item["topic"])
        topic_sources[norm].add(item["source"])

    # ── 3. Score every item ──────────────────────────────────────────────
    enriched: list[dict] = []
    for item in all_raw:
        related = list(item.get("tags") or [])[:10]
        velocity = item.get("velocity")
        norm = _normalize_topic(item["topic"])
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

    # Sort: intent score → velocity → cross-source count
    deduped.sort(key=lambda t: (
        -t["product_intent_score"],
        -(t.get("velocity") or 0.0),
        -t.get("cross_source_count", 1),
    ))
    ranked = [{"rank": i + 1, **t} for i, t in enumerate(deduped)]

    # ── 4. Build and emit payload ────────────────────────────────────────
    all_source_ids = list({
        "google_trends_daily", "youtube_trending", "google_news_rss",
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
                "google_trends_rss": len(trends_items),
                "google_news_rss": len(news_items),
                "pluggable": len(pluggable_items),
            },
        },
        "trends": ranked,
    }

    log.info(
        "Fenix Rank: %d topics | YT:%d Trends:%d News:%d Pluggable:%d",
        len(ranked), len(yt_items), len(trends_items),
        len(news_items), len(pluggable_items),
    )
    ctx["ranked_payload"] = payload
    return ctx
