"""Tests for el/nodes/prepare_gemini_prompt.py."""
from __future__ import annotations

from el.nodes import prepare_gemini_prompt as pgp


def test_builds_gemini_prompt_with_url_and_content():
    ctx = {
        'stripped_content': [
            {
                'json': {
                    'tavily_url': 'https://amazon.in/dp/B0ABC123',
                    'tavily_title': 'Marvel T-Shirt',
                    'tavily_raw_content': 'Price: Rs 299. Rating: 4.5 stars. 150 reviews. Available in multiple sizes including XS, S, M, L, XL, XXL.',
                    'tavily_domain': 'amazon.in',
                }
            }
        ]
    }
    pgp.run(ctx)
    prompt = ctx['gemini_prompts'][0]['json']['gemini_prompt']
    assert 'https://amazon.in/dp/B0ABC123' in prompt
    assert 'Marvel T-Shirt' in prompt
    assert 'Price: Rs 299' in prompt
    assert 'You are extracting one product listing' in prompt


def test_includes_system_instruction():
    ctx = {
        'stripped_content': [
            {
                'json': {
                    'tavily_url': 'https://example.com',
                    'tavily_raw_content': 'Some content that is long enough to pass the minimum length check of 50 characters',
                }
            }
        ]
    }
    pgp.run(ctx)
    prompt = ctx['gemini_prompts'][0]['json']['gemini_prompt']
    assert 'product_name' in prompt
    assert 'price_text' in prompt
    assert 'is_product_page' in prompt
    assert 'reject_reason' in prompt


def test_skips_thin_content():
    ctx = {
        'stripped_content': [
            {
                'json': {
                    'tavily_url': 'https://example.com',
                    'tavily_raw_content': 'short',  # < 50 chars
                }
            }
        ]
    }
    pgp.run(ctx)
    result = ctx['gemini_prompts'][0]['json']
    assert result['gemini_prompt'] is None
    assert result['gemini_skipped'] == 'thin or missing input'


def test_skips_missing_url():
    ctx = {
        'stripped_content': [
            {
                'json': {
                    'tavily_raw_content': 'Valid content here',
                }
            }
        ]
    }
    pgp.run(ctx)
    result = ctx['gemini_prompts'][0]['json']
    assert result['gemini_prompt'] is None
    assert result['gemini_skipped'] == 'thin or missing input'


def test_detects_domain_from_url():
    ctx = {
        'stripped_content': [
            {
                'json': {
                    'tavily_url': 'https://flipkart.com/p/ABCD123',
                    'tavily_raw_content': 'Content here with enough text to pass the minimum length check definitely',
                }
            }
        ]
    }
    pgp.run(ctx)
    prompt = ctx['gemini_prompts'][0]['json']['gemini_prompt']
    assert 'flipkart.com' in prompt


def test_uses_tavily_domain_when_provided():
    ctx = {
        'stripped_content': [
            {
                'json': {
                    'tavily_url': 'https://example.com/page',
                    'tavily_domain': 'amazon.in',
                    'tavily_raw_content': 'Content here that is long enough to pass minimum character requirements',
                }
            }
        ]
    }
    pgp.run(ctx)
    prompt = ctx['gemini_prompts'][0]['json']['gemini_prompt']
    assert 'amazon.in' in prompt


def test_preserves_metadata():
    ctx = {
        'stripped_content': [
            {
                'json': {
                    'tavily_url': 'https://example.com',
                    'tavily_raw_content': 'Content',
                    'entity_hint': 'Marvel',
                    'product_hint': 'poster',
                    'source_topic': 'trending',
                }
            }
        ]
    }
    pgp.run(ctx)
    result = ctx['gemini_prompts'][0]['json']
    assert result['entity_hint'] == 'Marvel'
    assert result['product_hint'] == 'poster'
    assert result['source_topic'] == 'trending'


def test_truncates_content_at_60000():
    large_content = 'A' * 70000
    ctx = {
        'stripped_content': [
            {
                'json': {
                    'tavily_url': 'https://example.com',
                    'tavily_raw_content': large_content,
                }
            }
        ]
    }
    pgp.run(ctx)
    prompt = ctx['gemini_prompts'][0]['json']['gemini_prompt']
    assert len(prompt) < 70000 + 500  # Content + system instruction overhead
