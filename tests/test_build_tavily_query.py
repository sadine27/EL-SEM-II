"""Tests for el/nodes/build_tavily_query.py."""
from __future__ import annotations

from el.nodes import build_tavily_query as btq


def test_build_tavily_query_simple_product():
    ctx = {
        'ranked_payload': [
            {
                'json': {
                    'search_query_in': 'trending phone case',
                    'topic': 'Trending Phone Case',
                    'rank': 1,
                }
            }
        ]
    }
    btq.run(ctx)
    assert 'tavily_queries' in ctx
    assert len(ctx['tavily_queries']) == 1
    assert ctx['tavily_queries'][0]['json']['tavily_query'].lower().startswith('buy')
    assert 'india' in ctx['tavily_queries'][0]['json']['tavily_query'].lower()


def test_build_tavily_query_merchandise():
    ctx = {
        'ranked_payload': [
            {
                'json': {
                    'search_query_in': 'trending marvel poster',
                    'topic': 'Marvel Poster',
                    'suggested_product_type': 'poster',
                    'rank': 1,
                }
            }
        ]
    }
    btq.run(ctx)
    assert len(ctx['tavily_queries']) == 1
    query = ctx['tavily_queries'][0]['json']
    assert query['intent_mode'] == 'merch'
    assert 'merchandise' in query['tavily_query'].lower() or 'poster' in query['tavily_query'].lower()


def test_build_tavily_query_skips_on_error():
    ctx = {
        'ranked_payload': [
            {
                'json': {
                    'error': 'Some error',
                    'topic': 'Should skip',
                }
            }
        ]
    }
    btq.run(ctx)
    assert len(ctx['tavily_queries']) == 0


def test_build_tavily_query_empty_payload():
    ctx = {
        'ranked_payload': []
    }
    btq.run(ctx)
    assert ctx['tavily_queries'] == []


def test_build_tavily_query_preserves_metadata():
    ctx = {
        'ranked_payload': [
            {
                'json': {
                    'search_query_in': 'trending t-shirt',
                    'topic': 'Trending TShirt',
                    'run_date': '2026-05-07',
                    'opportunity_score': 8.5,
                    'suggested_product_type': 't shirt',
                }
            }
        ]
    }
    btq.run(ctx)
    assert len(ctx['tavily_queries']) == 1
    query = ctx['tavily_queries'][0]['json']
    assert query['run_date'] == '2026-05-07'
    assert query['opportunity_score'] == 8.5
    assert query['source_topic'] == 'Trending TShirt'


def test_build_tavily_query_multiple_items():
    ctx = {
        'ranked_payload': [
            {
                'json': {
                    'search_query_in': 'trending mug',
                    'topic': 'Mug',
                    'rank': 1,
                }
            },
            {
                'json': {
                    'search_query_in': 'trending sticker',
                    'topic': 'Sticker',
                    'rank': 2,
                }
            }
        ]
    }
    btq.run(ctx)
    assert len(ctx['tavily_queries']) == 2
    assert 'mug' in ctx['tavily_queries'][0]['json']['tavily_query'].lower()
    assert 'sticker' in ctx['tavily_queries'][1]['json']['tavily_query'].lower()
