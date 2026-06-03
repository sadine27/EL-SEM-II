"""Tests for el/nodes/score_rank.py."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import requests

from el.nodes import score_rank as sr


def _fake_response(text: str, ok: bool = True, status_code: int = 200):
    resp = MagicMock(spec=requests.Response)
    resp.ok = ok
    resp.status_code = status_code
    resp.text = text
    if not ok:
        resp.raise_for_status.side_effect = requests.HTTPError(f"{status_code} Error")
    else:
        resp.raise_for_status.return_value = None
    return resp


# ---------- score_intent ----------

def test_score_intent_t1_hit():
    assert sr.score_intent("best wireless earbuds price", []) > 0.5


def test_score_intent_clamps_to_one():
    # All three T1 phrases stack: 3 * 0.30 = 0.90, plus T3 'wireless' = 1.0.
    topic = "buy cheap best wireless earbuds price"
    assert sr.score_intent(topic, []) == 1.0


def test_score_intent_clamps_to_zero_with_negatives():
    # NEG drags below 0.
    assert sr.score_intent("how to repair broken phone", []) == 0.0


def test_score_intent_uses_related():
    base = sr.score_intent("xyz product", [])
    boosted = sr.score_intent("xyz product", ["best price"])
    assert boosted > base


def test_score_intent_rounded_to_three_dp():
    val = sr.score_intent("wireless", [])  # single T3 = 0.10
    assert val == 0.1
    assert isinstance(val, float)


# ---------- map_categories ----------

def test_map_categories_known_keyword():
    assert "electronics" in sr.map_categories("new wireless earbuds", [])


def test_map_categories_uncategorized_when_no_match():
    assert sr.map_categories("xyzzy plugh", []) == ["uncategorized"]


def test_map_categories_word_boundary():
    # 'cat' should match only as a standalone word (pets), not inside 'category'.
    assert "pets" not in sr.map_categories("category management", [])


def test_map_categories_multiple():
    cats = sr.map_categories("yoga mat and protein shaker bottle", [])
    assert "fitness" in cats


# ---------- normalize_words / dedupe ----------

def test_normalize_words_strips_stopwords_and_punct():
    assert sr.normalize_words("The Best, Wireless Earbuds!") == {
        "best", "wireless", "earbuds"
    }


def test_dedupe_keeps_distinct_topics():
    items = [
        {"topic": "wireless earbuds", "related_queries": []},
        {"topic": "yoga mat", "related_queries": []},
    ]
    assert len(sr.dedupe(items)) == 2


def test_dedupe_collapses_high_overlap():
    items = [
        {"topic": "wireless earbuds review", "related_queries": []},
        {"topic": "wireless earbuds", "related_queries": []},
    ]
    # Second has 2/2 overlap with smaller set -> 1.0 > 0.7 -> dup.
    assert len(sr.dedupe(items)) == 1


def test_dedupe_replaces_with_richer_related():
    items = [
        {"topic": "wireless earbuds", "related_queries": []},
        {"topic": "wireless earbuds review", "related_queries": ["a", "b"]},
    ]
    result = sr.dedupe(items)
    assert len(result) == 1
    assert result[0]["related_queries"] == ["a", "b"]


def test_dedupe_skips_empty_topic():
    items = [{"topic": "the and or", "related_queries": []}]  # all stopwords
    assert sr.dedupe(items) == []


# ---------- parse_youtube ----------

def test_parse_youtube_extracts_titles():
    items = [
        {"snippet": {"title": "  Cool Video  ", "tags": ["x", "y"]}},
        {"snippet": {"title": ""}},  # skipped
        {"snippet": {}},  # no title
        {},  # no snippet
    ]
    out = sr.parse_youtube(items)
    assert len(out) == 1
    assert out[0]["topic"] == "Cool Video"
    assert out[0]["source"] == "youtube_trending"
    assert out[0]["tags"] == ["x", "y"]


# ---------- parse_rss_titles ----------

def test_parse_rss_titles_skips_channel_title():
    xml = (
        "<rss><channel>"
        "<title>Daily Search Trends</title>"
        "<item><title><![CDATA[Topic One]]></title></item>"
        "<item><title>Topic Two</title></item>"
        "</channel></rss>"
    )
    out = sr.parse_rss_titles(xml, "google_trends_daily")
    assert [o["topic"] for o in out] == ["Topic One", "Topic Two"]
    assert all(o["source"] == "google_trends_daily" for o in out)


def test_parse_rss_titles_respects_limit():
    inner = "".join(f"<item><title>Item {i}</title></item>" for i in range(5))
    xml = f"<rss><channel><title>Feed</title>{inner}</channel></rss>"
    assert len(sr.parse_rss_titles(xml, "src", limit=3)) == 3


# ---------- run ----------

def test_run_integrates_youtube_and_feeds():
    ctx = {
        "youtube_items": [
            {"snippet": {"title": "Best Wireless Earbuds Price 2026",
                         "tags": ["earbuds", "audio"]}},
            {"snippet": {"title": "How To Fix A Phone"}},  # negatives -> score 0
        ],
    }
    trends_xml = (
        "<rss><channel><title>Feed</title>"
        "<item><title>Yoga Mat Sale</title></item>"
        "</channel></rss>"
    )
    news_xml = (
        "<rss><channel><title>News</title>"
        "<item><title>Trending Smartwatch Launch Date</title></item>"
        "</channel></rss>"
    )

    def fake_get(url, *a, **kw):
        if "trends.google.com" in url:
            return _fake_response(trends_xml)
        if "news.google.com" in url:
            return _fake_response(news_xml)
        raise AssertionError(f"unexpected URL: {url}")

    with patch.object(sr.requests, "get", side_effect=fake_get):
        out = sr.run(ctx)

    payload = out["ranked_payload"]
    assert payload["metadata"]["geo"] == "IN"
    # google_trends_daily was removed (the RSS endpoint 404s permanently), so
    # only YouTube (2) + Google News (1) feed score_rank now.
    assert payload["metadata"]["total_topics"] == 3
    topics = [t["topic"] for t in payload["trends"]]
    assert topics[0] == "Best Wireless Earbuds Price 2026"  # highest score
    # Ranks are 1-indexed and contiguous.
    assert [t["rank"] for t in payload["trends"]] == [1, 2, 3]
    # Sources passed through.
    assert {t["source"] for t in payload["trends"]} == {
        "youtube_trending", "google_news_rss",
    }


def test_run_survives_rss_failure():
    ctx = {"youtube_items": [
        {"snippet": {"title": "Wireless Earbuds", "tags": []}},
    ]}

    def fake_get(url, *a, **kw):
        raise requests.ConnectionError("network down")

    with patch.object(sr.requests, "get", side_effect=fake_get):
        out = sr.run(ctx)

    assert out["ranked_payload"]["metadata"]["total_topics"] == 1
    assert out["ranked_payload"]["trends"][0]["topic"] == "Wireless Earbuds"


def test_run_with_no_youtube_items():
    ctx: dict = {}
    with patch.object(sr.requests, "get", side_effect=requests.ConnectionError("x")):
        out = sr.run(ctx)
    assert out["ranked_payload"]["metadata"]["total_topics"] == 0
    assert out["ranked_payload"]["trends"] == []


# ---------- velocity boost (Fenix) ----------

def test_velocity_boost_raises_rising_trend():
    base = sr.score_intent("mystery gadget", [])
    rising = sr.score_intent("mystery gadget", [], velocity=1.0)
    assert rising > base


def test_velocity_penalty_lowers_falling_trend():
    base = sr.score_intent("best wireless earbuds price", [])
    falling = sr.score_intent("best wireless earbuds price", [], velocity=-1.0)
    assert falling < base


def test_velocity_boost_is_clamped():
    # Even an absurd velocity cannot push the score above 1.0.
    assert sr.score_intent("buy cheap best price", [], velocity=999.0) == 1.0


# ---------- TOPIC_EXCLUSIONS (the earbuds -> fashion bug fix) ----------

def test_earbuds_not_mapped_to_fashion():
    cats = sr.map_categories("wireless earbuds", [])
    assert "electronics" in cats
    assert "fashion" not in cats
    assert "beauty" not in cats


def test_exclusion_zone_removes_excluded_even_with_keyword_hit():
    # "case" is an accessories keyword, but a smartphone topic excludes nothing
    # about accessories; instead verify a fashion-anchored topic excludes electronics.
    cats = sr.map_categories("designer saree with usb cable", [])
    assert "electronics" not in cats  # excluded by 'saree'


# ---------- anchor scoring ----------

def test_anchor_outweighs_single_keyword():
    # 'gaming laptop' is a 2-word electronics anchor (+4 + 3 = 7); a lone 'fan'
    # keyword for home (+1) must not beat it.
    cats = sr.map_categories("gaming laptop with fan", [])
    assert cats[0] == "electronics"


# ---------- sports_and_merch (RCB jersey) ----------

def test_rcb_jersey_maps_to_sports_and_merch():
    cats = sr.map_categories("RCB jersey", [])
    assert "sports_and_merch" in cats


def test_fan_merch_excludes_electronics_and_food():
    cats = sr.map_categories("official team jersey and merchandise", [])
    assert "sports_and_merch" in cats
    assert "electronics" not in cats
    assert "grocery_and_food" not in cats


# ---------- cross-source boost + pluggable source_candidates path ----------

def test_cross_source_boost_in_run():
    from el.sources import TrendCandidate
    # Same topic from three independent pluggable sources -> cross-source boost.
    ctx = {
        "source_candidates": [
            TrendCandidate(title="trending smart bottle", source_id="pytrends"),
            TrendCandidate(title="trending smart bottle", source_id="reddit"),
            TrendCandidate(title="trending smart bottle", source_id="rss_india"),
        ],
    }
    with patch.object(sr.requests, "get", side_effect=requests.ConnectionError("x")):
        out = sr.run(ctx)
    trend = out["ranked_payload"]["trends"][0]
    assert trend["cross_source_count"] == 3


def test_source_candidates_velocity_flows_into_payload():
    from el.sources import TrendCandidate
    ctx = {
        "source_candidates": [
            TrendCandidate(title="viral new toy", source_id="pytrends", velocity=0.8),
        ],
    }
    with patch.object(sr.requests, "get", side_effect=requests.ConnectionError("x")):
        out = sr.run(ctx)
    trend = out["ranked_payload"]["trends"][0]
    assert trend["velocity"] == 0.8
    assert trend["source"] == "pytrends"


def test_youtube_source_candidates_skipped_to_avoid_double_count():
    from el.sources import TrendCandidate
    # A youtube TrendCandidate must be ignored here (it arrives via youtube_items).
    ctx = {
        "youtube_items": [{"snippet": {"title": "Wireless Earbuds", "tags": []}}],
        "source_candidates": [
            TrendCandidate(title="Wireless Earbuds", source_id="youtube"),
        ],
    }
    with patch.object(sr.requests, "get", side_effect=requests.ConnectionError("x")):
        out = sr.run(ctx)
    topics = [t["topic"] for t in out["ranked_payload"]["trends"]]
    assert topics.count("Wireless Earbuds") == 1
