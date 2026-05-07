"""Tests for el/nodes/strip_html.py."""
from __future__ import annotations

from el.nodes import strip_html


def test_removes_html_tags():
    ctx = {
        'browserbase_results': [
            {
                'json': {
                    'content': '<p>Price: Rs 299</p><p>Rating: 5 stars</p>',
                    'tavily_url': 'https://amazon.in/dp/A',
                }
            }
        ]
    }
    strip_html.run(ctx)
    result = ctx['stripped_content'][0]['json']
    assert 'Rs 299' in result['tavily_raw_content']
    assert '<p>' not in result['tavily_raw_content']


def test_removes_scripts_and_styles():
    ctx = {
        'browserbase_results': [
            {
                'json': {
                    'content': '<script>var x=1;</script><p>Price: Rs 100</p><style>body{color:red;}</style>',
                }
            }
        ]
    }
    strip_html.run(ctx)
    result = ctx['stripped_content'][0]['json']
    assert 'var x=1' not in result['tavily_raw_content']
    assert 'body{color:red}' not in result['tavily_raw_content']


def test_removes_html_comments():
    ctx = {
        'browserbase_results': [
            {
                'json': {
                    'content': '<!-- tracking pixel --><p>Product Name</p><!-- comment -->',
                }
            }
        ]
    }
    strip_html.run(ctx)
    result = ctx['stripped_content'][0]['json']
    assert 'tracking pixel' not in result['tavily_raw_content']
    assert 'Product Name' in result['tavily_raw_content']


def test_collapses_whitespace():
    ctx = {
        'browserbase_results': [
            {
                'json': {
                    'content': '<p>Price:   Rs   299</p>\n\n<p>Rating:   5   stars</p>',
                }
            }
        ]
    }
    strip_html.run(ctx)
    result = ctx['stripped_content'][0]['json']
    assert 'Rs   299' not in result['tavily_raw_content']
    assert 'Rs 299' in result['tavily_raw_content']


def test_truncates_at_60000_chars():
    large_content = 'A' * 70000
    ctx = {
        'browserbase_results': [
            {'json': {'content': f'<p>{large_content}</p>'}}
        ]
    }
    strip_html.run(ctx)
    result = ctx['stripped_content'][0]['json']
    assert len(result['tavily_raw_content']) <= 60000


def test_sets_browserbase_used_flag():
    ctx = {
        'browserbase_results': [
            {'json': {'content': '<p>Test</p>'}}
        ]
    }
    strip_html.run(ctx)
    result = ctx['stripped_content'][0]['json']
    assert result['browserbase_used'] is True


def test_preserves_metadata():
    ctx = {
        'browserbase_results': [
            {
                'json': {
                    'content': '<p>Test</p>',
                    'entity_hint': 'Marvel',
                    'product_hint': 'poster',
                    'source_topic': 'trending',
                }
            }
        ]
    }
    strip_html.run(ctx)
    result = ctx['stripped_content'][0]['json']
    assert result['entity_hint'] == 'Marvel'
    assert result['product_hint'] == 'poster'


def test_falls_back_to_tavily_raw_content():
    ctx = {
        'browserbase_results': [
            {
                'json': {
                    'tavily_raw_content': 'Already cleaned text',
                    'tavily_url': 'https://example.com',
                }
            }
        ]
    }
    strip_html.run(ctx)
    result = ctx['stripped_content'][0]['json']
    assert result['tavily_raw_content'] == 'Already cleaned text'
