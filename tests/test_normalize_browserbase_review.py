"""Tests for el/nodes/normalize_browserbase_review.py."""
from __future__ import annotations

import json

from el.nodes import normalize_browserbase_review as nbr


def test_builds_hil_review_schema():
    ctx = {
        'gemini_extracts': [
            {
                'json': {
                    'candidates': [
                        {
                            'content': {
                                'parts': [
                                    {
                                        'text': '{"product_name": "Marvel T-Shirt", "price_inr": 299, "rating": 4.5, "image_urls": ["https://example.com/img.jpg"], "is_product_page": true}'
                                    }
                                ]
                            }
                        }
                    ],
                    'tavily_url': 'https://amazon.in/dp/B0ABC',
                    'tavily_title': 'Marvel T-Shirt',
                    'tavily_raw_content': 'Price: Rs 299. Rating: 4.5 stars. Available.',
                    'source_topic': 'Marvel Merchandise',
                    'run_date': '2026-05-07',
                }
            }
        ],
        'gemini_prompts': [
            {
                'json': {
                    'tavily_url': 'https://amazon.in/dp/B0ABC',
                    'source_topic': 'Marvel Merchandise',
                    'run_date': '2026-05-07',
                    'tavily_is_likely_product_page': True,
                    'tavily_raw_content': 'Price: Rs 299. Rating: 4.5 stars. Available.',
                }
            }
        ],
    }
    nbr.run(ctx)
    assert len(ctx['normalized_reviews']) >= 1
    review = ctx['normalized_reviews'][0]['json']
    assert review['product_name'] == 'Marvel T-Shirt'
    assert review['price_numeric'] == 299
    assert review['product_rating'] == 4.5
    assert review['review_schema_version'] == 'hil_v1'
    assert review['workflow_name'] == 'EL'


def test_filters_missing_product_name():
    ctx = {
        'gemini_extracts': [
            {
                'json': {
                    'candidates': [
                        {
                            'content': {
                                'parts': [
                                    {'text': '{"price_inr": 299}'}
                                ]
                            }
                        }
                    ],
                    'tavily_url': 'https://amazon.in/dp/A',
                    'tavily_title': '',
                    'tavily_raw_content': 'Some content',
                    'source_topic': 'test',
                }
            }
        ],
        'gemini_prompts': [
            {'json': {'tavily_url': 'https://amazon.in/dp/A', 'source_topic': 'test'}}
        ],
    }
    nbr.run(ctx)
    assert len(ctx['normalized_reviews']) == 0


def test_filters_404_titles():
    ctx = {
        'gemini_extracts': [
            {
                'json': {
                    'candidates': [
                        {
                            'content': {
                                'parts': [
                                    {'text': '{"product_name": "404 Not Found"}'}
                                ]
                            }
                        }
                    ],
                    'tavily_url': 'https://amazon.in/dp/A',
                    'tavily_title': '404 Not Found',
                    'tavily_raw_content': 'content',
                    'source_topic': 'test',
                }
            }
        ],
        'gemini_prompts': [{'json': {'tavily_url': 'https://amazon.in/dp/A', 'source_topic': 'test'}}],
    }
    nbr.run(ctx)
    assert len(ctx['normalized_reviews']) == 0


def test_filters_books_for_merch_intent():
    ctx = {
        'gemini_extracts': [
            {
                'json': {
                    'candidates': [
                        {
                            'content': {
                                'parts': [
                                    {'text': '{"product_name": "Harry Potter Book"}'}
                                ]
                            }
                        }
                    ],
                    'tavily_url': 'https://amazon.in/dp/A',
                    'tavily_title': 'Harry Potter Novel',
                    'tavily_raw_content': 'Paperback book for sale',
                    'tavily_query': 'buy Harry Potter merchandise',
                    'intent_mode': 'merch',
                    'source_topic': 'test',
                }
            }
        ],
        'gemini_prompts': [{'json': {'tavily_url': 'https://amazon.in/dp/A', 'source_topic': 'test'}}],
    }
    nbr.run(ctx)
    assert len(ctx['normalized_reviews']) == 0


