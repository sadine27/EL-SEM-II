"""Tests for the Forge marketplace source's believable-economics simulation.

The marketplace source scrapes a *retail* price from a real listing. These tests
assert it turns that one real number into an internally-consistent economic record
(retail = sell reference, simulated wholesale cost + delivery window) and that the
record flows through Sentinel to a believable margin and an un-inflated store price.
"""
from __future__ import annotations

from el.nodes import normalize_sentinel_review, sentinel_vetting
from el.suppliers import marketplace_source

_JSONLD_PAGE = """
<html><head>
<script type="application/ld+json">
{"@type":"Product","name":"RCB Jersey 2025 Official",
 "image":"https://m.media-amazon.com/images/rcb.jpg",
 "offers":{"price":"1000","availability":"https://schema.org/InStock"},
 "aggregateRating":{"ratingValue":"4.3"}}
</script>
</head><body>RCB Jersey</body></html>
"""


def _extract_one(monkeypatch, html=_JSONLD_PAGE):
    src = marketplace_source.MarketplaceSource(provider=object())  # provider unused (JSON-LD path)
    monkeypatch.setattr(src, "_fetch_html", lambda url: html)
    return src._extract(
        "RCB jersey",
        {"url": "https://www.amazon.in/dp/B0RCB", "title": "RCB Jersey"},
    )


# --------------------------------------------------------------------------- #
# economics simulation at the source                                          #
# --------------------------------------------------------------------------- #
def test_scraped_price_becomes_retail_reference_not_cost(monkeypatch):
    cand = _extract_one(monkeypatch)
    assert cand is not None
    # scraped ₹1000 is the RETAIL price, kept as the sell-side market reference
    assert cand.raw_payload["market_price"] == 1000.0
    assert cand.raw_payload["simulated_economics"] is True
    # wholesale cost is back-inferred (default factor 0.55) — never the retail price
    assert cand.cost == 550.0
    assert cand.currency == "INR"


def test_simulated_delivery_window_is_set(monkeypatch):
    cand = _extract_one(monkeypatch)
    assert cand.shipping_days_min == 3
    assert cand.shipping_days_max == 7
    assert cand.shipping_cost == 0.0
    assert cand.stock == 1


def test_cost_factor_is_env_tunable(monkeypatch):
    monkeypatch.setenv("EL_MARKETPLACE_COST_FACTOR", "0.40")
    cand = _extract_one(monkeypatch)
    assert cand.cost == 400.0  # 1000 * 0.40
    assert cand.raw_payload["market_price"] == 1000.0  # retail unchanged


# --------------------------------------------------------------------------- #
# the record flows through Sentinel to a real margin and an un-inflated price  #
# --------------------------------------------------------------------------- #
def _marketplace_match() -> dict:
    """A Forge match as supplier_search emits for a marketplace candidate."""
    return {
        "title": "RCB Jersey 2025 Official",
        "source_id": "marketplace",
        "product_url": "https://www.amazon.in/dp/B0RCB",
        "image_url": "https://m.media-amazon.com/images/rcb.jpg",
        "cost": 550.0,
        "currency": "INR",
        "shipping_cost": 0.0,
        "shipping_days_min": 3,
        "shipping_days_max": 7,
        "stock": 1,
        "rating": 4.3,
        "match_score": 0.8,
        "landed_cost": 550.0,
        "raw_payload": {"market_price": 1000.0, "simulated_economics": True},
    }


def test_sentinel_computes_believable_margin_from_retail():
    ctx = {"supplier_matches": [
        {"trend": {"topic": "RCB jersey", "rank": 1}, "query": "RCB jersey",
         "matches": [_marketplace_match()]},
    ]}
    sentinel_vetting.run(ctx)
    match = ctx["sentinel_matches"][0]["matches"][0]
    assert match["sentinel_decision"] == "pass"
    # sell = real retail (not landed * markup), margin = (1000 - 550) / 1000
    assert match["projected_sell_price"] == 1000.0
    assert match["projected_margin_pct"] == 0.45
    assert "margin_estimated_from_markup" not in match["sentinel_warnings"]


def test_store_price_is_real_retail_not_inflated():
    ctx = {"supplier_matches": [
        {"trend": {"topic": "RCB jersey", "rank": 1}, "query": "RCB jersey",
         "matches": [_marketplace_match()]},
    ]}
    sentinel_vetting.run(ctx)
    normalize_sentinel_review.run(ctx)
    row = ctx["sentinel_review_items"][0]
    # the listed price is the real scraped retail price — not cost * markup
    assert row["price_numeric"] == 1000.0
    assert row["product_name"] == "RCB Jersey 2025 Official"
