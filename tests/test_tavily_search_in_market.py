"""Tests for el/nodes/tavily_search_in_market.py."""
from __future__ import annotations

from el.nodes import tavily_search_in_market as tsm


class FakeTavilySearchProvider:
    def __init__(self, results: list[dict] | None = None, error: Exception | None = None):
        self.results_data = results or [
            {
                'url': 'https://amazon.in/dp/B123456',
                'title': 'Trending Mug',
                'content': 'A great mug',
                'raw_content': 'A great mug for trending products',
                'score': 8.5,
            }
        ]
        self.error = error
        self.calls = []

    def search(self, query: str, **kwargs) -> dict:
        self.calls.append(('search', query, kwargs))
        if self.error:
            raise self.error
        return {
            'ok': True,
            'query': query,
            'results': self.results_data,
            'answer': 'Test answer',
        }


def test_tavily_search_success():
    fake = FakeTavilySearchProvider()
    ctx = {
        'tavily_queries': [
            {
                'json': {
                    'tavily_query': 'buy mug india',
                    'product_hint': 'mug',
                }
            }
        ]
    }
    tsm.run(ctx, provider=fake)
    assert 'tavily_search_results' in ctx
    assert len(ctx['tavily_search_results']) == 1
    assert ctx['tavily_search_results'][0]['json']['ok'] is True
    assert ctx['tavily_search_results'][0]['json']['tavily_url'] == 'https://amazon.in/dp/B123456'


def test_tavily_search_multiple_results():
    fake = FakeTavilySearchProvider(results=[
        {'url': 'https://amazon.in/dp/A', 'title': 'Mug 1', 'score': 8.0},
        {'url': 'https://amazon.in/dp/B', 'title': 'Mug 2', 'score': 7.5},
    ])
    ctx = {
        'tavily_queries': [
            {
                'json': {
                    'tavily_query': 'buy mug india',
                    'product_hint': 'mug',
                }
            }
        ]
    }
    tsm.run(ctx, provider=fake)
    assert len(ctx['tavily_search_results']) == 2
    assert ctx['tavily_search_results'][0]['json']['tavily_url'] == 'https://amazon.in/dp/A'
    assert ctx['tavily_search_results'][1]['json']['tavily_url'] == 'https://amazon.in/dp/B'


def test_tavily_search_missing_query():
    fake = FakeTavilySearchProvider()
    ctx = {
        'tavily_queries': [
            {
                'json': {
                    'tavily_query': '',
                    'product_hint': 'mug',
                }
            }
        ]
    }
    tsm.run(ctx, provider=fake)
    assert len(ctx['tavily_search_results']) == 1
    assert ctx['tavily_search_results'][0]['json'].get('error') == 'Missing tavily_query'


def test_tavily_search_provider_error():
    fake = FakeTavilySearchProvider(error=RuntimeError('API error'))
    ctx = {
        'tavily_queries': [
            {
                'json': {
                    'tavily_query': 'buy mug india',
                    'product_hint': 'mug',
                }
            }
        ]
    }
    tsm.run(ctx, provider=fake)
    assert len(ctx['tavily_search_results']) == 1
    assert ctx['tavily_search_results'][0]['json']['ok'] is False
    assert 'API error' in ctx['tavily_search_results'][0]['json']['error']


def test_tavily_search_empty_queries():
    fake = FakeTavilySearchProvider()
    ctx = {
        'tavily_queries': []
    }
    tsm.run(ctx, provider=fake)
    assert ctx['tavily_search_results'] == []


def test_tavily_search_no_provider():
    ctx = {
        'tavily_queries': [
            {
                'json': {
                    'tavily_query': 'buy mug india',
                }
            }
        ]
    }
    # Without provider and without TAVILY_API_KEY env var, should still return empty
    import os
    old_key = os.environ.pop('TAVILY_API_KEY', None)
    try:
        tsm.run(ctx, provider=None)
        assert ctx['tavily_search_results'] == []
    finally:
        if old_key:
            os.environ['TAVILY_API_KEY'] = old_key


def test_tavily_search_preserves_metadata():
    fake = FakeTavilySearchProvider()
    ctx = {
        'tavily_queries': [
            {
                'json': {
                    'tavily_query': 'buy mug india',
                    'product_hint': 'mug',
                    'entity_hint': 'trending',
                    'source_topic': 'Trending Mug',
                    'run_date': '2026-05-07',
                }
            }
        ]
    }
    tsm.run(ctx, provider=fake)
    assert len(ctx['tavily_search_results']) == 1
    result = ctx['tavily_search_results'][0]['json']
    assert result['entity_hint'] == 'trending'
    assert result['source_topic'] == 'Trending Mug'
    assert result['run_date'] == '2026-05-07'