def test_requires_price_or_image_for_validity():
    ctx = {
        'gemini_extracts': [
            {
                'json': {
                    'candidates': [
                        {
                            'content': {
                                'parts': [
                                    {'text': '{"product_name": "Item", "price_inr": 299, "is_product_page": true}'}
                                ]
                            }
                        }
                    ],
                    'tavily_url': 'https://amazon.in/dp/B0ABC',
                    'tavily_title': 'Item',
                    'tavily_raw_content': 'Rs 299',
                    'source_topic': 'test',
                }
            }
        ],
        'gemini_prompts': [
            {
                'json': {
                    'tavily_url': 'https://amazon.in/dp/B0ABC',
                    'source_topic': 'test',
                    'tavily_is_likely_product_page': True,
                    'tavily_raw_content': 'Rs 299',
                }
            }
        ],
    }
    nbr.run(ctx)
    assert len(ctx['normalized_reviews']) == 1


def test_filters_very_low_prices():
    ctx = {
        'gemini_extracts': [
            {
                'json': {
                    'candidates': [
                        {
                            'content': {
                                'parts': [
                                    {'text': '{"product_name": "Item", "price_inr": 5}'}
                                ]
                            }
                        }
                    ],
                    'tavily_url': 'https://amazon.in/dp/A',
                    'tavily_title': 'Item',
                    'tavily_raw_content': 'Rs 5',
                    'image_urls': ['https://example.com/img.jpg'],
                    'source_topic': 'test',
                }
            }
        ],
        'gemini_prompts': [{'json': {'tavily_url': 'https://amazon.in/dp/A', 'source_topic': 'test'}}],
    }
    nbr.run(ctx)
    assert len(ctx['normalized_reviews']) == 0


def test_detects_price_from_fallback_text():
    ctx = {
        'gemini_extracts': [
            {
                'json': {
                    'candidates': [
                        {
                            'content': {
                                'parts': [
                                    {'text': '{"product_name": "Item", "is_product_page": true}'}
                                ]
                            }
                        }
                    ],
                    'tavily_url': 'https://amazon.in/dp/B0ABC',
                    'tavily_title': 'Item',
                    'tavily_raw_content': 'Rs 299 price available here for purchase with discount',
                    'source_topic': 'test',
                }
            }
        ],
        'gemini_prompts': [
            {
                'json': {
                    'tavily_url': 'https://amazon.in/dp/B0ABC',
                    'source_topic': 'test',
                    'tavily_is_likely_product_page': True,
                    'tavily_raw_content': 'Rs 299 price available here for purchase with discount',
                }
            }
        ],
    }
    nbr.run(ctx)
    assert len(ctx['normalized_reviews']) == 1
    assert ctx['normalized_reviews'][0]['json']['price_text'] == 'Rs 299'


def test_detects_rating_from_fallback_text():
    ctx = {
        'gemini_extracts': [
            {
                'json': {
                    'candidates': [
                        {
                            'content': {
                                'parts': [
                                    {'text': '{"product_name": "Item", "is_product_page": true}'}
                                ]
                            }
                        }
                    ],
                    'tavily_url': 'https://amazon.in/dp/B0ABC',
                    'tavily_title': 'Item',
                    'tavily_raw_content': 'Rs 299, rated 4.5 out of 5 stars available now in stock',
                    'source_topic': 'test',
                }
            }
        ],
        'gemini_prompts': [
            {
                'json': {
                    'tavily_url': 'https://amazon.in/dp/B0ABC',
                    'source_topic': 'test',
                    'tavily_is_likely_product_page': True,
                    'tavily_raw_content': 'Rs 299, rated 4.5 out of 5 stars available now in stock',
                }
            }
        ],
    }
    nbr.run(ctx)
    review = ctx['normalized_reviews'][0]['json']
    assert review['product_rating'] == 4.5


def test_detects_reviews_count_from_text():
    ctx = {
        'gemini_extracts': [
            {
                'json': {
                    'candidates': [
                        {
                            'content': {
                                'parts': [
                                    {'text': '{"product_name": "Item", "is_product_page": true}'}
                                ]
                            }
                        }
                    ],
                    'tavily_url': 'https://amazon.in/dp/B0ABC',
                    'tavily_title': 'Item',
                    'tavily_raw_content': 'Rs 299, 150 reviews, 4.5 stars available for order now',
                    'source_topic': 'test',
                }
            }
        ],
        'gemini_prompts': [
            {
                'json': {
                    'tavily_url': 'https://amazon.in/dp/B0ABC',
                    'source_topic': 'test',
                    'tavily_is_likely_product_page': True,
                    'tavily_raw_content': 'Rs 299, 150 reviews, 4.5 stars available for order now',
                }
            }
        ],
    }
    nbr.run(ctx)
    review = ctx['normalized_reviews'][0]['json']
    assert review['reviews_count'] == 150


