"""Tests for el/nodes/if_tavily_content_thin.py."""
from __future__ import annotations

from el.nodes import if_tavily_content_thin as icft


def test_splits_by_content_length_threshold():
    ctx = {
        'picked_indian_listings': [
            {'json': {'tavily_url': 'https://amazon.in/dp/A', 'tavily_content_len': 100}},
            {'json': {'tavily_url': 'https://amazon.in/dp/B', 'tavily_content_len': 600}},
            {'json': {'tavily_url': 'https://amazon.in/dp/C', 'tavily_content_len': 499}},
        ]
    }
    icft.run(ctx)
    assert len(ctx['thin_content_for_browserbase']) == 2
    assert len(ctx['thick_content_fallback']) == 1
    assert ctx['thick_content_fallback'][0]['json']['tavily_url'] == 'https://amazon.in/dp/B'


def test_handles_missing_content_len():
    ctx = {
        'picked_indian_listings': [
            {'json': {'tavily_url': 'https://amazon.in/dp/A'}},  # No content_len
            {'json': {'tavily_url': 'https://amazon.in/dp/B', 'tavily_content_len': 600}},
        ]
    }
    icft.run(ctx)
    assert len(ctx['thin_content_for_browserbase']) == 1
    assert len(ctx['thick_content_fallback']) == 1


def test_preserves_all_metadata():
    ctx = {
        'picked_indian_listings': [
            {
                'json': {
                    'tavily_url': 'https://amazon.in/dp/A',
                    'tavily_content_len': 100,
                    'entity_hint': 'Marvel',
                    'product_hint': 't shirt',
                    'source_topic': 'trending',
                }
            }
        ]
    }
    icft.run(ctx)
    picked = ctx['thin_content_for_browserbase'][0]['json']
    assert picked['entity_hint'] == 'Marvel'
    assert picked['product_hint'] == 't shirt'
    assert picked['source_topic'] == 'trending'


def test_empty_listings():
    ctx = {'picked_indian_listings': []}
    icft.run(ctx)
    assert ctx['thin_content_for_browserbase'] == []
    assert ctx['thick_content_fallback'] == []


def test_boundary_exactly_500():
    ctx = {
        'picked_indian_listings': [
            {'json': {'tavily_content_len': 500}},
            {'json': {'tavily_content_len': 499}},
        ]
    }
    icft.run(ctx)
    assert len(ctx['thin_content_for_browserbase']) == 1
    assert len(ctx['thick_content_fallback']) == 1
