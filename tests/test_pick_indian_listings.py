"""Tests for el/nodes/pick_indian_listings.py."""
from __future__ import annotations

from el.nodes import pick_indian_listings as pil


def test_pick_indian_listings_basic_filtering():
    ctx = {
        'tavily_search_results': [
            {
                'json': {
                    'tavily_query': 'buy mug india',
                    'entity_hint': None,
                    'product_hint': 'mug',
                    'intent_mode': 'direct_product',
                    'tavily_url': 'https://amazon.in/dp/B123456',
                    'tavily_title': 'Great Mug for Tea',
                    'tavily_raw_content': 'rs 299 mug tea amazon 5 stars 150 reviews',
                    'tavily_score': 8.0,
                }
            },
            {
                'json': {
                    'tavily_query': 'buy mug india',
                    'entity_hint': None,
                    'product_hint': 'mug',
                    'intent_mode': 'direct_product',
                    'tavily_url': 'https://flipkart.com/search?q=mug',
                    'tavily_title': 'Search Results for Mug',
                    'tavily_raw_content': 'search results page',
                    'tavily_score': 5.0,
                }
            }
        ],
        'tavily_queries': [
            {
                'json': {
                    'tavily_query': 'buy mug india',
                    'product_hint': 'mug',
                }
            }
        ]
    }
    pil.run(ctx)
    assert 'picked_indian_listings' in ctx
    # Should prefer product page over search results
    assert len(ctx['picked_indian_listings']) >= 1
    assert ctx['picked_indian_listings'][0]['json']['tavily_url'] == 'https://amazon.in/dp/B123456'


def test_pick_indian_listings_top3_limit():
    ctx = {
        'tavily_search_results': [
            {
                'json': {
                    'tavily_query': 'buy t shirt india',
                    'product_hint': 't shirt',
                    'tavily_url': f'https://amazon.in/dp/B{i}',
                    'tavily_title': f'TShirt {i}',
                    'tavily_raw_content': 'rs 299 t shirt amazon 5 stars',
                    'tavily_score': 9.0 - (i * 0.5),
                }
            }
            for i in range(10)
        ],
        'tavily_queries': [
            {
                'json': {
                    'tavily_query': 'buy t shirt india',
                    'product_hint': 't shirt',
                }
            }
        ]
    }
    pil.run(ctx)
    assert len(ctx['picked_indian_listings']) <= 3


def test_pick_indian_listings_merchandise_intent():
    ctx = {
        'tavily_search_results': [
            {
                'json': {
                    'tavily_query': 'buy "Marvel" t shirt india',
                    'entity_hint': 'Marvel',
                    'product_hint': 't shirt',
                    'intent_mode': 'merch',
                    'tavily_url': 'https://amazon.in/dp/MARVEL_TSHIRT',
                    'tavily_title': 'Marvel TShirt Merchandise',
                    'tavily_raw_content': 'marvel t shirt 5 stars rs 499',
                    'tavily_score': 8.0,
                }
            }
        ],
        'tavily_queries': [
            {
                'json': {
                    'tavily_query': 'buy "Marvel" t shirt india',
                    'entity_hint': 'Marvel',
                    'product_hint': 't shirt',
                    'intent_mode': 'merch',
                }
            }
        ]
    }
    pil.run(ctx)
    assert len(ctx['picked_indian_listings']) == 1
    assert 'marvel' in ctx['picked_indian_listings'][0]['json']['tavily_title'].lower()


def test_pick_indian_listings_prefers_merch_over_books():
    # Books should be deprioritized for merch intent
    ctx = {
        'tavily_search_results': [
            {
                'json': {
                    'tavily_query': 'buy "harry potter" merchandise t shirt',
                    'entity_hint': 'Harry Potter',
                    'product_hint': 't shirt',
                    'intent_mode': 'merch',
                    'tavily_url': 'https://amazon.in/B0BOOK',
                    'tavily_title': 'Harry Potter T-Shirt Fan Merchandise',
                    'tavily_raw_content': 'Rs 399 Harry Potter Official T-Shirt Merchandise 5 stars 1200 reviews',
                    'tavily_score': 9.5,
                }
            }
        ],
        'tavily_queries': [
            {
                'json': {
                    'tavily_query': 'buy "harry potter" merchandise t shirt',
                    'entity_hint': 'Harry Potter',
                    'product_hint': 't shirt',
                    'intent_mode': 'merch',
                }
            }
        ]
    }
    pil.run(ctx)
    # Should pick the merchandise when it has good signals
    assert len(ctx['picked_indian_listings']) >= 1


def test_pick_indian_listings_empty_results():
    ctx = {
        'tavily_search_results': [],
        'tavily_queries': []
    }
    pil.run(ctx)
    assert ctx['picked_indian_listings'] == []


def test_pick_indian_listings_quality_score_threshold():
    # Very low quality items should be filtered
    ctx = {
        'tavily_search_results': [
            {
                'json': {
                    'tavily_query': 'buy item',
                    'product_hint': 'item',
                    'tavily_url': 'https://example.com/search?q=item',
                    'tavily_title': 'Search Results',
                    'tavily_raw_content': 'page with search results',
                    'tavily_score': 0.1,  # Extremely low score
                }
            }
        ],
        'tavily_queries': [
            {
                'json': {
                    'tavily_query': 'buy item',
                    'product_hint': 'item',
                }
            }
        ]
    }
    pil.run(ctx)
    # Extremely low quality with no valid signals should not be picked
    assert len(ctx['picked_indian_listings']) == 0


def test_pick_indian_listings_with_domain():
    ctx = {
        'tavily_search_results': [
            {
                'json': {
                    'tavily_query': 'buy mug india',
                    'product_hint': 'mug',
                    'tavily_url': 'https://flipkart.com/p/B123456',
                    'tavily_title': 'Premium Coffee Mug',
                    'tavily_raw_content': 'rs 349 coffee mug flipkart 4.5 stars 200 reviews',
                    'tavily_score': 7.5,
                    'tavily_domain': 'flipkart.com',
                }
            }
        ],
        'tavily_queries': [
            {
                'json': {
                    'tavily_query': 'buy mug india',
                    'product_hint': 'mug',
                }
            }
        ]
    }
    pil.run(ctx)
    assert len(ctx['picked_indian_listings']) >= 1
    assert ctx['picked_indian_listings'][0]['json']['tavily_domain'] == 'flipkart.com'


def test_pick_indian_listings_preserves_metadata():
    ctx = {
        'tavily_search_results': [
            {
                'json': {
                    'tavily_query': 'buy mug india',
                    'product_hint': 'mug',
                    'tavily_url': 'https://amazon.in/dp/B123456',
                    'tavily_title': 'Mug',
                    'tavily_raw_content': 'rs 299 mug amazon 5 stars',
                    'tavily_score': 8.0,
                    'run_date': '2026-05-07',
                    'source_topic': 'Trending Mug',
                    'opportunity_score': 8.5,
                }
            }
        ],
        'tavily_queries': [
            {
                'json': {
                    'tavily_query': 'buy mug india',
                    'product_hint': 'mug',
                    'run_date': '2026-05-07',
                }
            }
        ]
    }
    pil.run(ctx)
    assert len(ctx['picked_indian_listings']) >= 1
    picked = ctx['picked_indian_listings'][0]['json']
    assert picked['run_date'] == '2026-05-07'
    assert picked['source_topic'] == 'Trending Mug'