def test_filters_usable_image_urls():
    ctx = {
        'gemini_extracts': [
            {
                'json': {
                    'candidates': [
                        {
                            'content': {
                                'parts': [
                                    {
                                        'text': '{"product_name": "Item", "image_urls": ["https://example.com/logo.gif", "https://example.com/product.jpg"]}'
                                    }
                                ]
                            }
                        }
                    ],
                    'tavily_url': 'https://amazon.in/dp/A',
                    'tavily_title': 'Item',
                    'tavily_raw_content': 'Rs 299',
                    'source_topic': 'test',
                }
            }
        ],
        'gemini_prompts': [{'json': {'tavily_url': 'https://amazon.in/dp/A', 'source_topic': 'test'}}],
    }
    nbr.run(ctx)
    review = ctx['normalized_reviews'][0]['json']
    assert review['image_url'] == 'https://example.com/product.jpg'


def test_merch_intent_requires_product_match():
    ctx = {
        'gemini_extracts': [
            {
                'json': {
                    'candidates': [
                        {
                            'content': {
                                'parts': [
                                    {'text': '{"product_name": "Random Item"}'}
                                ]
                            }
                        }
                    ],
                    'tavily_url': 'https://amazon.in/dp/A',
                    'tavily_title': 'Item',
                    'tavily_raw_content': 'Rs 299',
                    'image_urls': ['https://example.com/img.jpg'],
                    'tavily_query': 'buy Marvel merchandise t shirt',
                    'intent_mode': 'merch',
                    'product_hint': 't shirt',
                    'entity_hint': 'Marvel',
                    'source_topic': 'test',
                }
            }
        ],
        'gemini_prompts': [{'json': {'tavily_url': 'https://amazon.in/dp/A', 'source_topic': 'test'}}],
    }
    nbr.run(ctx)
    assert len(ctx['normalized_reviews']) == 0


def test_preserves_raw_payload():
    ctx = {
        'gemini_extracts': [
            {
                'json': {
                    'candidates': [
                        {
                            'content': {
                                'parts': [
                                    {'text': '{"product_name": "Item", "price_inr": 299, "is_product_page": true}'}
                                ]
                            }
                        }
                    ],
                    'tavily_url': 'https://amazon.in/dp/B0ABC',
                    'tavily_title': 'Item',
                    'tavily_raw_content': 'Rs 299 product available in multiple colors',
                    'tavily_score': 8.5,
                    'tavily_query': 'buy item',
                    'source_topic': 'test',
                }
            }
        ],
        'gemini_prompts': [
            {
                'json': {
                    'tavily_url': 'https://amazon.in/dp/B0ABC',
                    'source_topic': 'test',
                    'tavily_is_likely_product_page': True,
                    'tavily_raw_content': 'Rs 299 product available in multiple colors',
                    'tavily_score': 8.5,
                    'tavily_query': 'buy item',
                }
            }
        ],
    }
    nbr.run(ctx)
    review = ctx['normalized_reviews'][0]['json']
    payload = json.loads(review['raw_payload'])
    assert payload['tavily_score'] == 8.5
    assert payload['tavily_query'] == 'buy item'


def test_handles_missing_gemini_response():
    ctx = {
        'gemini_extracts': [
            {
                'json': {
                    'tavily_url': 'https://amazon.in/dp/A',
                    'tavily_title': 'Item',
                    'tavily_raw_content': 'Rs 299',
                    'source_topic': 'test',
                }
            }
        ],
        'gemini_prompts': [{'json': {'tavily_url': 'https://amazon.in/dp/A', 'source_topic': 'test'}}],
    }
    nbr.run(ctx)
    assert len(ctx['normalized_reviews']) == 0


def test_detects_availability_status():
    ctx = {
        'gemini_extracts': [
            {
                'json': {
                    'candidates': [
                        {
                            'content': {
                                'parts': [
                                    {'text': '{"product_name": "Item", "is_product_page": true}'}
                                ]
                            }
                        }
                    ],
                    'tavily_url': 'https://amazon.in/dp/B0ABC',
                    'tavily_title': 'Item',
                    'tavily_raw_content': 'Rs 299, out of stock currently unavailable now',
                    'source_topic': 'test',
                }
            }
        ],
        'gemini_prompts': [
            {
                'json': {
                    'tavily_url': 'https://amazon.in/dp/B0ABC',
                    'source_topic': 'test',
                    'tavily_is_likely_product_page': True,
                    'tavily_raw_content': 'Rs 299, out of stock currently unavailable now',
                }
            }
        ],
    }
    nbr.run(ctx)
    review = ctx['normalized_reviews'][0]['json']
    assert review['availability_status'] == 'out_of_stock'
