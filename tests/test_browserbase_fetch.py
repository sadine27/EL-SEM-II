"""Tests for el/nodes/browserbase_fetch.py."""
from __future__ import annotations

from el.nodes import browserbase_fetch as bbf


class FakeBrowserbaseProvider:
    """Fake Browserbase provider for testing."""

    def __init__(self, responses: dict | None = None, should_error: bool = False):
        self.responses = responses or {}
        self.should_error = should_error
        self.calls = []

    def fetch(self, url: str, allow_redirects: bool = True, proxies: bool = True) -> dict:
        self.calls.append({'url': url, 'allow_redirects': allow_redirects, 'proxies': proxies})
        if self.should_error:
            raise Exception("Browserbase API error")
        return self.responses.get(url, {'ok': False, 'error': f'No response for {url}'})


def test_fetches_and_preserves_metadata():
    provider = FakeBrowserbaseProvider(
        responses={
            'https://amazon.in/dp/A': {
                'ok': True,
                'content': '<p>Product details here</p>',
                'statusCode': 200,
            }
        }
    )
    ctx = {
        'thin_content_for_browserbase': [
            {
                'json': {
                    'tavily_url': 'https://amazon.in/dp/A',
                    'entity_hint': 'Marvel',
                    'product_hint': 'poster',
                }
            }
        ]
    }
    bbf.run(ctx, provider=provider)
    result = ctx['browserbase_results'][0]['json']
    assert result['ok'] is True
    assert '<p>' in result['content']
    assert result['entity_hint'] == 'Marvel'
    assert result['browserbase_status_code'] == 200


def test_handles_provider_errors():
    provider = FakeBrowserbaseProvider(should_error=True)
    ctx = {
        'thin_content_for_browserbase': [
            {'json': {'tavily_url': 'https://example.com'}}
        ]
    }
    bbf.run(ctx, provider=provider)
    result = ctx['browserbase_results'][0]['json']
    assert result['ok'] is False
    assert 'error' in result


def test_skips_missing_url():
    ctx = {
        'thin_content_for_browserbase': [
            {'json': {'entity_hint': 'test'}}
        ]
    }
    bbf.run(ctx, provider=FakeBrowserbaseProvider())
    result = ctx['browserbase_results'][0]['json']
    assert result['error'] == 'Missing tavily_url'


def test_returns_empty_when_no_provider_and_no_credentials():
    ctx = {'thin_content_for_browserbase': []}
    result = bbf.run(ctx, provider=None)
    assert result['browserbase_results'] == []


def test_multiple_fetches():
    provider = FakeBrowserbaseProvider(
        responses={
            'https://amazon.in/dp/A': {'ok': True, 'content': 'Product A', 'statusCode': 200},
            'https://flipkart.com/p/B': {'ok': True, 'content': 'Product B', 'statusCode': 200},
        }
    )
    ctx = {
        'thin_content_for_browserbase': [
            {'json': {'tavily_url': 'https://amazon.in/dp/A'}},
            {'json': {'tavily_url': 'https://flipkart.com/p/B'}},
        ]
    }
    bbf.run(ctx, provider=provider)
    assert len(ctx['browserbase_results']) == 2
    assert 'Product A' in ctx['browserbase_results'][0]['json']['content']
    assert 'Product B' in ctx['browserbase_results'][1]['json']['content']


def test_api_error_response():
    provider = FakeBrowserbaseProvider(
        responses={
            'https://example.com': {'ok': False, 'error': 'Rate limited', 'statusCode': 429}
        }
    )
    ctx = {
        'thin_content_for_browserbase': [
            {'json': {'tavily_url': 'https://example.com'}}
        ]
    }
    bbf.run(ctx, provider=provider)
    result = ctx['browserbase_results'][0]['json']
    assert result['ok'] is False
    assert 'Rate limited' in result['error']


def test_preserves_all_metadata_fields():
    provider = FakeBrowserbaseProvider(
        responses={
            'https://example.com': {'ok': True, 'content': 'content', 'statusCode': 200}
        }
    )
    ctx = {
        'thin_content_for_browserbase': [
            {
                'json': {
                    'tavily_url': 'https://example.com',
                    'source_topic': 'trending',
                    'source_pick_rank': 1,
                    'tavily_score': 8.5,
                    'run_date': '2026-05-07',
                }
            }
        ]
    }
    bbf.run(ctx, provider=provider)
    result = ctx['browserbase_results'][0]['json']
    assert result['source_topic'] == 'trending'
    assert result['source_pick_rank'] == 1
    assert result['tavily_score'] == 8.5
    assert result['run_date'] == '2026-05-07'
