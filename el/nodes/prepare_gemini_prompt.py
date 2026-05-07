"""Prepare Gemini extraction prompt from cleaned content."""
from __future__ import annotations

from urllib.parse import urlparse


def run(ctx: dict) -> dict:
    """Build system prompt and marketplace page content for Gemini extraction.

    Input: ctx["stripped_content"] (cleaned HTML text from Browserbase)
    Output: ctx["gemini_prompts"] (items with gemini_prompt field ready for extraction)
    """
    SYSTEM = (
        "You are extracting one product listing from an Indian marketplace page. "
        "Return only a single JSON object. No markdown. No explanation. "
        "If the page is a search, category, showroom, or wholesale listing page rather than a single product detail page, "
        "set is_product_page to false and keep product_name, price_text, price_inr, image_urls, rating, and reviews_count as null. "
        "Keys: product_name (string), price_text (string or null), price_inr (number or null), "
        "description (string max 300 chars or null), image_urls (array of absolute URL strings), "
        "marketplace (string domain like amazon.in or alibaba.com or null), rating (number 0-5 or null), "
        "reviews_count (integer or null), in_stock (boolean or null), supplier_name (string or null), "
        "is_product_page (boolean), reject_reason (string or null)."
    )

    def detect_domain(url: str | None) -> str | None:
        try:
            return urlparse(str(url or '')).hostname
        except Exception:
            return None

    results = ctx.get('stripped_content', [])
    out = []

    for item in results:
        if isinstance(item, dict):
            j = item.get('json', item)
        else:
            j = getattr(item, 'json', item)
        if not isinstance(j, dict):
            continue

        url = j.get('tavily_url') or ''
        content = str(j.get('tavily_raw_content') or '')[:60000]

        if not url or len(content) < 50:
            out.append({
                'json': {
                    **j,
                    'gemini_prompt': None,
                    'gemini_skipped': 'thin or missing input',
                }
            })
            continue

        prompt = (
            SYSTEM
            + f"\n\nURL: {url}"
            + f"\nPage title: {str(j.get('tavily_title') or '')}"
            + f"\nMarketplace domain: {str(j.get('tavily_domain') or detect_domain(url) or '')}"
            + f"\n\nMarketplace page text:\n{content}"
        )

        out.append({
            'json': {
                **j,
                'gemini_prompt': prompt,
            }
        })

    ctx['gemini_prompts'] = out
    return ctx
