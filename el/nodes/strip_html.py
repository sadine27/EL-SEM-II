"""Strip HTML tags and clean content from Browserbase fetch."""
from __future__ import annotations

import re


def run(ctx: dict) -> dict:
    """Clean HTML content from Browserbase API response.

    Input: ctx["browserbase_results"] (raw Browserbase fetch results with HTML content)
    Output: ctx["stripped_content"] (cleaned text content)
    """
    results = ctx.get('browserbase_results', [])
    out = []

    for item in results:
        if isinstance(item, dict):
            j = item.get('json', item)
        else:
            j = getattr(item, 'json', item)

        # Get HTML from Browserbase response
        html = str(j.get('content') or j.get('tavily_raw_content') or '')

        # Strip script, style, comments, noscript tags
        cleaned = re.sub(r'<script[^>]*>[\s\S]*?</script>', ' ', html, flags=re.IGNORECASE)
        cleaned = re.sub(r'<style[^>]*>[\s\S]*?</style>', ' ', cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r'<!--[\s\S]*?-->', ' ', cleaned)
        cleaned = re.sub(r'<noscript[^>]*>[\s\S]*?</noscript>', ' ', cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r'<[^>]+>', ' ', cleaned)
        cleaned = re.sub(r'\s+', ' ', cleaned)
        cleaned = cleaned.strip()[:60000]

        out.append({
            'json': {
                **j,
                'tavily_raw_content': cleaned,
                'tavily_content_len': len(cleaned),
                'browserbase_used': True,
            }
        })

    ctx['stripped_content'] = out
    return ctx
