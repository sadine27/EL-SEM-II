"""Tests for el/nodes/gemini_extract_product.py."""
from __future__ import annotations

from el.nodes import gemini_extract_product as gep


def fake_gemini_success(prompt: str, api_key: str | None = None, timeout: int = 60) -> dict:
    """Fake Gemini that returns product JSON."""
    return {
        'ok': True,
        'statusCode': 200,
        'candidates': [
            {
                'content': {
                    'parts': [
                        {
                            'text': '{"product_name": "Marvel T-Shirt", "price_inr": 299, "rating": 4.5, "image_urls": ["https://example.com/img.jpg"]}'
                        }
                    ]
                }
            }
        ],
        'text': '{"product_name": "Marvel T-Shirt"}',
    }


def fake_gemini_empty(prompt: str, api_key: str | None = None, timeout: int = 60) -> dict:
    """Fake Gemini that returns no candidates."""
    return {
        'ok': False,
        'error': 'No candidates in response',
    }


def fake_gemini_error(prompt: str, api_key: str | None = None, timeout: int = 60) -> dict:
    """Fake Gemini that fails."""
    return {
        'ok': False,
        'statusCode': 500,
        'error': 'Internal server error',
    }


def test_calls_gemini_with_prompt():
    ctx = {
        'gemini_prompts': [
            {
                'json': {
                    'gemini_prompt': 'Extract product from this page...',
                    'tavily_url': 'https://amazon.in/dp/A',
                }
            }
        ]
    }
    gep.run(ctx, gemini_fn=fake_gemini_success)
    result = ctx['gemini_extracts'][0]['json']
    assert result['ok'] is True
    assert result['gemini_status_code'] == 200
    assert len(result.get('candidates', [])) > 0


def test_skips_missing_prompt():
    ctx = {
        'gemini_prompts': [
            {
                'json': {
                    'tavily_url': 'https://amazon.in/dp/A',
                    'gemini_skipped': 'thin content',
                }
            }
        ]
    }
    gep.run(ctx, gemini_fn=fake_gemini_success)
    result = ctx['gemini_extracts'][0]['json']
    assert result['gemini_skipped'] == 'thin content'
    assert 'ok' not in result


def test_handles_gemini_error():
    ctx = {
        'gemini_prompts': [
            {
                'json': {
                    'gemini_prompt': 'Extract...',
                    'tavily_url': 'https://example.com',
                }
            }
        ]
    }
    gep.run(ctx, gemini_fn=fake_gemini_error)
    result = ctx['gemini_extracts'][0]['json']
    assert result['ok'] is False
    assert result['gemini_status_code'] == 500
    assert 'Internal server error' in result['error']


def test_preserves_metadata():
    ctx = {
        'gemini_prompts': [
            {
                'json': {
                    'gemini_prompt': 'Extract...',
                    'entity_hint': 'Marvel',
                    'product_hint': 't shirt',
                    'source_topic': 'trending',
                    'tavily_url': 'https://amazon.in/dp/A',
                }
            }
        ]
    }
    gep.run(ctx, gemini_fn=fake_gemini_success)
    result = ctx['gemini_extracts'][0]['json']
    assert result['entity_hint'] == 'Marvel'
    assert result['product_hint'] == 't shirt'
    assert result['source_topic'] == 'trending'


def test_handles_gemini_exception():
    def gemini_raises(prompt: str, api_key: str | None = None, timeout: int = 60) -> dict:
        raise Exception("Connection failed")

    ctx = {
        'gemini_prompts': [
            {'json': {'gemini_prompt': 'Extract...', 'tavily_url': 'https://example.com'}}
        ]
    }
    gep.run(ctx, gemini_fn=gemini_raises)
    result = ctx['gemini_extracts'][0]['json']
    assert result['ok'] is False
    assert 'Connection failed' in result['error']


def test_multiple_extracts():
    def gemini_multi(prompt: str, api_key: str | None = None, timeout: int = 60) -> dict:
        if 'Marvel' in prompt:
            return {
                'ok': True,
                'statusCode': 200,
                'candidates': [{'content': {'parts': [{'text': '{"product_name": "Marvel"}'}]}}],
                'text': '{"product_name": "Marvel"}',
            }
        else:
            return {
                'ok': True,
                'statusCode': 200,
                'candidates': [{'content': {'parts': [{'text': '{"product_name": "DC"}'}]}}],
                'text': '{"product_name": "DC"}',
            }

    ctx = {
        'gemini_prompts': [
            {'json': {'gemini_prompt': 'Extract Marvel...', 'entity_hint': 'Marvel'}},
            {'json': {'gemini_prompt': 'Extract DC...', 'entity_hint': 'DC'}},
        ]
    }
    gep.run(ctx, gemini_fn=gemini_multi)
    assert len(ctx['gemini_extracts']) == 2
    assert ctx['gemini_extracts'][0]['json']['ok'] is True
    assert ctx['gemini_extracts'][1]['json']['ok'] is True


def test_empty_prompts():
    ctx = {'gemini_prompts': []}
    gep.run(ctx, gemini_fn=fake_gemini_success)
    assert ctx['gemini_extracts'] == []
