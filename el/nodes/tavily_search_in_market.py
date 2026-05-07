"""Tavily search for products in Indian market."""
from __future__ import annotations

from el.tavily import TavilySearchProvider


def run(ctx: dict, *, provider: TavilySearchProvider | None = None) -> dict:
    """Execute Tavily searches for each generated query.

    Input: ctx["tavily_queries"] (list of query items from Build Tavily Query)
    Output: ctx["tavily_search_results"] (list of search result items)
    """
    if provider is None:
        try:
            provider = TavilySearchProvider()
        except Exception:
            ctx['tavily_search_results'] = []
            return ctx

    queries = ctx.get('tavily_queries', [])
    results = []

    for item in queries:
        if isinstance(item, dict):
            j = item.get('json', item)
        else:
            j = getattr(item, 'json', item)
        if not isinstance(j, dict):
            continue
        tavily_query = (j.get('tavily_query') or '').strip()

        if not tavily_query:
            results.append({'json': {**j, 'error': 'Missing tavily_query'}})
            continue

        try:
            search_result = provider.search(tavily_query, max_results=10)
        except Exception as e:
            results.append({
                'json': {
                    **j,
                    'ok': False,
                    'error': str(e),
                }
            })
            continue

        if not isinstance(search_result, dict):
            results.append({'json': {**j, 'ok': False, 'error': 'Tavily search failed'}})
            continue

        if not search_result.get('ok'):
            results.append({
                'json': {
                    **j,
                    'ok': False,
                    'error': search_result.get('error', 'Tavily search failed'),
                }
            })
            continue

        # Return search results paired with original query metadata
        search_results = search_result.get('results', [])
        if not isinstance(search_results, list):
            search_results = []
        for result in search_results:
            if not isinstance(result, dict):
                continue
            result_item = {**j}  # Copy all metadata from query
            result_item.update({
                'ok': True,
                'tavily_url': result.get('url'),
                'tavily_title': result.get('title'),
                'tavily_raw_content': result.get('raw_content') or result.get('content'),
                'tavily_score': result.get('score'),
            })
            results.append({'json': result_item})

    ctx['tavily_search_results'] = results
    return ctx
