from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT / ".env"
WORKFLOW_ID = "298f3JSOE72nhW59"


def read_env() -> dict[str, str]:
    env: dict[str, str] = {}
    for raw_line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.split(" #", 1)[0].strip().strip('"').strip("'")
        env[key.strip()] = value
    return env


ENV = read_env()
N8N_URL = ENV["N8N_URL"]
N8N_SECRET = ENV["N8N_SECRET"]
GEMINI_API_KEY = ENV["GEMINI_API_KEY"]

CRED_TAVILY = {"id": "1W4trh2dkUei7Iet", "name": "Tavily API (EL Phase 3)"}
CRED_BROWSERBASE = {"id": "VaqaiCGZLn38cSq1", "name": "Browserbase API (EL Phase 3)"}
POSTGRES_CRED = {"id": "Tx3i0fewZ8MM6LFt", "name": "Supabase yatralounge (Dropship Memory)"}

INDIAN_MARKETPLACES = [
    "amazon.in",
    "flipkart.com",
    "meesho.com",
    "myntra.com",
    "ajio.com",
    "nykaa.com",
    "purplle.com",
    "tatacliq.com",
    "snapdeal.com",
    "firstcry.com",
    "pepperfry.com",
    "urbanladder.com",
    "croma.com",
    "reliancedigital.in",
    "decathlon.in",
    "alibaba.com",
]


PHASE3_NODE_NAMES = {
    "Build Tavily Query",
    "Tavily Search (IN Market)",
    "Pick Indian Listings",
    "If Tavily Content Thin",
    "Browserbase Fetch",
    "Strip HTML",
    "Gemini Extract Product",
    "Normalize Browserbase Review",
    "Normalize CJ Review",
    "Merge Review Sources",
    "Supabase Insert (HIL Reviews)",
    "cluster:phase3b-browserbase-review",
    "cluster:phase3d-hil-review-queue",
    "Normalize Tavily Product",
    "cluster:phase3b-indian-market",
}


