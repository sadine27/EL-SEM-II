"""Build search queries for Tavily web search."""
from __future__ import annotations


def run(ctx: dict) -> dict:
    """Generate Tavily search queries from ranked products.

    Input: ctx["ranked_payload"] (list of ranked product items)
    Output: ctx["tavily_queries"] (list of query items ready for Tavily search)
    """
    product_terms = {
        'phone case', 't shirt', 'hoodie', 'poster', 'mug', 'keychain',
        'action figure', 'building blocks', 'toy', 'plush', 'figurine',
        'sticker', 'cover', 'shirt', 'case', 'cap'
    }
    merch_terms = {
        't shirt', 'hoodie', 'poster', 'mug', 'keychain', 'sticker',
        'shirt', 'case', 'cover', 'cap'
    }

    def compact(value: str | None) -> str:
        return ' '.join((str(value) or '').split())

    def normalize(value: str | None) -> str:
        s = compact(value).lower()
        return ' '.join(c for c in s if c.isalnum() or c.isspace()).split()

    def clean_entity(raw: str | None) -> str:
        text = compact(raw)
        if not text:
            return ''
        text = text.split('|')[0]
        words_to_remove = {'official', 'video', 'song', 'trailer', 'teaser', 'live', 'lyrics', 'audio', 'full', 'viral', 'new'}
        text = ' '.join(w for w in text.split() if w.lower() not in words_to_remove and not w.startswith('#'))
        if len(text) > 80:
            text = ' '.join(text.split()[:8])
        return compact(text)

    def detect_product_term(query: str, suggested_type: str | None) -> str:
        hay = normalize(' '.join(filter(None, [query, suggested_type])))
        for term in product_terms:
            if all(w in hay for w in term.split()):
                return term
        query_words = normalize(query)
        if len(query_words) >= 2:
            return ' '.join(query_words[-2:])
        if query_words:
            return query_words[0]
        type_words = normalize(suggested_type) if suggested_type else []
        return ' '.join(type_words[:2]) if type_words else ''

    def looks_merch_topic(topic: str | None, query: str | None, product_term: str | None) -> bool:
        text = ' '.join(filter(None, [topic, query, product_term])).lower()
        patterns = {'series', 'movie', 'trailer', 'song', 'music', 'video', 'bgmi', 'minecraft', 'marvel', 'wolverine'}
        return any(p in text for p in patterns)

    ranked = ctx.get('ranked_payload', [])
    out = []

    for item in ranked:
        # Handle both dict items and wrapped items with 'json' key
        if isinstance(item, dict):
            j = item.get('json', item)
        else:
            j = getattr(item, 'json', item)
        if not isinstance(j, dict):
            continue
        if isinstance(j, dict) and j.get('error'):
            continue

        search_query = compact(j.get('search_query_in') or '')
        entity = clean_entity(j.get('topic') or search_query)
        product_term = detect_product_term(search_query, j.get('suggested_product_type'))
        merch_intent = looks_merch_topic(j.get('topic'), search_query, product_term)

        if not product_term and merch_intent:
            product_term = 't shirt'

        keyword = compact(search_query or ' '.join(filter(None, [entity, product_term])))
        if not keyword:
            keyword = compact(j.get('topic') or '')
        keyword = keyword[:120]
        if not keyword:
            continue

        # Build Tavily query
        if entity and product_term:
            if merch_intent or product_term in merch_terms:
                tavily_query = f'buy "{entity}" merchandise {product_term} india'
            else:
                tavily_query = f'buy "{entity}" {product_term} india'
        elif search_query:
            tavily_query = f'buy {search_query} india'
        else:
            tavily_query = f'buy {keyword} india'

        tavily_query = compact(tavily_query)[:180]

        out.append({
            'json': {
                'keyword': keyword,
                'tavily_query': tavily_query,
                'entity_hint': entity or None,
                'product_hint': product_term or None,
                'intent_mode': 'merch' if (merch_intent or product_term in merch_terms) else 'direct_product',
                'source_topic': j.get('topic') or keyword,
                'source_pick_rank': j.get('rank'),
                'opportunity_score': j.get('opportunity_score'),
                'run_date': j.get('run_date') or None,
                'suggested_product_type': j.get('suggested_product_type'),
                'target_audience': j.get('target_audience'),
            }
        })

    ctx['tavily_queries'] = out
    return ctx
