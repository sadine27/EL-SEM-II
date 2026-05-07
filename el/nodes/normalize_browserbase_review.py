"""Normalize Browserbase extracted product data and build HIL review schema."""
from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any


def run(ctx: dict) -> dict:
    """Normalize Gemini-extracted product data and filter for HIL review insertion.

    Input: ctx["gemini_extracts"] (Gemini JSON extraction responses)
           ctx["picked_indian_listings"] (original listings for metadata pairing)
    Output: ctx["normalized_reviews"] (HIL review schema items ready for insertion)
    """

    def parse_first_json_object(text: str | None) -> dict:
        if not text:
            return {}
        try:
            match = re.search(r'\{[\s\S]*\}', str(text))
            return json.loads(match.group(0)) if match else {}
        except Exception:
            return {}

    def compact(value: str | None) -> str:
        return ' '.join((str(value or '')).split())

    def normalize_text(value: str | None) -> str:
        s = compact(value).lower()
        return re.sub(r'[^a-z0-9\s]', ' ', s).strip()

    def tokenize(value: str | None) -> list[str]:
        return [w for w in normalize_text(value).split() if len(w) > 2]

    def overlap_count(text: str, tokens: list[str]) -> int:
        return sum(1 for t in tokens if t in text)

    def to_number(value: Any) -> float | None:
        if isinstance(value, (int, float)) and not (isinstance(value, bool)):
            return float(value) if isinstance(value, int) else value if (-1e10 < value < 1e10) else None
        cleaned = compact(str(value or '')).replace(',', '')
        matches = re.findall(r'[\d.]+', cleaned)
        if not matches:
            return None
        try:
            parsed = float(matches[0])
            return parsed if -1e10 < parsed < 1e10 else None
        except ValueError:
            return None

    def url_looks_bad(url: str | None) -> bool:
        v = str(url or '').lower()
        if re.search(r'[?&](k|q|keyword|search)=', v):
            return True
        if re.search(r'\/s(\?|\/|$)', v):
            return True
        if re.search(r'(showroom|wholesale|collections?|category|categories|browse|results|product-insights|unboxed|blog|blogs|article|articles)', v):
            return True
        return False

    def url_looks_product(url: str | None) -> bool:
        v = str(url or '').lower()
        if re.search(r'(\/dp\/|\/gp\/product\/|\/product\/|\/products\/|\/item\/|\/offer\/|\/p\/)', v):
            return True
        if re.search(r'\/b0[a-z0-9]{8,}', v):
            return True
        return False

    def parse_image_urls(value: Any) -> list[str]:
        if isinstance(value, list):
            return [compact(str(item)) for item in value if re.match(r'^https?://', compact(str(item)), re.IGNORECASE)]
        if isinstance(value, str) and value.strip():
            try:
                parsed = json.loads(value)
                if isinstance(parsed, list):
                    return [compact(str(item)) for item in parsed if re.match(r'^https?://', compact(str(item)), re.IGNORECASE)]
            except Exception:
                pass
            if re.match(r'^https?://', value.strip(), re.IGNORECASE):
                return [value.strip()]
        return []

    def detect_image_urls(text: str | None) -> list[str]:
        matches = re.findall(r'https?:\/\/[^\s"\'()]+(?:jpg|jpeg|png|webp|gif)', str(text or ''), re.IGNORECASE)
        return list(dict.fromkeys([compact(m) for m in matches if m]))[:5]

    def is_usable_image_url(url: str | None) -> bool:
        v = str(url or '').lower()
        if not re.match(r'^https?://', v, re.IGNORECASE):
            return False
        if re.search(r'(sprite|logo|icon|flag|placeholder|spacer|privacy|batman-returns|moengage|avatar|profileimage)', v):
            return False
        if re.search(r'\.gif(\?|$)', v):
            return False
        if re.search(r'\/gif(\/|\?|$)', v):
            return False
        return True

    def detect_price_text(text: str | None) -> str | None:
        match = re.search(r'(?:^|[\s(])(?:rs\.?|inr|₹)\s*[0-9][0-9,]*(?:\.\d{1,2})?', str(text or ''), re.IGNORECASE)
        return compact(match.group(0)) if match else None

    def detect_rating(text: str | None) -> float | None:
        match = re.search(r'\b([0-5](?:\.\d)?)\s*(?:out of 5|\/5|stars?)\b', str(text or ''), re.IGNORECASE)
        return to_number(match.group(1)) if match else None

    def detect_reviews_count(text: str | None) -> int | None:
        match = re.search(r'\b([0-9][0-9,]{0,10})\s*(?:ratings?|reviews?)\b', str(text or ''), re.IGNORECASE)
        if match:
            count = to_number(match.group(1))
            return int(round(count)) if count is not None else None
        return None

    def detect_availability(text: str | None) -> str:
        v = str(text or '').lower()
        if re.search(r'currently unavailable|out of stock|sold out', v):
            return 'out_of_stock'
        if re.search(r'\bin stock\b', v):
            return 'in_stock'
        return 'unknown'

    def clean_title(title: str | None) -> str | None:
        text = compact(title)
        if not text:
            return None
        cleaned = re.sub(r'^amazon\.in\s*:\s*', '', text, flags=re.IGNORECASE)
        cleaned = re.sub(r'^buy\s+', '', cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r'\s+online at low prices in india.*$', '', cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r'\s+\|\s+amazon\.in.*$', '', cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r'\s+:\s+amazon\.in.*$', '', cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r'\s+-\s+amazon\.in.*$', '', cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r'\s+-\s+alibaba\.com.*$', '', cleaned, flags=re.IGNORECASE)
        cleaned = cleaned.strip()
        return None if not cleaned or re.match(r'^404\b', cleaned, re.IGNORECASE) else cleaned

    def product_match_count(text: str, product_hint: str | None) -> int:
        aliases = {
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
        list_aliases = aliases.get(product_hint or '', [product_hint] if product_hint else [])
        normalized = normalize_text(text)
        return sum(1 for alias in list_aliases if normalize_text(alias) in normalized)

    def is_book_like(text: str | None) -> bool:
        return bool(re.search(r'\b(book|books|novel|novels|paperback|hardcover|kindle|author|authors)\b', str(text or ''), re.IGNORECASE))

    # Build mapping of extracted items by index for pairing
    gemini_items = ctx.get('gemini_extracts', [])
    prompt_items = ctx.get('gemini_prompts', [])
    run_date = datetime.now().strftime('%Y-%m-%d')

    out = []

    for idx, item in enumerate(gemini_items):
        if isinstance(item, dict):
            j = item.get('json', item)
        else:
            j = getattr(item, 'json', item)

        # Get base metadata from prompt items (should match by order)
        base = prompt_items[idx]['json'] if idx < len(prompt_items) else {}
        if isinstance(prompt_items[idx] if idx < len(prompt_items) else {}, dict):
            base = prompt_items[idx].get('json', prompt_items[idx]) if idx < len(prompt_items) else {}

        # Check for missing URL or error conditions
        if not base.get('tavily_url') or not base.get('source_topic'):
            continue
        if url_looks_bad(base.get('tavily_url')):
            continue

        # Parse Gemini response
        response = j or {}
        candidates = response.get('candidates', []) or []
        gemini_text = ''
        if candidates and isinstance(candidates[0], dict):
            content = candidates[0].get('content', {})
            parts = content.get('parts', []) if isinstance(content, dict) else []
            gemini_text = ''.join(p.get('text', '') for p in (parts or []) if isinstance(p, dict))

        extract = parse_first_json_object(gemini_text)

        # Image URLs: prefer extracted, fall back to detection
        image_urls = parse_image_urls(extract.get('image_urls'))
        if not image_urls:
            image_urls = detect_image_urls(base.get('tavily_raw_content'))
        image_urls = [url for url in image_urls if is_usable_image_url(url)]
        image_url = image_urls[0] if image_urls else None

        # Fallback detection for missing fields
        fallback_text = (base.get('tavily_title') or '') + '\n' + (base.get('tavily_raw_content') or '')
        rating = to_number(extract.get('rating')) or detect_rating(fallback_text)
        reviews_count_raw = to_number(extract.get('reviews_count')) or detect_reviews_count(fallback_text)
        reviews_count = int(round(reviews_count_raw)) if reviews_count_raw is not None else None
        price_text = extract.get('price_text') or detect_price_text(fallback_text)
        price_inr = to_number(extract.get('price_inr')) or to_number(price_text)
        product_name = extract.get('product_name') or clean_title(base.get('tavily_title'))
        marketplace_host = extract.get('marketplace') or base.get('tavily_domain')
        likely_product_page = extract.get('is_product_page') is True or base.get('tavily_is_likely_product_page') or url_looks_product(base.get('tavily_url'))
        has_review_signals = bool(price_text or image_url or rating is not None or reviews_count is not None)

        # Text analysis for matching
        text_for_match = normalize_text(' '.join([product_name or '', fallback_text, extract.get('description') or '']))
        entity_matches = overlap_count(text_for_match, tokenize(base.get('entity_hint') or ''))
        product_matches = product_match_count(text_for_match, base.get('product_hint'))
        merch_intent = base.get('intent_mode') == 'merch' or bool(re.search(r'(merchandise|t shirt|hoodie|poster|mug|keychain|case|shirt|cover|cap)', base.get('tavily_query') or '', re.IGNORECASE))

        # Filtering rules
        title_looks_404 = bool(re.match(r'^404\b', compact(base.get('tavily_title') or ''), re.IGNORECASE)) or bool(re.match(r'^404\b', compact(product_name or ''), re.IGNORECASE))
        if not product_name or title_looks_404:
            continue
        if extract.get('is_product_page') is False and not likely_product_page and not has_review_signals:
            continue
        if not likely_product_page and not has_review_signals:
            continue
        if is_book_like(text_for_match) and merch_intent:
            continue
        if merch_intent and (not product_matches or (base.get('entity_hint') and not entity_matches)):
            continue
        if not merch_intent and base.get('entity_hint') and not entity_matches and not product_matches:
            continue
        if not price_text and not image_url:
            continue
        if price_inr is not None and price_inr < 20:
            continue

        # Build HIL review schema
        availability = (
            'in_stock' if extract.get('in_stock') is True
            else 'out_of_stock' if extract.get('in_stock') is False
            else detect_availability(fallback_text)
        )

        out.append({
            'json': {
                'review_schema_version': 'hil_v1',
                'workflow_name': 'EL',
                'workflow_run_id': f"EL:{run_date}:{ctx.get('_execution_id', 'manual')}",
                'run_date': base.get('run_date') or run_date,
                'source_provider': 'browserbase_marketplace',
                'source_topic': base.get('source_topic'),
                'source_pick_rank': base.get('source_pick_rank'),
                'opportunity_score': base.get('opportunity_score'),
                'product_name': product_name,
                'product_url': base.get('tavily_url'),
                'product_sku': None,
                'price_text': price_text,
                'price_numeric': price_inr,
                'currency': 'INR',
                'product_rating': rating,
                'reviews_count': reviews_count,
                'image_url': image_url,
                'image_urls': json.dumps(image_urls),
                'description': compact(extract.get('description') or '')[:300] if extract.get('description') else None,
                'supplier_name': extract.get('supplier_name'),
                'marketplace': marketplace_host,
                'availability_status': availability,
                'approval_status': 'pending',
                'approval_channel': 'telegram',
                'raw_payload': json.dumps({
                    'source': 'browserbase_marketplace',
                    'tavily_query': base.get('tavily_query'),
                    'tavily_score': base.get('tavily_score'),
                    'tavily_quality_score': base.get('tavily_quality_score'),
                    'tavily_entity_matches': base.get('tavily_entity_matches'),
                    'tavily_product_matches': base.get('tavily_product_matches'),
                    'tavily_title': base.get('tavily_title'),
                    'tavily_domain': base.get('tavily_domain'),
                    'tavily_selection_mode': base.get('tavily_selection_mode'),
                    'tavily_is_likely_product_page': base.get('tavily_is_likely_product_page'),
                    'browserbase_used': base.get('browserbase_used'),
                    'gemini_status': response.get('gemini_status_code', 200),
                    'gemini_error': response.get('error'),
                    'extract': extract,
                }),
                'scraped_at': datetime.now().isoformat(),
            }
        })

    ctx['normalized_reviews'] = out
    return ctx