def http(method: str, path: str, body: dict | None = None):
    req = urllib.request.Request(
        f"{N8N_URL}/api/v1{path}",
        data=json.dumps(body).encode() if body is not None else None,
        method=method,
        headers={
            "X-N8N-API-KEY": N8N_SECRET,
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.loads(resp.read() or b"null")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode(errors="replace")


BUILD_TAVILY_QUERY_JS = r"""
const TOPIC_STOP = new Set([
  'official','video','song','new','live','trailer','teaser','full','movie','season','episode',
  'vs','viral','instagram','youtube','music','bgmi','gaming','challenge','opening','news'
]);

const PRODUCT_HINTS = [
  { canonical: 't-shirt', aliases: ['tshirt','t-shirt','tee','tees','shirt','shirts','hoodie','hoodies'] },
  { canonical: 'phone case', aliases: ['case','cover','phonecase','phone-case'] },
  { canonical: 'mug', aliases: ['mug','cup'] },
  { canonical: 'poster', aliases: ['poster','posters'] },
  { canonical: 'keychain', aliases: ['keychain','key-chain','keychains'] },
  { canonical: 'action figure', aliases: ['figure','figures','toy','toys','collectible','collectibles'] },
  { canonical: 'building blocks', aliases: ['blocks','block','brick','bricks','lego'] },
];

function detectProductHint(...values) {
  const text = values.filter(Boolean).join(' ').toLowerCase();
  for (const hint of PRODUCT_HINTS) {
    if (hint.aliases.some(alias => text.includes(alias))) return hint.canonical;
  }
  return null;
}

function extractTopicKey(topic) {
  const parts = String(topic || '')
    .replace(/[#|:()[\]{}]/g, ' ')
    .replace(/[^\p{L}\p{N}\s-]+/gu, ' ')
    .split(/\s+/)
    .filter(Boolean);
  const kept = [];
  for (const part of parts) {
    const normalized = part.toLowerCase();
    if (normalized.length < 3) continue;
    if (/^\d+$/.test(normalized)) continue;
    if (TOPIC_STOP.has(normalized)) continue;
    kept.push(part);
    if (kept.length >= 4) break;
  }
  return kept.join(' ').trim();
}

function buildMarketplaceQuery(topicKey, productHint, fallbackKeyword) {
  const base = (topicKey || fallbackKeyword || '').trim();
  if (!base) return '';
  if (!productHint) return `${base} buy India`;
  if (productHint === 't-shirt') return `${base} fan t-shirt India -book -novel -kindle`;
  if (productHint === 'phone case') return `${base} phone case India`;
  if (productHint === 'mug') return `${base} printed mug India -book -novel`;
  if (productHint === 'poster') return `${base} wall poster India`;
  if (productHint === 'keychain') return `${base} keychain India`;
  if (productHint === 'action figure') return `${base} action figure India -book -novel`;
  if (productHint === 'building blocks') return `${base} building blocks India -book -novel`;
  return `${base} ${productHint} India`;
}

const items = $input.all();
const out = [];
for (const it of items) {
  const j = it.json || {};
  if (j.error) continue;
  const rawKeyword = String(j.search_query_in || '').replace(/\s+/g, ' ').trim();
  const topicKey = extractTopicKey(j.topic || rawKeyword);
  const productHint = detectProductHint(rawKeyword, j.suggested_product_type || '');
  let q = buildMarketplaceQuery(topicKey, productHint, rawKeyword || String(j.topic || '').trim());
  if (!q) q = String(j.suggested_product_type || '').trim();
  if (!q) q = String(j.topic || '').trim();
  q = q.replace(/\s+/g, ' ').trim().slice(0, 120);
  if (!q) continue;
  out.push({ json: {
    keyword: q,
    source_topic: j.topic || q,
    source_pick_rank: j.rank ?? null,
    opportunity_score: j.opportunity_score ?? null,
    run_date: j.run_date || new Date().toISOString().substring(0, 10),
    query_product_hint: productHint,
    topic_key: topicKey || null,
    suggested_product_type: j.suggested_product_type || null,
    target_audience: j.target_audience || null,
  }});
}
return out;
"""

PICK_INDIAN_LISTINGS_JS = r"""
function parseUrl(value) {
  try { return new URL(value); } catch { return null; }
}

function isSearchOrCollectionPage(urlObj) {
  if (!urlObj) return true;
  const path = urlObj.pathname.toLowerCase();
  const query = urlObj.searchParams;
  if (path === '/s' || query.has('k') || query.has('q') || query.has('keyword') || query.has('search')) return true;
  return /(showroom|wholesale|search|collections?|category|categories|browse|results)/.test(path);
}

function isLikelyProductPage(urlObj) {
  if (!urlObj || isSearchOrCollectionPage(urlObj)) return false;
  const path = urlObj.pathname.toLowerCase();
  if (/(\/dp\/|\/gp\/product\/|\/product\/|\/products\/|\/item\/|\/offer\/|\/p\/)/.test(path)) return true;
  const last = path.split('/').filter(Boolean).pop() || '';
  return /[a-z0-9][a-z0-9-]{7,}/.test(last);
}

function titleLooksGeneric(title) {
  const text = String(title || '').trim().toLowerCase();
  if (!text) return true;
  return /^amazon\.in\s*:/.test(text)
    || /(^|\b)(search|showroom|wholesale|category|categories)(\b|$)/.test(text)
    || /online at low prices/.test(text);
}

function qualityScore(result) {
  const title = String(result.title || '');
  const raw = String(result.raw_content || result.content || '');
  let score = Number(result.score || 0);
  if (/(₹|rs\.?|inr)\s*\d/i.test(raw)) score += 0.35;
  if (/\b\d(?:\.\d)?\s*(out of 5|\/5|stars?)\b/i.test(raw)) score += 0.2;
  if (/ratings?|reviews?/i.test(raw)) score += 0.15;
  if (!titleLooksGeneric(title)) score += 0.15;
  if (isLikelyProductPage(parseUrl(result.url))) score += 1;
  return score;
}

const MATCH_HINTS = {
  't-shirt': ['tshirt','t-shirt','tee','shirt','hoodie'],
  'phone case': ['case','cover'],
  'mug': ['mug','cup'],
  'poster': ['poster'],
  'keychain': ['keychain','key-chain'],
  'action figure': ['figure','toy','collectible'],
  'building blocks': ['blocks','block','brick','lego'],
};

function normalizeText(value) {
  return String(value || '').toLowerCase().replace(/[^a-z0-9\s-]+/g, ' ').replace(/\s+/g, ' ').trim();
}

function tokenSet(value) {
  return new Set(normalizeText(value).split(' ').filter(token => token.length > 2));
}

function hintMatchScore(text, productHint) {
  if (!productHint) return 0;
  const aliases = MATCH_HINTS[productHint] || [productHint];
  const hay = normalizeText(text);
  return aliases.some(alias => hay.includes(alias)) ? 1 : 0;
}

function mismatchPenalty(text, productHint) {
  const hay = normalizeText(text);
  if (productHint && ['t-shirt','phone case','mug','poster','keychain','action figure','building blocks'].includes(productHint)) {
    if (/\b(book|books|novel|paperback|kindle|author)\b/.test(hay)) return 2;
  }
  return 0;
}

const items = $input.all();
const out = [];
for (let i = 0; i < items.length; i++) {
  const it = items[i].json || {};
  const meta = $('Build Tavily Query').all()[i]?.json || {};
  const results = Array.isArray(it.results) ? it.results : [];
  const seen = new Set();
  const topicTerms = [...tokenSet(meta.topic_key || meta.source_topic || '')];
  const productHint = meta.query_product_hint || null;
  const ranked = results
    .filter(r => (r.score || 0) >= 0.2 && r.url)
    .map(r => {
      const text = `${r.title || ''} ${r.raw_content || r.content || ''}`;
      const topicMatches = topicTerms.filter(term => normalizeText(text).includes(term)).length;
      const productMatch = hintMatchScore(text, productHint);
      const penalty = mismatchPenalty(text, productHint);
      return {
        ...r,
        _url: parseUrl(r.url),
        _topicMatches: topicMatches,
        _productMatch: productMatch,
        _penalty: penalty,
        _quality: qualityScore(r) + (topicMatches * 0.2) + (productMatch * 1.2) - penalty,
      };
    })
    .filter(r => r._url && !isSearchOrCollectionPage(r._url))
    .filter(r => r._penalty < 2)
    .sort((a, b) => (b._quality || 0) - (a._quality || 0));

  function pushResult(r) {
    if (seen.has(r.url)) return false;
    seen.add(r.url);
    const raw = String(r.raw_content || r.content || '').substring(0, 60000);
    out.push({ json: {
      run_date: meta.run_date ?? null,
      source_topic: meta.source_topic ?? null,
      source_pick_rank: meta.source_pick_rank ?? null,
      opportunity_score: meta.opportunity_score ?? null,
      tavily_url: r.url,
      tavily_title: r.title || '',
      tavily_score: r.score || 0,
      tavily_raw_content: raw,
      tavily_content_len: raw.length,
      tavily_domain: r._url?.hostname || null,
      tavily_is_likely_product_page: isLikelyProductPage(r._url),
      tavily_topic_match_count: r._topicMatches || 0,
      tavily_product_match: r._productMatch || 0,
      suggested_product_type: meta.suggested_product_type ?? null,
      target_audience: meta.target_audience ?? null,
    }});
    return seen.size >= 3;
  }

  for (const r of ranked) {
    if (!isLikelyProductPage(r._url)) continue;
    if (pushResult(r)) break;
  }
  for (const r of ranked) {
    if (seen.size >= 3) break;
    pushResult(r);
  }
}
return out;
"""

STRIP_HTML_JS = r"""
const items = $input.all();
const out = [];
for (const it of items) {
  const j = it.json || {};
  const html = String(j.content || j.tavily_raw_content || '');
  const cleaned = html
    .replace(/<script[\s\S]*?<\/script>/gi, ' ')
    .replace(/<style[\s\S]*?<\/style>/gi, ' ')
    .replace(/<!--[\s\S]*?-->/g, ' ')
    .replace(/<noscript[\s\S]*?<\/noscript>/gi, ' ')
    .replace(/<[^>]+>/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
    .substring(0, 60000);
  out.push({ json: { ...j, tavily_raw_content: cleaned, tavily_content_len: cleaned.length, browserbase_used: true } });
}
return out;
"""

GEMINI_EXTRACT_JS = f"""
const API_KEY = {json.dumps(GEMINI_API_KEY)};
const SYSTEM = "You are extracting one product listing from an Indian marketplace page. " +
  "Return only a single JSON object. No markdown. No explanation. " +
  "If the page is a search, category, showroom, or wholesale listing page rather than a single product detail page, " +
  "set is_product_page to false and keep product_name, price_text, price_inr, image_urls, rating, and reviews_count as null. " +
  "Keys: product_name (string), price_text (string or null), price_inr (number or null), " +
  "description (string max 300 chars or null), image_urls (array of absolute URL strings), " +
  "marketplace (string domain like amazon.in or alibaba.com or null), rating (number 0-5 or null), " +
  "reviews_count (integer or null), in_stock (boolean or null), supplier_name (string or null), " +
  "is_product_page (boolean), reject_reason (string or null).";

const items = $input.all();
const out = [];
for (const it of items) {{
  const j = it.json || {{}};
  const url = j.tavily_url || '';
  const content = String(j.tavily_raw_content || '').slice(0, 60000);
  if (!url || content.length < 50) {{
    out.push({{ json: {{ ...j, gemini_extract_text: '', gemini_skipped: 'thin or missing input' }} }});
    continue;
  }}
  const prompt = SYSTEM
    + "\\n\\nURL: " + url
    + "\\nPage title: " + String(j.tavily_title || '')
    + "\\nMarketplace domain: " + String(j.tavily_domain || '')
    + "\\n\\nMarketplace page text:\\n" + content;
  try {{
    const res = await fetch(
      `https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-latest:generateContent?key=${{API_KEY}}`,
      {{
        method: 'POST',
        headers: {{ 'Content-Type': 'application/json' }},
        body: JSON.stringify({{
          generationConfig: {{ responseMimeType: 'application/json', temperature: 0.1 }},
          contents: [{{ parts: [{{ text: prompt }}] }}]
        }})
      }}
    );
    const data = await res.json();
    const text = (data?.candidates?.[0]?.content?.parts || [])
      .map(part => part?.text || '')
      .join('')
      .trim();
    out.push({{ json: {{ ...j, gemini_extract_text: text, gemini_status: res.status }} }});
  }} catch (e) {{
    out.push({{ json: {{ ...j, gemini_extract_text: '', gemini_error: String(e) }} }});
  }}
}}
return out;
"""

NORMALIZE_CJ_REVIEW_JS = r"""
function parseJson(value, fallback) {
  try { return JSON.parse(value); } catch { return fallback; }
}

const runDateFallback = new Date().toISOString().substring(0, 10);
return $input.all().flatMap((it) => {
  const j = it.json || {};
  const imageUrls = Array.isArray(j.image_urls) ? j.image_urls : parseJson(j.image_urls || '[]', []);
  const offers = Array.isArray(j.offers) ? j.offers : parseJson(j.offers || '[]', []);
  const offer = offers[0] || {};
  const rawPayload = typeof j.raw_payload === 'string' ? parseJson(j.raw_payload, j.raw_payload) : (j.raw_payload || {});
  const imageUrl = imageUrls[0] || null;
  if (!j.product_url || !j.source_topic || !j.product_name) return [];

  return [{
    json: {
      review_schema_version: 'hil_v1',
      workflow_name: 'EL',
      workflow_run_id: `EL:${j.run_date || runDateFallback}:${$execution.id || 'manual'}`,
      run_date: j.run_date || runDateFallback,
      source_provider: 'cj_dropshipping',
      source_topic: j.source_topic,
      source_pick_rank: j.source_pick_rank ?? null,
      opportunity_score: j.opportunity_score ?? null,
      product_name: j.product_name,
      product_url: j.product_url,
      product_sku: j.product_sku ?? null,
      price_text: j.price_text ?? null,
      price_numeric: j.price_numeric ?? null,
      currency: j.currency ?? 'USD',
      product_rating: null,
      reviews_count: null,
      image_url: imageUrl,
      image_urls: JSON.stringify(imageUrls),
      description: j.description ? String(j.description).substring(0, 300) : null,
      supplier_name: offer.supplierName ?? null,
      marketplace: 'cjdropshipping',
      availability_status: 'unknown',
      approval_status: 'pending',
      approval_channel: 'telegram',
      raw_payload: JSON.stringify({
        source: 'cj_dropshipping',
        offer,
        raw_payload: rawPayload,
      }),
      scraped_at: j.scraped_at || new Date().toISOString(),
    }
  }];
});
"""

NORMALIZE_BROWSERBASE_REVIEW_JS = r"""
function parseFirstJsonObject(text) {
  if (!text) return {};
  try {
    const m = String(text).match(/\{[\s\S]*\}/);
    return m ? JSON.parse(m[0]) : {};
  } catch {
    return {};
  }
}

function toNumber(value) {
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  const cleaned = String(value || '').replace(/,/g, '');
  const nums = cleaned.match(/[\d.]+/g);
  if (!nums || !nums.length) return null;
  const parsed = Number(nums[0]);
  return Number.isFinite(parsed) ? parsed : null;
}

function parseUrl(value) {
  try { return new URL(value); } catch { return null; }
}

function isSearchOrCollectionPage(urlObj) {
  if (!urlObj) return true;
  const path = urlObj.pathname.toLowerCase();
  const query = urlObj.searchParams;
  if (path === '/s' || query.has('k') || query.has('q') || query.has('keyword') || query.has('search')) return true;
  return /(showroom|wholesale|search|collections?|category|categories|browse|results)/.test(path);
}

function isLikelyProductPage(urlObj) {
  if (!urlObj || isSearchOrCollectionPage(urlObj)) return false;
  const path = urlObj.pathname.toLowerCase();
  if (/(\/dp\/|\/gp\/product\/|\/product\/|\/products\/|\/item\/|\/offer\/|\/p\/)/.test(path)) return true;
  const last = path.split('/').filter(Boolean).pop() || '';
  return /[a-z0-9][a-z0-9-]{7,}/.test(last);
}

function parseImageUrls(value) {
  if (Array.isArray(value)) return value.map(v => String(v || '').trim()).filter(v => /^https?:\/\//i.test(v));
  if (typeof value === 'string' && value.trim()) {
    try {
      const parsed = JSON.parse(value);
      if (Array.isArray(parsed)) return parsed.map(v => String(v || '').trim()).filter(v => /^https?:\/\//i.test(v));
    } catch {}
    if (/^https?:\/\//i.test(value.trim())) return [value.trim()];
  }
  return [];
}

function detectPriceText(text) {
  const match = String(text || '').match(/(?:₹|rs\.?|inr)\s*[0-9][0-9,]*(?:\.\d{1,2})?/i);
  return match ? match[0].replace(/\s+/g, ' ').trim() : null;
}

function detectRating(text) {
  const match = String(text || '').match(/\b([0-5](?:\.\d)?)\s*(?:out of 5|\/5|stars?)\b/i);
  return match ? toNumber(match[1]) : null;
}

function detectReviewsCount(text) {
  const match = String(text || '').match(/\b([0-9][0-9,]{0,10})\s*(?:ratings?|reviews?)\b/i);
  return match ? Math.round(toNumber(match[1])) : null;
}

function cleanTitle(title) {
  const text = String(title || '').trim();
  if (!text) return null;
  if (/^amazon\.in\s*:/i.test(text)) return null;
  if (/(showroom|wholesale|search results?|category)/i.test(text)) return null;
  return text
    .replace(/\s+\|\s+amazon\.in.*$/i, '')
    .replace(/\s+:\s+amazon\.in.*$/i, '')
    .replace(/\s+-\s+amazon\.in.*$/i, '')
    .replace(/\s+-\s+alibaba\.com.*$/i, '')
    .trim();
}

const runDateFallback = new Date().toISOString().substring(0, 10);
return $input.all().flatMap((it) => {
  const j = it.json || {};
  const extract = parseFirstJsonObject(j.gemini_extract_text);
  const urlObj = parseUrl(j.tavily_url);
  if (!j.tavily_url || !j.source_topic || !isLikelyProductPage(urlObj)) return [];

  const imageUrls = parseImageUrls(extract.image_urls);
  const imageUrl = imageUrls[0] || null;
  const inStock = extract.in_stock;
  let availability = 'unknown';
  if (inStock === true) availability = 'in_stock';
  if (inStock === false) availability = 'out_of_stock';
  const fallbackText = [j.tavily_title || '', j.tavily_raw_content || ''].join('\n');
  const rating = toNumber(extract.rating) ?? detectRating(fallbackText);
  const reviewsCountRaw = toNumber(extract.reviews_count) ?? detectReviewsCount(fallbackText);
  const reviewsCount = reviewsCountRaw == null ? null : Math.round(reviewsCountRaw);
  const priceText = extract.price_text || detectPriceText(fallbackText);
  const priceInr = toNumber(extract.price_inr) ?? toNumber(priceText);
  const marketplace = extract.marketplace || urlObj?.hostname || null;
  const productName = extract.product_name || cleanTitle(j.tavily_title);
  const hasReviewSignals = Boolean(priceText || imageUrl || rating != null || reviewsCount != null);
  if (extract.is_product_page === false) return [];
  if (!productName || !hasReviewSignals) return [];

  return [{
    json: {
      review_schema_version: 'hil_v1',
      workflow_name: 'EL',
      workflow_run_id: `EL:${j.run_date || runDateFallback}:${$execution.id || 'manual'}`,
      run_date: j.run_date || runDateFallback,
      source_provider: 'browserbase_marketplace',
      source_topic: j.source_topic,
      source_pick_rank: j.source_pick_rank ?? null,
      opportunity_score: j.opportunity_score ?? null,
      product_name: productName,
      product_url: j.tavily_url,
      product_sku: null,
      price_text: priceText,
      price_numeric: priceInr,
      currency: 'INR',
      product_rating: rating,
      reviews_count: reviewsCount,
      image_url: imageUrl,
      image_urls: JSON.stringify(imageUrls),
      description: extract.description ? String(extract.description).substring(0, 300) : null,
      supplier_name: extract.supplier_name || null,
      marketplace,
      availability_status: availability,
      approval_status: 'pending',
      approval_channel: 'telegram',
      raw_payload: JSON.stringify({
        source: 'browserbase_marketplace',
        tavily_score: j.tavily_score ?? null,
        tavily_title: j.tavily_title ?? null,
        tavily_domain: j.tavily_domain ?? null,
        browserbase_used: !!j.browserbase_used,
        gemini_status: j.gemini_status ?? null,
        gemini_error: j.gemini_error ?? null,
        extract,
      }),
      scraped_at: new Date().toISOString(),
    }
  }];
});
"""


def new_nodes() -> list[dict]:
    domains_js = json.dumps(INDIAN_MARKETPLACES)
    tavily_body_expr = (
        "={{ JSON.stringify({ "
        "query: $json.keyword, "
        "search_depth: 'advanced', "
        "max_results: 5, "
        "include_raw_content: true, "
        f"include_domains: {domains_js} "
        "}) }}"
    )
    return [
        {
            "parameters": {"jsCode": BUILD_TAVILY_QUERY_JS},
            "type": "n8n-nodes-base.code",
            "typeVersion": 2,
            "position": [980, 720],
            "id": "p3hil-btq-0001",
            "name": "Build Tavily Query",
            "onError": "continueErrorOutput",
        },
        {
            "parameters": {
                "method": "POST",
                "url": "https://api.tavily.com/search",
                "authentication": "genericCredentialType",
                "genericAuthType": "httpHeaderAuth",
                "sendBody": True,
                "specifyBody": "json",
                "jsonBody": tavily_body_expr,
                "options": {
                    "batching": {"batch": {"batchSize": 1, "batchInterval": 800}}
                },
            },
            "type": "n8n-nodes-base.httpRequest",
            "typeVersion": 4.2,
            "position": [1200, 720],
            "id": "p3hil-tav-0001",
            "name": "Tavily Search (IN Market)",
            "credentials": {"httpHeaderAuth": CRED_TAVILY},
            "onError": "continueErrorOutput",
            "retryOnFail": True,
            "maxTries": 3,
            "waitBetweenTries": 2000,
        },
        {
            "parameters": {"jsCode": PICK_INDIAN_LISTINGS_JS},
            "type": "n8n-nodes-base.code",
            "typeVersion": 2,
            "position": [1440, 720],
            "id": "p3hil-pil-0001",
            "name": "Pick Indian Listings",
            "onError": "continueErrorOutput",
        },
        {
            "parameters": {
                "conditions": {
                    "options": {"caseSensitive": True, "leftValue": "", "typeValidation": "strict"},
                    "conditions": [
                        {
                            "id": "thin-content-check",
                            "leftValue": "={{ ($json.tavily_content_len || 0) }}",
                            "rightValue": 500,
                            "operator": {"type": "number", "operation": "lt"},
                        }
                    ],
                    "combinator": "and",
                },
                "options": {},
            },
            "type": "n8n-nodes-base.if",
            "typeVersion": 2,
            "position": [1680, 720],
            "id": "p3hil-if-0001",
            "name": "If Tavily Content Thin",
        },
        {
            "parameters": {
                "method": "POST",
                "url": "https://api.browserbase.com/v1/fetch",
                "authentication": "genericCredentialType",
                "genericAuthType": "httpHeaderAuth",
                "sendBody": True,
                "specifyBody": "json",
                "jsonBody": "={{ JSON.stringify({ url: $json.tavily_url, allowRedirects: true, proxies: true }) }}",
                "options": {},
            },
            "type": "n8n-nodes-base.httpRequest",
            "typeVersion": 4.2,
            "position": [1680, 920],
            "id": "p3hil-bbf-0001",
            "name": "Browserbase Fetch",
            "credentials": {"httpHeaderAuth": CRED_BROWSERBASE},
            "onError": "continueErrorOutput",
        },
        {
            "parameters": {"jsCode": STRIP_HTML_JS},
            "type": "n8n-nodes-base.code",
            "typeVersion": 2,
            "position": [1920, 920],
            "id": "p3hil-strip-0001",
            "name": "Strip HTML",
            "onError": "continueErrorOutput",
        },
        {
            "parameters": {"jsCode": GEMINI_EXTRACT_JS},
            "type": "n8n-nodes-base.code",
            "typeVersion": 2,
            "position": [1920, 720],
            "id": "p3hil-gem-0001",
            "name": "Gemini Extract Product",
            "onError": "continueErrorOutput",
        },
        {
            "parameters": {"jsCode": NORMALIZE_CJ_REVIEW_JS},
            "type": "n8n-nodes-base.code",
            "typeVersion": 2,
            "position": [1680, 1160],
            "id": "p3hil-cjnorm-0001",
            "name": "Normalize CJ Review",
            "onError": "continueErrorOutput",
        },
        {
            "parameters": {"jsCode": NORMALIZE_BROWSERBASE_REVIEW_JS},
            "type": "n8n-nodes-base.code",
            "typeVersion": 2,
            "position": [2160, 720],
            "id": "p3hil-bbnorm-0001",
            "name": "Normalize Browserbase Review",
            "onError": "continueErrorOutput",
        },
        {
            "parameters": {
                "mode": "append",
                "numberInputs": 2,
            },
            "type": "n8n-nodes-base.merge",
            "typeVersion": 3,
            "position": [2400, 920],
            "id": "p3hil-merge-0001",
            "name": "Merge Review Sources",
        },
        {
            "parameters": {
                "operation": "upsert",
                "schema": {"__rl": True, "value": "private", "mode": "list"},
                "table": {"__rl": True, "value": "hil_reviews", "mode": "list"},
                "columns": {
                    "mappingMode": "autoMapInputData",
                    "value": {},
                    "matchingColumns": [
                        "workflow_run_id",
                        "source_provider",
                        "source_topic",
                        "product_url",
                    ],
                    "schema": [],
                },
                "options": {
                    "queryBatching": "independently"
                },
            },
            "type": "n8n-nodes-base.postgres",
            "typeVersion": 2.5,
            "position": [2640, 920],
            "id": "p3hil-pg-0001",
            "name": "Supabase Insert (HIL Reviews)",
            "credentials": {"postgres": POSTGRES_CRED},
            "continueOnFail": True,
        },
        {
            "parameters": {
                "color": 3,
                "width": 1360,
                "height": 360,
                "content": "## Phase 3b - Browserbase Marketplace Review\n\n"
                           "Parse Agent Output feeds a second discovery branch for Indian marketplaces.\n"
                           "Tavily finds product pages, Browserbase fills thin pages, Gemini extracts product fields,\n"
                           "and Normalize Browserbase Review converts the result into the exact HITL contract.",
            },
            "type": "n8n-nodes-base.stickyNote",
            "typeVersion": 1,
            "position": [930, 640],
            "id": "p3hil-sticky-0001",
            "name": "cluster:phase3b-browserbase-review",
        },
        {
            "parameters": {
                "color": 7,
                "width": 1080,
                "height": 260,
                "content": "## Phase 3d - HITL Review Queue\n\n"
                           "Normalize CJ Review and Normalize Browserbase Review both emit the same `private.hil_reviews`\n"
                           "row shape. Merge Review Sources collects them and Supabase Insert (HIL Reviews) upserts the queue.",
            },
            "type": "n8n-nodes-base.stickyNote",
            "typeVersion": 1,
            "position": [1610, 1040],
            "id": "p3hil-sticky-0002",
            "name": "cluster:phase3d-hil-review-queue",
        },
    ]


def clean_connections(connections: dict) -> dict:
    cleaned: dict = {}
    for src, ports in connections.items():
        if src in PHASE3_NODE_NAMES:
            continue
        cleaned_ports: dict = {}
        for port_name, branches in ports.items():
            cleaned_ports[port_name] = []
            for branch in branches:
                cleaned_ports[port_name].append(
                    [c for c in branch if c.get("node") not in PHASE3_NODE_NAMES]
                )
        cleaned[src] = cleaned_ports
    return cleaned


def ensure_error_branch(connections: dict, node_name: str):
    entry = connections.setdefault(node_name, {"main": [[], []]})
    main = entry.setdefault("main", [[], []])
    while len(main) < 2:
        main.append([])
    if not any(c.get("node") == "Error Formatter" for c in main[1]):
        main[1].append({"node": "Error Formatter", "type": "main", "index": 0})


def main():
    status, workflow = http("GET", f"/workflows/{WORKFLOW_ID}")
    if status != 200:
        raise SystemExit(f"Failed to fetch workflow: {status} {workflow}")

    nodes = [n for n in workflow["nodes"] if n["name"] not in PHASE3_NODE_NAMES]
    nodes.extend(new_nodes())

    connections = clean_connections(workflow["connections"])

    parse_agent = connections.setdefault("Parse Agent Output", {"main": [[], []]})
    while len(parse_agent["main"]) < 2:
        parse_agent["main"].append([])
    if not any(c.get("node") == "Build Tavily Query" for c in parse_agent["main"][0]):
        parse_agent["main"][0].append({"node": "Build Tavily Query", "type": "main", "index": 0})

    pick_top_3 = connections.setdefault("Pick Top 3", {"main": [[], []]})
    while len(pick_top_3["main"]) < 2:
        pick_top_3["main"].append([])
    if not any(c.get("node") == "Normalize CJ Review" for c in pick_top_3["main"][0]):
        pick_top_3["main"][0].append({"node": "Normalize CJ Review", "type": "main", "index": 0})

    connections["Build Tavily Query"] = {
        "main": [
            [{"node": "Tavily Search (IN Market)", "type": "main", "index": 0}],
            [{"node": "Error Formatter", "type": "main", "index": 0}],
        ]
    }
    connections["Tavily Search (IN Market)"] = {
        "main": [
            [{"node": "Pick Indian Listings", "type": "main", "index": 0}],
            [{"node": "Error Formatter", "type": "main", "index": 0}],
        ]
    }
    connections["Pick Indian Listings"] = {
        "main": [
            [{"node": "If Tavily Content Thin", "type": "main", "index": 0}],
            [{"node": "Error Formatter", "type": "main", "index": 0}],
        ]
    }
    connections["If Tavily Content Thin"] = {
        "main": [
            [{"node": "Browserbase Fetch", "type": "main", "index": 0}],
            [{"node": "Gemini Extract Product", "type": "main", "index": 0}],
        ]
    }
    connections["Browserbase Fetch"] = {
        "main": [
            [{"node": "Strip HTML", "type": "main", "index": 0}],
            [{"node": "Error Formatter", "type": "main", "index": 0}],
        ]
    }
    connections["Strip HTML"] = {
        "main": [
            [{"node": "Gemini Extract Product", "type": "main", "index": 0}],
            [{"node": "Error Formatter", "type": "main", "index": 0}],
        ]
    }
    connections["Gemini Extract Product"] = {
        "main": [
            [{"node": "Normalize Browserbase Review", "type": "main", "index": 0}],
            [{"node": "Error Formatter", "type": "main", "index": 0}],
        ]
    }
    connections["Normalize CJ Review"] = {
        "main": [
            [{"node": "Merge Review Sources", "type": "main", "index": 0}],
            [{"node": "Error Formatter", "type": "main", "index": 0}],
        ]
    }
    connections["Normalize Browserbase Review"] = {
        "main": [
            [{"node": "Merge Review Sources", "type": "main", "index": 1}],
            [{"node": "Error Formatter", "type": "main", "index": 0}],
        ]
    }
    connections["Merge Review Sources"] = {
        "main": [[
            {"node": "Supabase Insert (HIL Reviews)", "type": "main", "index": 0},
        ]]
    }

    ensure_error_branch(connections, "Normalize CJ Review")
    ensure_error_branch(connections, "Normalize Browserbase Review")

    body = {
        "name": workflow["name"],
        "nodes": nodes,
        "connections": connections,
        "settings": {
            "executionOrder": (workflow.get("settings") or {}).get("executionOrder", "v1"),
            "errorWorkflow": (workflow.get("settings") or {}).get("errorWorkflow"),
        },
    }
    body["settings"] = {k: v for k, v in body["settings"].items() if v is not None}
    status, result = http("PUT", f"/workflows/{WORKFLOW_ID}", body)
    if status >= 300:
        raise SystemExit(f"Failed to update workflow: {status} {result}")

    print("OK", status)
    print("versionId", result.get("versionId"))
    print("nodes", len(nodes))
    print("Parse Agent Output ->", [c["node"] for c in connections["Parse Agent Output"]["main"][0]])
    print("Pick Top 3 ->", [c["node"] for c in connections["Pick Top 3"]["main"][0]])
    print("Merge Review Sources ->", [c["node"] for c in connections["Merge Review Sources"]["main"][0]])


if __name__ == "__main__":
    main()
