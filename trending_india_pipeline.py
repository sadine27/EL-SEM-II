"""trending_india_pipeline.py

Part 1 of the SaaS dropshipping pipeline: fetch trending topics from India
(Google Trends + YouTube + Google News RSS), score them for product-purchase
intent, and export a normalised JSON file consumed by the downstream ad-spy
/ Selenium stage.

Runnable standalone: `python trending_india_pipeline.py`
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Auto-install block (runs before other imports so a fresh machine just works)
# ---------------------------------------------------------------------------
import importlib
import subprocess
import sys


def _install(pkg: str, import_name: str | None = None) -> None:
    """Install `pkg` via pip if `import_name` (or `pkg`) is not importable."""
    name = import_name or pkg.replace("-", "_")
    try:
        importlib.import_module(name)
    except ImportError:
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", pkg, "-q"]
        )


for _pkg, _mod in [
    ("pytrends-modern", "pytrends_modern"),
    ("feedparser", "feedparser"),
    ("python-dotenv", "dotenv"),
    ("requests", "requests"),
]:
    _install(_pkg, _mod)


# ---------------------------------------------------------------------------
# Standard imports
# ---------------------------------------------------------------------------
import json
import logging
import os
import re
import string
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import feedparser
import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

# pytrends-modern is imported lazily inside methods so a broken install
# does not prevent the rest of the pipeline (YouTube + RSS) from running.


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
CONFIG: dict[str, Any] = {
    "geo": "IN",
    "language": "en-IN",
    "max_topics": 1000,
    "request_delay_seconds": 5,
    "youtube_max_results": 50,
    "rss_max_entries": 100,
    "min_product_intent_score": 0.0,
    "output_dir": str(Path(__file__).parent / "output"),
    # New: cap the number of pytrends related_queries expansions per run
    # (the call is the biggest rate-limit risk). Topics beyond this cap still
    # get scored using only their own title words.
    "max_related_expansions": 40,
    # Minimum + maximum related_queries per topic in output
    "min_related_per_topic": 3,
    "max_related_per_topic": 10,
}


# ---------------------------------------------------------------------------
# Scoring constants (tiered so >100 keywords don't saturate every topic to 1.0)
# ---------------------------------------------------------------------------
# Tier 1 — Immediate Transactional (wallet is out)
HIGH_INTENT_TIER1: tuple[str, ...] = (
    "buy", "price", "cheap", "best", "review", "order", "shop", "deal",
    "discount", "sale", "offer", "coupon", "promo code", "clearance",
    "cash on delivery", "cod", "free shipping", "emi", "in stock",
    "where to buy", "lowest price", "cheap price", "wholesale", "bulk",
    "dropship", "distributor", "under 500", "under 1000",
)
# Tier 2 — Commercial Investigation (narrowing down options)
HIGH_INTENT_TIER2: tuple[str, ...] = (
    "alternative to", "similar to", "replacement for", "specs",
    "specifications", "features", "dimensions", "unboxing", "hands on",
    "teardown", "pros and cons", "is it worth it", "buying guide",
    "top 10", "top 5", "tier list", "ranking", "benchmarks", "reddit",
    "quora", "combo", "kit", "pack", "vs", "comparison",
)
# Tier 3 — Trust verifiers + urgency + strong descriptors
HIGH_INTENT_TIER3: tuple[str, ...] = (
    "wireless", "portable", "new", "latest", "trending", "india 2026",
    "original", "authentic", "genuine", "fake vs real", "refurbished",
    "second hand", "used", "open box", "warranty", "return policy",
    "customer service", "size chart", "colors", "variants", "edition",
    "flash sale", "limited time", "lightning deal", "restock", "sold out",
    "in stock tracker", "pre-order", "launch date", "release date",
    "early access", "near me",
)
# Negative intent (informational / DIY — pull the score down)
NEGATIVE_KEYWORDS: tuple[str, ...] = (
    "how to", "tutorial", "diy", "repair", "fix", "not working", "error",
    "broken", "manual", "pdf", "driver download", "free download",
)

TIER_WEIGHTS: dict[str, float] = {
    "t1": 0.30,
    "t2": 0.15,
    "t3": 0.10,
    "neg": -0.20,
}

CATEGORY_MAPPING: dict[str, list[str]] = {
    "electronics": [
        "wireless", "bluetooth", "earbuds", "phone", "laptop", "usb",
        "charger", "led", "power bank", "smartwatch", "speaker",
        "monitor", "cable", "adapter", "tablet", "camera",
    ],
    "fashion": [
        "shirt", "dress", "kurta", "saree", "sneakers", "watch", "bag",
        "sunglasses", "jeans", "t-shirt", "jacket", "shoes", "hoodie",
        "heels", "wallet", "belt",
    ],
    "home": [
        "kitchen", "decor", "organizer", "cleaning", "storage", "fan",
        "cooler", "light", "bottle", "bedsheet", "pillow", "cookware",
        "blender", "mop", "towel", "vacuum",
    ],
    "fitness": [
        "gym", "yoga", "protein", "supplement", "band", "tracker",
        "cycle", "dumbbells", "mat", "creatine", "whey", "treadmill",
        "resistance", "shaker", "massager",
    ],
    "beauty": [
        "skincare", "hair", "serum", "moisturizer", "lipstick",
        "foundation", "sunscreen", "shampoo", "perfume", "lotion",
        "concealer", "trimmer", "face wash", "makeup", "cleanser",
    ],
    "accessories": [
        "case", "cover", "stand", "holder", "mount", "strap",
        "tempered glass", "sleeve", "skin", "guard", "ring",
        "tripod", "grip", "hub",
    ],
    "automotive": [
        "car", "bike", "helmet", "dashcam", "tyre", "wax", "polish",
        "wiper", "gps", "inflator", "mat", "coolant", "scratch",
        "jump starter", "perfume",
    ],
    "baby_and_kids": [
        "toy", "puzzle", "lego", "diaper", "stroller", "wipes",
        "pacifier", "onesie", "rattle", "plush", "scooter", "doll",
        "action figure", "bottle",
    ],
    "pets": [
        "dog", "cat", "food", "collar", "leash", "bed", "litter",
        "treats", "aquarium", "grooming", "cage", "harness", "shampoo",
        "bowl",
    ],
    "office_and_stationery": [
        "book", "notebook", "pen", "desk", "chair", "printer", "paper",
        "marker", "folder", "diary", "planner", "stapler", "calculator",
        "ink",
    ],
    "health_and_medical": [
        "thermometer", "massager", "vitamins", "mask", "sanitizer",
        "first aid", "scale", "oximeter", "braces", "monitor", "inhaler",
        "test kit", "support",
    ],
    "tools_and_hardware": [
        "drill", "screwdriver", "wrench", "saw", "tape", "hammer",
        "screws", "pliers", "multimeter", "ladder", "glue", "toolkit",
        "nails", "hinge",
    ],
    "grocery_and_food": [
        "coffee", "tea", "snacks", "chocolate", "dry fruits", "oil",
        "rice", "spices", "honey", "noodles", "sauce", "cereal", "pasta",
        "biscuit",
    ],
}

STOPWORDS: frozenset[str] = frozenset({
    "a", "an", "the", "in", "of", "for", "with", "is", "are", "was",
    "were", "and", "or", "on", "at", "to", "by", "from",
})


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------
class TrendingIndiaPipeline:
    """Fetch, score, dedupe and export trending topics from India.

    Sources in priority order: pytrends (realtime + daily), YouTube Data API v3,
    Google News RSS. Every network call is defensive — failures are logged and
    the run continues so the downstream pipeline always receives a JSON file.
    """

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        self.output_dir = Path(config["output_dir"])
        self.output_dir.mkdir(parents=True, exist_ok=True)

        date_str = datetime.now().strftime("%Y-%m-%d")
        log_path = self.output_dir / f"pipeline_errors_{date_str}.log"

        self.logger = logging.getLogger("trending_india_pipeline")
        self.logger.setLevel(logging.INFO)
        # Avoid duplicate handlers if the class is re-instantiated
        self.logger.handlers.clear()
        fh = logging.FileHandler(log_path, encoding="utf-8")
        fh.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(message)s"
        ))
        self.logger.addHandler(fh)
        sh = logging.StreamHandler(sys.stdout)
        sh.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
        self.logger.addHandler(sh)

        self._related_calls_used = 0
        self._pytrends_client = None  # lazy

    # ------------------------------------------------------------------
    # pytrends client (lazy)
    # ------------------------------------------------------------------
    def _get_pytrends(self):
        """Return a cached TrendReq instance, or None if the lib is broken."""
        if self._pytrends_client is False:
            return None
        if self._pytrends_client is not None:
            return self._pytrends_client
        try:
            from pytrends_modern import TrendReq
            self._pytrends_client = TrendReq(
                hl=self.config["language"], tz=330  # IST = UTC+5:30
            )
            return self._pytrends_client
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("pytrends-modern unavailable: %s", exc)
            self._pytrends_client = False
            return None

    # ------------------------------------------------------------------
    # Source 1a: pytrends realtime
    # ------------------------------------------------------------------
    def fetch_pytrends_realtime(self) -> list[dict]:
        """Fetch realtime trending searches for India. Falls back to TrendsRSS."""
        out: list[dict] = []
        client = self._get_pytrends()
        if client is None:
            return out

        # Primary: TrendReq.realtime_trending_searches
        try:
            df = client.realtime_trending_searches(pn=self.config["geo"])
            for _, row in df.iterrows():
                title = str(
                    row.get("title") or row.get("entityNames") or ""
                ).strip()
                if not title:
                    continue
                out.append({
                    "topic": title,
                    "traffic_estimate": "N/A",
                    "source": "google_trends_realtime",
                })
        except Exception as exc:  # noqa: BLE001
            self.logger.warning(
                "realtime_trending_searches failed (%s) — trying TrendsRSS",
                exc,
            )
            try:
                from pytrends_modern import TrendsRSS
                rss = TrendsRSS()
                # API varies across versions; try the two most common shapes
                try:
                    items = rss.get_trending(geo=self.config["geo"])
                except AttributeError:
                    items = rss.trending(geo=self.config["geo"])
                for item in items or []:
                    title = (
                        item.get("title") if isinstance(item, dict) else str(item)
                    )
                    if not title:
                        continue
                    traffic = (
                        item.get("approx_traffic", "N/A")
                        if isinstance(item, dict) else "N/A"
                    )
                    out.append({
                        "topic": str(title).strip(),
                        "traffic_estimate": str(traffic),
                        "source": "google_trends_realtime",
                    })
            except Exception as rss_exc:  # noqa: BLE001
                self.logger.error(
                    "TrendsRSS fallback also failed: %s", rss_exc
                )

        self.logger.info("pytrends realtime: %d topics", len(out))
        return out

    # ------------------------------------------------------------------
    # Source 1b: pytrends daily
    # ------------------------------------------------------------------
    def fetch_pytrends_daily(self) -> list[dict]:
        """Fetch the daily trending searches list for India."""
        out: list[dict] = []
        client = self._get_pytrends()
        if client is None:
            return out
        try:
            df = client.trending_searches(pn="india")
            for _, row in df.iterrows():
                # DataFrame is typically a single column of strings
                topic = str(row.iloc[0]).strip() if len(row) else ""
                if topic:
                    out.append({
                        "topic": topic,
                        "traffic_estimate": "N/A",
                        "source": "google_trends_daily",
                    })
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("trending_searches(india) failed: %s", exc)

        self.logger.info("pytrends daily: %d topics", len(out))
        return out

    # ------------------------------------------------------------------
    # Source 2: YouTube Data API v3
    # ------------------------------------------------------------------
    def fetch_youtube_trending(self) -> list[dict]:
        """Most-popular YouTube videos in India. Silently skips if no API key."""
        out: list[dict] = []
        key = os.getenv("YOUTUBE_API_KEY", "").strip()
        if not key:
            self.logger.warning(
                "YOUTUBE_API_KEY not set — skipping YouTube source"
            )
            return out

        try:
            resp = requests.get(
                "https://www.googleapis.com/youtube/v3/videos",
                params={
                    "chart": "mostPopular",
                    "regionCode": self.config["geo"],
                    "maxResults": self.config["youtube_max_results"],
                    "part": "snippet",
                    "key": key,
                },
                timeout=15,
            )
            resp.raise_for_status()
            items = resp.json().get("items", [])
            for item in items:
                sn = item.get("snippet", {})
                title = (sn.get("title") or "").strip()
                if not title:
                    continue
                tags = sn.get("tags", []) or []
                out.append({
                    "topic": title,
                    "traffic_estimate": "N/A",
                    "source": "youtube_trending",
                    "_tags": tags,  # stripped before export
                })
        except Exception as exc:  # noqa: BLE001
            self.logger.error("YouTube API failed: %s", exc)

        self.logger.info("YouTube trending: %d topics", len(out))
        return out

    # ------------------------------------------------------------------
    # Source 3: Google News RSS
    # ------------------------------------------------------------------
    def fetch_google_news_rss(self) -> list[dict]:
        """Google News India RSS titles (tertiary source)."""
        out: list[dict] = []
        try:
            feed = feedparser.parse(
                "https://news.google.com/rss?hl=en-IN&gl=IN&ceid=IN:en"
            )
            for entry in feed.entries[: self.config["rss_max_entries"]]:
                title = (getattr(entry, "title", "") or "").strip()
                if title:
                    out.append({
                        "topic": title,
                        "traffic_estimate": "N/A",
                        "source": "google_news_rss",
                    })
        except Exception as exc:  # noqa: BLE001
            self.logger.error("Google News RSS failed: %s", exc)

        self.logger.info("Google News RSS: %d topics", len(out))
        return out

    # ------------------------------------------------------------------
    # Related-query expansion (rate-limit sensitive)
    # ------------------------------------------------------------------
    def expand_related_queries(self, topic: str) -> list[str]:
        """Return related queries for `topic` from pytrends, or [] on failure.

        Respects `max_related_expansions` so we don't blow through the rate
        limit on a single run.
        """
        if self._related_calls_used >= self.config["max_related_expansions"]:
            return []
        client = self._get_pytrends()
        if client is None:
            return []

        try:
            client.build_payload(
                kw_list=[topic[:100]],  # Google Trends rejects very long kw
                geo=self.config["geo"],
                timeframe="now 1-d",
            )
            related = client.related_queries()
            self._related_calls_used += 1

            bucket = related.get(topic[:100], {}) if isinstance(related, dict) else {}
            queries: list[str] = []
            for key in ("top", "rising"):
                df = bucket.get(key) if isinstance(bucket, dict) else None
                if df is None:
                    continue
                try:
                    queries.extend(str(q) for q in df["query"].tolist())
                except Exception:  # noqa: BLE001
                    continue
            # Rate-limit courtesy sleep after a successful call
            time.sleep(self.config["request_delay_seconds"])
            # De-dupe while preserving order
            seen: set[str] = set()
            dedup = []
            for q in queries:
                q_norm = q.strip()
                if q_norm and q_norm.lower() not in seen:
                    seen.add(q_norm.lower())
                    dedup.append(q_norm)
            return dedup[: self.config["max_related_per_topic"]]
        except Exception as exc:  # noqa: BLE001
            self.logger.warning(
                "related_queries(%r) failed: %s — skipping", topic, exc
            )
            return []

    # ------------------------------------------------------------------
    # Scoring
    # ------------------------------------------------------------------
    def score_product_intent(self, topic: str, related: list[str]) -> float:
        """Heuristic 0.0–1.0 purchase-intent score (tiered keyword matching)."""
        haystack = " ".join([topic, *related]).lower()
        score = 0.0
        for phrase in HIGH_INTENT_TIER1:
            if phrase in haystack:
                score += TIER_WEIGHTS["t1"]
        for phrase in HIGH_INTENT_TIER2:
            if phrase in haystack:
                score += TIER_WEIGHTS["t2"]
        for phrase in HIGH_INTENT_TIER3:
            if phrase in haystack:
                score += TIER_WEIGHTS["t3"]
        for phrase in NEGATIVE_KEYWORDS:
            if phrase in haystack:
                score += TIER_WEIGHTS["neg"]
        return round(max(0.0, min(1.0, score)), 3)

    # ------------------------------------------------------------------
    # Category mapping (returns ALL matching categories)
    # ------------------------------------------------------------------
    def map_categories(self, topic: str, related: list[str]) -> list[str]:
        """Return every category whose keywords appear in topic/related text."""
        haystack = " ".join([topic, *related]).lower()
        # Word-boundary check so "mat" doesn't match "matter"
        matches: list[str] = []
        for category, keywords in CATEGORY_MAPPING.items():
            for kw in keywords:
                pattern = r"\b" + re.escape(kw.lower()) + r"\b"
                if re.search(pattern, haystack):
                    matches.append(category)
                    break
        return matches or ["uncategorized"]

    # ------------------------------------------------------------------
    # Deduplication
    # ------------------------------------------------------------------
    @staticmethod
    def _normalize_words(text: str) -> set[str]:
        stripped = text.lower().translate(
            str.maketrans("", "", string.punctuation)
        )
        return {w for w in stripped.split() if w and w not in STOPWORDS}

    def deduplicate(self, topics: list[dict]) -> list[dict]:
        """Merge topics with >70% word overlap; keep the one with more related queries."""
        kept: list[dict] = []
        for cand in topics:
            cand_words = self._normalize_words(cand["topic"])
            if not cand_words:
                continue
            duplicate_idx: int | None = None
            for idx, existing in enumerate(kept):
                existing_words = self._normalize_words(existing["topic"])
                if not existing_words:
                    continue
                overlap = len(cand_words & existing_words)
                smaller = min(len(cand_words), len(existing_words))
                if smaller and overlap / smaller > 0.70:
                    duplicate_idx = idx
                    break
            if duplicate_idx is None:
                kept.append(cand)
            else:
                existing = kept[duplicate_idx]
                if len(cand.get("related_queries", [])) > len(
                    existing.get("related_queries", [])
                ):
                    kept[duplicate_idx] = cand
        return kept

    # ------------------------------------------------------------------
    # Orchestration
    # ------------------------------------------------------------------
    def run(self) -> dict:
        """Run every source, score, deduplicate, and return the final payload."""
        raw: list[dict] = []
        raw += self.fetch_pytrends_realtime()
        raw += self.fetch_pytrends_daily()
        raw += self.fetch_youtube_trending()
        raw += self.fetch_google_news_rss()

        self.logger.info("Total raw topics: %d", len(raw))

        # Cap at max_topics to keep runtime bounded
        raw = raw[: self.config["max_topics"]]

        enriched: list[dict] = []
        for item in raw:
            topic = item["topic"]
            tag_hints: list[str] = item.pop("_tags", []) if "_tags" in item else []

            related = self.expand_related_queries(topic)
            # Pad from YouTube tags if pytrends gave us too few
            if len(related) < self.config["min_related_per_topic"]:
                for t in tag_hints:
                    if t and t not in related:
                        related.append(t)
                    if len(related) >= self.config["min_related_per_topic"]:
                        break
            # Still not enough? Pad with topic words so schema (min 3) holds
            if len(related) < self.config["min_related_per_topic"]:
                words = [
                    w for w in self._normalize_words(topic)
                    if len(w) > 2
                ]
                for w in words:
                    if w not in related:
                        related.append(w)
                    if len(related) >= self.config["min_related_per_topic"]:
                        break

            related = related[: self.config["max_related_per_topic"]]

            enriched.append({
                "topic": topic,
                "traffic_estimate": item.get("traffic_estimate", "N/A"),
                "source": item["source"],
                "related_queries": related,
                "product_intent_score": self.score_product_intent(topic, related),
                "suggested_categories": self.map_categories(topic, related),
            })

        deduped = self.deduplicate(enriched)

        # Filter + sort
        min_score = self.config["min_product_intent_score"]
        filtered = [t for t in deduped if t["product_intent_score"] >= min_score]
        filtered.sort(key=lambda t: t["product_intent_score"], reverse=True)

        # Assign final rank
        for rank, topic in enumerate(filtered, start=1):
            topic["rank"] = rank
        # Reorder keys so rank is first in the JSON
        filtered = [_reorder(t) for t in filtered]

        return {
            "metadata": {
                "scraped_at": datetime.now(timezone.utc).isoformat(),
                "geo": self.config["geo"],
                "total_topics": len(filtered),
                "sources": [
                    "google_trends_realtime",
                    "google_trends_daily",
                    "youtube_trending",
                ],
            },
            "trends": filtered,
        }

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------
    def export_json(self, data: dict) -> str:
        """Write the payload to `trending_india_<YYYY-MM-DD>.json` (UTF-8)."""
        date_str = datetime.now().strftime("%Y-%m-%d")
        out_path = self.output_dir / f"trending_india_{date_str}.json"
        with open(out_path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
        self.logger.info("Wrote %s", out_path)
        return str(out_path)


def _reorder(topic: dict) -> dict:
    """Return a new dict with `rank` first — purely for human-readable JSON."""
    ordered = {"rank": topic["rank"]}
    for k in (
        "topic", "traffic_estimate", "source", "related_queries",
        "product_intent_score", "suggested_categories",
    ):
        ordered[k] = topic[k]
    return ordered


# ---------------------------------------------------------------------------
# Entrypoint (never crashes — always produces output)
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    pipeline = TrendingIndiaPipeline(CONFIG)
    try:
        results = pipeline.run()
    except Exception as exc:  # noqa: BLE001
        pipeline.logger.exception("Pipeline crashed: %s", exc)
        results = {
            "metadata": {
                "scraped_at": datetime.now(timezone.utc).isoformat(),
                "geo": CONFIG["geo"],
                "total_topics": 0,
                "sources": [
                    "google_trends_realtime",
                    "google_trends_daily",
                    "youtube_trending",
                ],
            },
            "trends": [],
        }
    path = pipeline.export_json(results)
    print(f"Done. {len(results['trends'])} topics exported. -> {path}")
