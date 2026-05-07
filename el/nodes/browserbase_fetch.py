"""Fetch marketplace page content via Browserbase API."""
from __future__ import annotations

from el.browserbase import BrowserbaseProvider


def run(ctx: dict, *, provider: BrowserbaseProvider | None = None) -> dict:
    """Execute Browserbase fetch for URLs with thin Tavily content.

    Input: ctx["thin_content_for_browserbase"] (URLs to fetch)
    Output: ctx["browserbase_results"] (fetched content items)
    """
    if provider is None:
        try:
            provider = BrowserbaseProvider()
        except Exception:
            ctx['browserbase_results'] = []
            return ctx

    items = ctx.get('thin_content_for_browserbase', [])
    results = []

    for item in items:
        if isinstance(item, dict):
            j = item.get('json', item)
        else:
            j = getattr(item, 'json', item)

        url = j.get('tavily_url') or ''
        if not url:
            results.append({'json': {**j, 'error': 'Missing tavily_url'}})
            continue

        try:
            fetch_result = provider.fetch(url, allow_redirects=True, proxies=True)
        except Exception as e:
            results.append({
                'json': {
                    **j,
                    'ok': False,
                    'error': str(e),
                }
            })
            continue

        if not fetch_result.get('ok'):
            results.append({
                'json': {
                    **j,
                    'ok': False,
                    'error': fetch_result.get('error', 'Browserbase fetch failed'),
                }
            })
            continue

        result_item = {**j}
        result_item.update({
            'ok': True,
            'content': fetch_result.get('content', ''),
            'browserbase_status_code': fetch_result.get('statusCode', 200),
        })
        results.append({'json': result_item})

    ctx['browserbase_results'] = results
    return ctx
