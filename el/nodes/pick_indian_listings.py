"""Filter and rank Tavily search results for quality and relevance."""
from __future__ import annotations

from typing import Any


def run(ctx: dict) -> dict:
    """Rank and filter Tavily results by product relevance and quality.

    Input: ctx["tavily_search_results"] (raw search results from Tavily)
           ctx["tavily_queries"] (original query metadata, for pairing)
    Output: ctx["picked_indian_listings"] (top 3 results per query, by quality score)
    """
    STOP_WORDS = {'the', 'and', 'for', 'with', 'from', 'that', 'this', 'your', 'into', 'online', 'india', 'buy'}
    MERCH_PRODUCT_TERMS = {'t shirt', 'hoodie', 'poster', 'mug', 'keychain', 'sticker', 'shirt', 'case', 'cover', 'cap'}
    PRODUCT_ALIASES = {
        't shirt': ['t shirt', 'tshirt', 'shirt', 'tee', 'hoodie'],
        'hoodie': ['hoodie', 'sweatshirt'],
        'poster': ['poster', 'wall poster'],
        'mug': ['mug', 'cup'],
        'keychain': ['keychain', 'key chain'],
        'sticker': ['sticker'],
        'phone case': ['phone case', 'case', 'cover'],
        'action figure': ['action figure', 'figurine', 'collectible', 'toy'],
        'building blocks': ['building blocks', 'blocks', 'brick', 'bricks', 'lego'],
    }

    def compact(value: str | None) -> str:
        return ' '.join((str(value) or '').split())

    def normalize_text(value: str | None) -> str:
        s = compact(value).lower()
        return ' '.join(c for c in s if c.isalnum() or c.isspace())

    def tokenize(value: str | None) -> list[str]:
        words = normalize_text(value).split()
        return [w for w in words if len(w) > 2 and w not in STOP_WORDS]

    def url_looks_bad(url: str | None) -> bool:
        v = (str(url) or '').lower()
        bad_patterns = {'/s', 'showroom', 'wholesale', 'collections', 'category', 'browse', 'results', 'blog', 'article'}
        has_search_param = any(p in v for p in ['?k=', '?q=', '?keyword=', '?search='])
        has_bad_pattern = any(p in v for p in bad_patterns)
        return has_search_param or has_bad_pattern

    def url_looks_product(url: str | None) -> bool:
        v = (str(url) or '').lower()
        product_patterns = {'/dp/', '/gp/product/', '/product/', '/products/', '/item/', '/offer/', '/p/'}
        asin_pattern = '/b0' in v  # Amazon ASIN pattern
        has_pattern = any(p in v for p in product_patterns)
        return has_pattern or asin_pattern

    def overlap_count(text: str, tokens: list[str]) -> int:
        return sum(1 for t in tokens if t in text)

    def product_match_count(text: str, product_hint: str | None) -> int:
        if not product_hint:
            return 0
        aliases = PRODUCT_ALIASES.get(product_hint, [product_hint] if product_hint else [])
        normalized = normalize_text(text)
        return sum(1 for alias in aliases if normalize_text(alias) in normalized)

    def is_book_like(text: str) -> bool:
        return any(w in text.lower() for w in ['book', 'novel', 'paperback', 'hardcover', 'kindle', 'author'])

    def quality_score(result: dict[str, Any], meta: dict[str, Any]) -> float:
        url = str(result.get('tavily_url') or '')
        title = compact(result.get('tavily_title') or '')
        raw = compact(result.get('tavily_raw_content') or '')
        text = normalize_text(title + ' ' + raw)
        product_tokens = tokenize(meta.get('product_hint') or meta.get('keyword') or '')
        entity_tokens = tokenize(meta.get('entity_hint') or '')
        merch_intent = meta.get('intent_mode') == 'merch'

        score = float(result.get('tavily_score') or 0) * 10
        if url_looks_product(url):
            score += 4
        if 'rs' in raw.lower() or '₹' in raw:
            score += 2
        if any(w in text for w in ['rating', 'star', 'review', 'rate']):
            score += 1.5
        score += overlap_count(text, product_tokens) * 1.8
        score += overlap_count(text, entity_tokens) * 1.4
        score += product_match_count(text, meta.get('product_hint')) * 2.4

        if meta.get('entity_hint') and normalize_text(meta.get('entity_hint')) in text:
            score += 2

        if merch_intent and product_match_count(text, meta.get('product_hint')) == 0:
            score -= 10
        if merch_intent and entity_tokens and overlap_count(text, entity_tokens) == 0:
            score -= 8
        if merch_intent and is_book_like(text):
            score -= 12
        if not merch_intent and entity_tokens and overlap_count(text, entity_tokens) == 0:
            score -= 3
        if url_looks_bad(url):
            score -= 8

        return score

    # Group search results by original query
    search_results = ctx.get('tavily_search_results', [])
    queries = ctx.get('tavily_queries', [])
    query_by_idx = {i: (q.get('json', q) if isinstance(q, dict) else q) for i, q in enumerate(queries)}

    # Group results by query to handle multiple results per query
    results_by_query_key = {}
    for result_item in search_results:
        if isinstance(result_item, dict):
            result = result_item.get('json', result_item)
        else:
            result = getattr(result_item, 'json', result_item)
        query_key = (result.get('tavily_query'), result.get('entity_hint'), result.get('product_hint'))
        if query_key not in results_by_query_key:
            results_by_query_key[query_key] = []
        results_by_query_key[query_key].append(result)

    picked = []

    for (tavily_query, entity_hint, product_hint), group_results in results_by_query_key.items():
        # Get metadata from first result in group
        if not group_results:
            continue
        meta = group_results[0]

        # Skip if error
        if meta.get('error'):
            continue

        # Rank results
        ranked = sorted(
            group_results,
            key=lambda r: quality_score(r, meta),
            reverse=True
        )

        # Filter safe results
        safe = [
            r for r in ranked
            if not url_looks_bad(r.get('tavily_url'))
            and not is_book_like(normalize_text(r.get('tavily_title') or ''))
            and quality_score(r, meta) >= 8
        ]

        # Also check product/entity matching based on intent_mode
        merch_intent = meta.get('intent_mode') == 'merch'
        if merch_intent:
            safe = [
                r for r in safe
                if not is_book_like(normalize_text(r.get('tavily_title') or ''))
                and product_match_count(normalize_text(r.get('tavily_title') or ''), product_hint) > 0
                and (not entity_hint or overlap_count(normalize_text(r.get('tavily_title') or ''), tokenize(entity_hint)) > 0)
            ]
        else:
            safe = [
                r for r in safe
                if overlap_count(normalize_text(r.get('tavily_title') or ''), tokenize(entity_hint or '')) > 0
                or product_match_count(normalize_text(r.get('tavily_title') or ''), product_hint) > 0
            ]

        # Prefer product pages, then fall back to safe, then last resort
        preferred = [r for r in safe if url_looks_product(r.get('tavily_url')) and quality_score(r, meta) >= 11]
        chosen = []
        seen = set()

        for source_list, mode in [(preferred, 'preferred'), (safe, 'fallback_safe')]:
            for result in source_list:
                if len(chosen) >= 3:
                    break
                url = result.get('tavily_url')
                if url and url not in seen:
                    seen.add(url)
                    raw_content = compact(result.get('tavily_raw_content') or '')[:60000]
                    chosen.append({
                        'json': {
                            'run_date': meta.get('run_date'),
                            'source_topic': meta.get('source_topic'),
                            'source_pick_rank': meta.get('source_pick_rank'),
                            'opportunity_score': meta.get('opportunity_score'),
                            'tavily_query': tavily_query,
                            'entity_hint': entity_hint,
                            'product_hint': product_hint,
                            'intent_mode': meta.get('intent_mode'),
                            'tavily_url': url,
                            'tavily_title': result.get('tavily_title') or '',
                            'tavily_score': result.get('tavily_score') or 0,
                            'tavily_quality_score': quality_score(result, meta),
                            'tavily_entity_matches': overlap_count(normalize_text(result.get('tavily_title') or ''), tokenize(entity_hint or '')),
                            'tavily_product_matches': product_match_count(normalize_text(result.get('tavily_title') or ''), product_hint),
                            'tavily_raw_content': raw_content,
                            'tavily_content_len': len(raw_content),
                            'tavily_domain': result.get('tavily_domain'),
                            'tavily_is_likely_product_page': url_looks_product(url),
                            'tavily_selection_mode': mode,
                            'suggested_product_type': meta.get('suggested_product_type'),
                            'target_audience': meta.get('target_audience'),
                        }
                    })
            if len(chosen) >= 3:
                break

        # Last resort: if nothing picked yet, try the best ranked (if it passed base filtering)
        if not chosen and ranked and quality_score(ranked[0], meta) >= 5:
            url = ranked[0].get('tavily_url')
            title = normalize_text(ranked[0].get('tavily_title') or '')
            # Don't use last resort for books in merch intent or if quality too low
            if url and not url_looks_bad(url):
                if merch_intent and is_book_like(title):
                    pass  # Skip books for merchandise intent
                else:
                    raw_content = compact(ranked[0].get('tavily_raw_content') or '')[:60000]
                    chosen.append({
                        'json': {
                            'run_date': meta.get('run_date'),
                            'source_topic': meta.get('source_topic'),
                            'source_pick_rank': meta.get('source_pick_rank'),
                            'opportunity_score': meta.get('opportunity_score'),
                            'tavily_query': tavily_query,
                            'entity_hint': entity_hint,
                            'product_hint': product_hint,
                            'intent_mode': meta.get('intent_mode'),
                            'tavily_url': url,
                            'tavily_title': ranked[0].get('tavily_title') or '',
                            'tavily_score': ranked[0].get('tavily_score') or 0,
                            'tavily_quality_score': quality_score(ranked[0], meta),
                            'tavily_entity_matches': overlap_count(normalize_text(ranked[0].get('tavily_title') or ''), tokenize(entity_hint or '')),
                            'tavily_product_matches': product_match_count(normalize_text(ranked[0].get('tavily_title') or ''), product_hint),
                            'tavily_raw_content': raw_content,
                            'tavily_content_len': len(raw_content),
                            'tavily_domain': ranked[0].get('tavily_domain'),
                            'tavily_is_likely_product_page': url_looks_product(url),
                            'tavily_selection_mode': 'last_resort',
                            'suggested_product_type': meta.get('suggested_product_type'),
                            'target_audience': meta.get('target_audience'),
                        }
                    })

        picked.extend(chosen)

    ctx['picked_indian_listings'] = picked
    return ctx
