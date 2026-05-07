"""Conditional: skip if Tavily content length is < 500 chars."""
from __future__ import annotations


def run(ctx: dict) -> dict:
    """Filter listings with thin Tavily content for Browserbase fallback.

    Input: ctx["picked_indian_listings"] (listings from Pick Indian Listings)
    Output: ctx["thin_content_for_browserbase"] (items where tavily_content_len < 500)
            ctx["thick_content_fallback"] (items where tavily_content_len >= 500, sent to Prepare Sheet Rows)
    """
    listings = ctx.get('picked_indian_listings', [])
    thin = []
    thick = []

    for item in listings:
        if isinstance(item, dict):
            j = item.get('json', item)
        else:
            j = getattr(item, 'json', item)
        if not isinstance(j, dict):
            continue

        try:
            content_len = int(j.get('tavily_content_len') or 0)
        except (TypeError, ValueError):
            content_len = 0
        if content_len < 500:
            thin.append(item)
        else:
            thick.append(item)

    ctx['thin_content_for_browserbase'] = thin
    ctx['thick_content_fallback'] = thick
    return ctx
