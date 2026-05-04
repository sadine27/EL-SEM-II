const fs = require("fs");
const path = require("path");

const ROOT = path.join(__dirname, "..");
const WORKFLOW_PATH = path.join(ROOT, "el_workflow.json");
const ENV_PATH = path.join(ROOT, ".env");
const WORKFLOW_ID = "298f3JSOE72nhW59";
const HIL_CHAT_ID = "8243518279";

const candidateSelectionJs = String.raw`
const MIN_SCORE = 25;
const FALLBACK_MIN_SCORE = 20;
const FALLBACK_MAX_ITEMS = 2;
const TOPIC_CAP = 2;
const CJ_PROVIDER_CAP = 5;
const BROWSERBASE_PROVIDER_CAP = 7;
const TOTAL_CAP = 10;

const STOP = new Set([
  'the', 'and', 'for', 'with', 'from', 'that', 'this', 'your', 'into', 'online',
  'india', 'buy', 'shop', 'store', 'official', 'new', 'latest', 'best'
]);
const TOPIC_NOISE = new Set([
  'trailer', 'teaser', 'official', 'movie', 'season', 'episode', 'youtube', 'news',
  'video', 'song', 'lyrics', 'review', 'return', 'returns', 'opening', 'challenge',
  'build', 'back', 'everyone', 'nerdy'
]);
const GENERIC_PRODUCT_TERMS = [
  't shirt', 'tshirt', 'shirt', 'hoodie', 'poster', 'mug', 'keychain', 'sticker',
  'phone case', 'cover', 'jersey', 'figurine', 'action figure', 'collectible',
  'merchandise', 'plush', 'toy', 'mouse pad', 'desk mat', 'notebook', 'cap'
];
const ALLOWED_MEDIA_PRODUCT_TERMS = [
  't shirt', 'tshirt', 'shirt', 'hoodie', 'poster', 'mug', 'keychain', 'sticker',
  'phone case', 'cover', 'figurine', 'action figure', 'collectible', 'plush',
  'toy', 'mouse pad', 'desk mat', 'notebook', 'cap'
];
const ALLOWED_GAMING_PRODUCT_TERMS = [
  'mouse pad', 'desk mat', 'phone case', 'cover', 'sticker', 'poster', 'hoodie',
  't shirt', 'tshirt', 'shirt', 'mug', 'keychain', 'figurine', 'action figure',
  'collectible', 'controller skin', 'controller grip', 'gaming sleeve'
];
const HARD_BLOCK_TERMS = [
  'repair tool', 'tool box', 'opening tool', 'service hard case', 'hard case',
  'skin care lotion', 'pruritus', 'earrings', 'flats', 'dress', 'sleeveless',
  'women s shoes', 'ointment', 'cream', 'medical', 'body care', 'shoe', 'shoes',
  'heels', 'sandals'
];
const ENTERTAINMENT_TERMS = [
  'trailer', 'teaser', 'movie', 'season', 'episode', 'song', 'lyrics', 'youtube',
  'music', 'video', 'album', 'gana', 'gaana', 'magahi', 'bhojpuri', 'punjabi',
  'singer', 'artist', 'official video', 'new song'
];
const CJ_ENTERTAINMENT_BLOCKLIST = [
  'flats', 'earrings', 'dress', 'sleeveless', 'body care', 'medical', 'ointment',
  'cream', 'skin care', 'pruritus', 'women s shoes', 'soft bottomed', 'lightweight shoes'
];
const GAMING_TERMS = [
  'bgmi', 'pubg', 'gta', 'gameplay', 'gaming', 'gamer', 'franklin', 'mr meat',
  'indian bike driving', '3d', 'jonathan', 'battlegrounds'
];
const ENTITY_FAMILIES = [
  { topic: ['wolverine', 'ultron', 'avengers', 'wakanda', 'marvel', 'doomsday', 'hulk'], product: ['marvel', 'wolverine', 'ultron', 'avengers', 'wakanda', 'hulk', 'iron man', 'captain america', 'thor'] },
  { topic: ['bgmi', 'pubg', 'jonathan', 'battlegrounds'], product: ['bgmi', 'pubg', 'battlegrounds', 'gaming', 'gamer', 'joystick', 'controller', 'mouse pad'] },
  { topic: ['sidhu', 'moose', 'wala'], product: ['sidhu', 'moose', 'wala', 'punjabi', 'music', 'singer', 'artist'] },
  { topic: ['ashish', 'khushi', 'amarpali', 'nache'], product: ['ashish', 'khushi', 'amarpali', 'music', 'song', 'artist', 'poster', 't shirt'] },
];
const TERMINAL_REJECTION_STAGES = new Set(['reviewability', 'mismatch', 'dedupe', 'cap']);
const TERMINAL_REJECTION_CODES = new Set([
  'missing_product_name',
  'missing_product_url',
  'missing_source_topic',
  'bad_product_url',
  'out_of_stock',
  'missing_price_and_image',
  'hard_block_term',
  'browserbase_repair_tool',
  'cj_not_listed',
  'cj_blocked_category',
  'gaming_missing_allowed_noun',
  'gaming_missing_entity_signal',
  'media_missing_allowed_noun',
  'media_missing_entity_signal',
  'direct_product_hard_block',
  'duplicate_candidate',
  'topic_cap_reached',
  'provider_cap_reached',
  'total_cap_reached',
]);

function compact(value) {
  return String(value || '').replace(/\s+/g, ' ').trim();
}

function normalizeText(value) {
  return compact(value)
    .toLowerCase()
    .replace(/[^a-z0-9\s]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

function tokenize(value) {
  return normalizeText(value)
    .split(' ')
    .filter((token) => token.length > 2 && !STOP.has(token));
}

function toNumber(value) {
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  const text = compact(value).replace(/,/g, '');
  if (!text) return null;
  const match = text.match(/-?\d+(?:\.\d+)?/);
  if (!match) return null;
  const parsed = Number(match[0]);
  return Number.isFinite(parsed) ? parsed : null;
}

function matchedTerms(text, terms) {
  const normalized = normalizeText(text);
  const matches = [];
  for (const term of terms) {
    const needle = normalizeText(term);
    if (needle && (' ' + normalized + ' ').includes(' ' + needle + ' ')) {
      matches.push(needle);
    }
  }
  return Array.from(new Set(matches));
}

function countTermMatches(text, terms) {
  return matchedTerms(text, terms).length;
}

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

function safeUrl(value) {
  try {
    return new URL(String(value || '').trim());
  } catch {
    return null;
  }
}

function extractHostname(value) {
  const match = compact(value).match(/^https?:\/\/([^\/?#]+)/i);
  return match ? String(match[1]).toLowerCase() : null;
}

function canonicalUrl(value) {
  const parsed = safeUrl(value);
  if (!parsed) return compact(value).toLowerCase();
  parsed.hash = '';
  const keep = ['pid', 'sku', 'id', 'product_id'];
  const params = new URLSearchParams();
  for (const key of keep) {
    const param = parsed.searchParams.get(key);
    if (param) params.set(key, param);
  }
  parsed.search = params.toString() ? '?' + params.toString() : '';
  return parsed.toString().replace(/\/$/, '');
}

function hostOf(value) {
  const parsed = safeUrl(value);
  if (parsed && parsed.hostname) return parsed.hostname.toLowerCase();
  const fallback = extractHostname(value);
  return fallback || compact(value).toLowerCase();
}

function imageKey(value) {
  const parsed = safeUrl(value);
  if (!parsed) return null;
  parsed.search = '';
  parsed.hash = '';
  return parsed.toString().replace(/\/$/, '');
}

function overlapRatio(a, b) {
  if (!a.size || !b.size) return 0;
  let overlap = 0;
  for (const item of a) {
    if (b.has(item)) overlap += 1;
  }
  return overlap / Math.min(a.size, b.size);
}

function looksBadUrl(value) {
  const text = compact(value).toLowerCase();
  return /[?&](q|k|keyword|search)=/.test(text)
    || /\/s(\?|\/|$)/.test(text)
    || /(search|showroom|wholesale|collection|collections|category|categories|browse|results|blog|article)/.test(text);
}

function parseRawPayload(value) {
  if (!value) return {};
  if (typeof value === 'object' && !Array.isArray(value)) return value;
  try {
    return JSON.parse(value);
  } catch {
    return { raw: value };
  }
}

function topicTokensForMatch(text) {
  return tokenize(text).filter((token) => !TOPIC_NOISE.has(token));
}

function classifyTopicIntent(text) {
  const normalized = normalizeText(text);
  const entertainmentHits = countTermMatches(normalized, ENTERTAINMENT_TERMS);
  const gamingHits = countTermMatches(normalized, GAMING_TERMS);
  const hashtagHits = (String(text || '').match(/#\S+/g) || []).length;
  const separatorHits = (String(text || '').match(/[|&]|\bft\b|\bfeat\b/ig) || []).length;
  if (gamingHits > 0) return 'gaming_merch';
  if (entertainmentHits > 0 || hashtagHits >= 2 || separatorHits >= 2) return 'media_merch';
  return 'direct_product';
}

function entertainmentTopicSignals(text) {
  const normalized = normalizeText(text);
  const termHits = countTermMatches(normalized, ENTERTAINMENT_TERMS);
  const hashtagHits = (String(text || '').match(/#\S+/g) || []).length;
  const quotedEntityHits = (String(text || '').match(/[|&]|\bft\b|\bfeat\b/ig) || []).length;
  return {
    termHits,
    hashtagHits,
    quotedEntityHits,
    isEntertainment:
      termHits > 0
      || hashtagHits >= 2
      || quotedEntityHits >= 2
      || /\b(video|gana|gaana|song|lyrics|teaser|trailer)\b/i.test(String(text || '')),
  };
}

function overlapCount(a, b) {
  if (!a.size || !b.size) return 0;
  let overlap = 0;
  for (const item of a) {
    if (b.has(item)) overlap += 1;
  }
  return overlap;
}

function previewText(text, maxLength) {
  const value = compact(text);
  return value.length > maxLength ? value.slice(0, maxLength - 1) + '…' : value;
}

function buildContext(row, rawPayload) {
  const productCoreText = [
    row.product_name,
    row.description,
    row.supplier_name,
    row.marketplace,
    rawPayload?.extract?.description,
    rawPayload?.extract?.product_name,
    rawPayload?.extract?.supplier_name,
    rawPayload?.offer?.categoryName,
    rawPayload?.raw_payload?.categoryName,
    rawPayload?.raw_payload?.productNameEn,
    rawPayload?.raw_payload?.productName,
  ].filter(Boolean).join(' ');
  const productText = [
    productCoreText,
    rawPayload?.tavily_query,
    rawPayload?.tavily_title,
  ].filter(Boolean).join(' ');
  const topicText = [row.source_topic, rawPayload?.tavily_query].filter(Boolean).join(' ');
  const topicTokens = new Set(topicTokensForMatch(topicText));
  const productTokens = new Set(tokenize(productText));
  const topicOverlap = overlapCount(topicTokens, productTokens);
  const genericMerchTerms = matchedTerms(productCoreText, GENERIC_PRODUCT_TERMS);
  const mediaAllowedTerms = matchedTerms(productCoreText, ALLOWED_MEDIA_PRODUCT_TERMS);
  const gamingAllowedTerms = matchedTerms(productCoreText, ALLOWED_GAMING_PRODUCT_TERMS);
  const hardBlockTerms = matchedTerms(productCoreText, HARD_BLOCK_TERMS);
  const cjBlockedTerms = matchedTerms(productCoreText, CJ_ENTERTAINMENT_BLOCKLIST);
  const browserbaseEntityMatches = toNumber(rawPayload?.tavily_entity_matches) ?? 0;
  const browserbaseProductMatches = toNumber(rawPayload?.tavily_product_matches) ?? 0;
  const listedNum = toNumber(rawPayload?.offer?.listedNum ?? rawPayload?.raw_payload?.listedNum);
  const topicSignals = entertainmentTopicSignals(topicText);
  const topicIntentType = classifyTopicIntent(topicText);
  const mediaTopic = topicIntentType !== 'direct_product';
  const normalizedTopicText = normalizeText(topicText);
  const normalizedProductText = normalizeText(productText);
  const normalizedProductCoreText = normalizeText(productCoreText);
  const familyMatches = [];

  for (const family of ENTITY_FAMILIES) {
    const topicHits = family.topic.filter((term) => normalizedTopicText.includes(normalizeText(term)));
    const productHits = family.product.filter((term) => normalizedProductText.includes(normalizeText(term)));
    if (topicHits.length && productHits.length) {
      familyMatches.push({
        topic_terms: Array.from(new Set(topicHits.map((term) => normalizeText(term)))),
        product_terms: Array.from(new Set(productHits.map((term) => normalizeText(term)))),
      });
    }
  }

  return {
    productCoreText,
    productText,
    topicText,
    topicTokens,
    productTokens,
    topicOverlap,
    genericMerchTerms,
    genericMerchMatches: genericMerchTerms.length,
    mediaAllowedTerms,
    mediaAllowedMatches: mediaAllowedTerms.length,
    gamingAllowedTerms,
    gamingAllowedMatches: gamingAllowedTerms.length,
    hardBlockTerms,
    hardBlockMatches: hardBlockTerms.length,
    cjBlockedTerms,
    browserbaseEntityMatches,
    browserbaseProductMatches,
    listedNum,
    mediaTopic,
    topicIntentType,
    topicSignals,
    familyMatch: familyMatches.length > 0,
    familyMatches,
    normalizedTopicText,
    normalizedProductText,
    normalizedProductCoreText,
  };
}

function buildReason(stage, code, message, details) {
  return {
    stage,
    code,
    message,
    details: details || {},
  };
}

function hasTerminalRejection(candidate) {
  return candidate.rejectionReasons.some((reason) => (
    TERMINAL_REJECTION_STAGES.has(reason.stage)
    || TERMINAL_REJECTION_CODES.has(reason.code)
  ));
}

function hasOnlyScoreRejections(candidate) {
  return candidate.rejectionReasons.length > 0
    && candidate.rejectionReasons.every((reason) => reason.stage === 'score');
}

function hasFallbackEvidence(candidate) {
  const row = candidate.row || {};
  const context = candidate.context || {};
  const price = toNumber(row.price_numeric);
  const hasCommercialSignal = Boolean(row.image_url && (row.price_text || price != null));
  const hasTopicSignal = context.topicOverlap > 0
    || context.familyMatch
    || (context.browserbaseEntityMatches || 0) > 0
    || context.topicIntentType === 'direct_product';
  return hasCommercialSignal && hasTopicSignal;
}

function mismatchReasons(row, context) {
  const reasons = [];
  const hasEntitySignal = context.topicOverlap > 0 || context.familyMatch || context.browserbaseEntityMatches > 0;
  const hasAllowedMediaNoun = context.mediaAllowedMatches > 0;
  const hasAllowedGamingNoun = context.gamingAllowedMatches > 0;

  if (context.hardBlockTerms.length > 0) {
    reasons.push(buildReason(
      'mismatch',
      'hard_block_term',
      'Blocked because the product text contains banned drift terms.',
      { matched_terms: context.hardBlockTerms }
    ));
  }

  if (
    row.source_provider === 'browserbase_marketplace'
    && /repair tool|tool box|opening tool|service hard case|hard case/.test(context.normalizedProductCoreText)
  ) {
    reasons.push(buildReason(
      'mismatch',
      'browserbase_repair_tool',
      'Blocked browserbase result because the product looks like a repair tool or service case.',
      { matched_terms: matchedTerms(context.productCoreText, ['repair tool', 'tool box', 'opening tool', 'service hard case', 'hard case']) }
    ));
  }

  if (row.source_provider === 'cj_dropshipping' && context.listedNum != null && context.listedNum <= 0) {
    reasons.push(buildReason(
      'mismatch',
      'cj_not_listed',
      'Blocked CJ product because listedNum is missing or non-positive.',
      { listed_num: context.listedNum }
    ));
  }

  if (row.source_provider === 'cj_dropshipping' && context.cjBlockedTerms.length > 0) {
    reasons.push(buildReason(
      'mismatch',
      'cj_blocked_category',
      'Blocked CJ product because it falls into an entertainment-topic category blocklist.',
      { matched_terms: context.cjBlockedTerms }
    ));
  }

  if (context.topicIntentType === 'gaming_merch' && !hasAllowedGamingNoun) {
    reasons.push(buildReason(
      'mismatch',
      'gaming_missing_allowed_noun',
      'Blocked gaming topic because the product text has no allowed gaming merch noun.',
      { allowed_terms_found: context.gamingAllowedTerms }
    ));
  }

  if (context.topicIntentType === 'gaming_merch' && !hasEntitySignal) {
    reasons.push(buildReason(
      'mismatch',
      'gaming_missing_entity_signal',
      'Blocked gaming topic because the product has no topic/entity overlap.',
      {
        topic_overlap: context.topicOverlap,
        family_match: context.familyMatch,
        browserbase_entity_matches: context.browserbaseEntityMatches,
      }
    ));
  }

  if (context.topicIntentType === 'media_merch' && !hasAllowedMediaNoun) {
    reasons.push(buildReason(
      'mismatch',
      'media_missing_allowed_noun',
      'Blocked media topic because the product text has no allowed merch noun.',
      { allowed_terms_found: context.mediaAllowedTerms }
    ));
  }

  if (context.topicIntentType === 'media_merch' && !hasEntitySignal) {
    reasons.push(buildReason(
      'mismatch',
      'media_missing_entity_signal',
      'Blocked media topic because the product has no topic/entity overlap.',
      {
        topic_overlap: context.topicOverlap,
        family_match: context.familyMatch,
        browserbase_entity_matches: context.browserbaseEntityMatches,
      }
    ));
  }

  if (context.topicIntentType === 'direct_product' && context.hardBlockMatches > 0 && !hasEntitySignal) {
    reasons.push(buildReason(
      'mismatch',
      'direct_product_hard_block',
      'Blocked direct-product topic because the item only matches banned drift terms and lacks entity support.',
      {
        matched_terms: context.hardBlockTerms,
        topic_overlap: context.topicOverlap,
        family_match: context.familyMatch,
        browserbase_entity_matches: context.browserbaseEntityMatches,
      }
    ));
  }

  return reasons;
}

function selectionScore(row, context) {
  const opportunity = toNumber(row.opportunity_score) ?? 0;
  const pickRank = toNumber(row.source_pick_rank);
  const rating = toNumber(row.product_rating);
  const reviews = toNumber(row.reviews_count);
  const price = toNumber(row.price_numeric);
  const availability = compact(row.availability_status).toLowerCase();
  const host = hostOf(row.product_url || row.marketplace || '');

  let score = 0;
  score += clamp(opportunity, 0, 10) * 6;
  if (pickRank != null) score += clamp(12 - pickRank, 0, 10) * 1.8;
  if (rating != null) score += clamp(rating, 0, 5) * 4;
  if (reviews != null) score += clamp(Math.log10(reviews + 1) * 8, 0, 22);
  if (row.image_url) score += 7;
  if (row.price_text || price != null) score += 5;
  if (row.description) score += 3;
  if (availability === 'in_stock') score += 4;
  if (availability === 'out_of_stock') score -= 20;
  if (looksBadUrl(row.product_url)) score -= 20;
  if (/amazon\.in|flipkart\.com|myntra\.com|ajio\.com|nykaa\.com|meesho\.com|croma\.com|firstcry\.com/.test(host)) score += 4;
  if (row.source_provider === 'browserbase_marketplace') score += 2;
  if (row.source_provider === 'cj_dropshipping') score += 1;
  if (price != null && price > 0) score += 2;
  if (context.topicOverlap > 0) score += clamp(context.topicOverlap * 6, 0, 18);
  if (context.familyMatch) score += 8;
  if (context.genericMerchMatches > 0) score += clamp(context.genericMerchMatches * 2, 0, 8);
  if (context.browserbaseEntityMatches > 0) score += clamp(context.browserbaseEntityMatches * 5, 0, 15);
  if (context.browserbaseProductMatches > 0) score += clamp(context.browserbaseProductMatches * 3, 0, 9);
  if (context.hardBlockMatches > 0) score -= clamp(context.hardBlockMatches * 20, 0, 60);
  if (context.mediaTopic && context.topicOverlap === 0 && !context.familyMatch) score -= 25;
  if (!row.product_name) score -= 100;
  if (!row.product_url) score -= 100;
  return Math.round(score * 100) / 100;
}

function reviewabilityReasons(row, context) {
  const reasons = [];

  if (!compact(row.product_name)) {
    reasons.push(buildReason('reviewability', 'missing_product_name', 'Blocked because product_name is empty.'));
  }
  if (!compact(row.product_url)) {
    reasons.push(buildReason('reviewability', 'missing_product_url', 'Blocked because product_url is empty.'));
  }
  if (!compact(row.source_topic)) {
    reasons.push(buildReason('reviewability', 'missing_source_topic', 'Blocked because source_topic is empty.'));
  }
  if (looksBadUrl(row.product_url)) {
    reasons.push(buildReason('reviewability', 'bad_product_url', 'Blocked because the URL looks like a search/listing page.', {
      product_url: row.product_url,
    }));
  }
  if (compact(row.availability_status).toLowerCase() === 'out_of_stock') {
    reasons.push(buildReason('reviewability', 'out_of_stock', 'Blocked because the item is marked out of stock.'));
  }
  if (!row.image_url && !row.price_text && toNumber(row.price_numeric) == null) {
    reasons.push(buildReason(
      'reviewability',
      'missing_price_and_image',
      'Blocked because the candidate has neither image nor price signal.'
    ));
  }

  reasons.push(...mismatchReasons(row, context));
  return reasons;
}

function buildDiagnostics(entry) {
  return {
    decision: entry.selected ? 'selected' : 'rejected',
    score: entry.score,
    min_score: MIN_SCORE,
    topic_intent_type: entry.context.topicIntentType,
    source_provider: compact(entry.row.source_provider).toLowerCase() || null,
    source_host: entry.host || null,
    dedupe_name_key: entry.normalizedName || null,
    topic_overlap: entry.context.topicOverlap,
    family_match: entry.context.familyMatch,
    family_matches: entry.context.familyMatches,
    browserbase_entity_matches: entry.context.browserbaseEntityMatches,
    browserbase_product_matches: entry.context.browserbaseProductMatches,
    generic_merch_terms: entry.context.genericMerchTerms,
    media_allowed_terms: entry.context.mediaAllowedTerms,
    gaming_allowed_terms: entry.context.gamingAllowedTerms,
    hard_block_terms: entry.context.hardBlockTerms,
    cj_blocked_terms: entry.context.cjBlockedTerms,
    listed_num: entry.context.listedNum,
    topic_signals: entry.context.topicSignals,
    product_text_preview: previewText(entry.context.productCoreText, 220),
    topic_text_preview: previewText(entry.context.topicText, 180),
    rejection_reasons: entry.rejectionReasons,
  };
}

function attachPayload(entry, selection) {
  const diagnostics = buildDiagnostics(entry);
  const rawPayload = {
    ...entry.rawPayload,
    phase4_selection: selection || null,
    phase4_debug: diagnostics,
  };
  return {
    ...entry.row,
    raw_payload: JSON.stringify(rawPayload),
  };
}

const input = $input.all().map((item) => item.json || {});
const prepared = input.map((row) => {
  const nameTokens = new Set(tokenize(row.product_name));
  const normalizedName = Array.from(nameTokens).join(' ');
  const url = canonicalUrl(row.product_url);
  const img = imageKey(row.image_url);
  const rawPayload = parseRawPayload(row.raw_payload);
  const context = buildContext(row, rawPayload);
  const score = selectionScore(row, context);
  const rejectionReasons = reviewabilityReasons(row, context);

  if (score < MIN_SCORE) {
    rejectionReasons.push(buildReason(
      'score',
      'below_min_score',
      'Blocked because the candidate score is below the phase 4 threshold.',
      { score, min_score: MIN_SCORE }
    ));
  }

  return {
    row,
    score,
    url,
    img,
    host: hostOf(row.product_url || row.marketplace || ''),
    normalizedName,
    nameTokens,
    rawPayload,
    context,
    rejectionReasons,
    selected: false,
  };
});

const eligible = prepared.filter((entry) => entry.rejectionReasons.length === 0);

eligible.sort((a, b) => {
  if (b.score !== a.score) return b.score - a.score;
  const oppA = toNumber(a.row.opportunity_score) ?? -1;
  const oppB = toNumber(b.row.opportunity_score) ?? -1;
  if (oppB !== oppA) return oppB - oppA;
  const rankA = toNumber(a.row.source_pick_rank) ?? 999;
  const rankB = toNumber(b.row.source_pick_rank) ?? 999;
  return rankA - rankB;
});

const deduped = [];
for (const candidate of eligible) {
  let duplicateOf = null;
  for (const kept of deduped) {
    const sameUrl = candidate.url && kept.url && candidate.url === kept.url;
    const sameImage = candidate.img && kept.img && candidate.img === kept.img;
    const sameTopic = normalizeText(candidate.row.source_topic) === normalizeText(kept.row.source_topic);
    const sameHost = candidate.host && kept.host && candidate.host === kept.host;
    const similarName = overlapRatio(candidate.nameTokens, kept.nameTokens) >= 0.8;
    if (sameUrl || sameImage || (sameTopic && sameHost && similarName)) {
      duplicateOf = kept;
      break;
    }
  }
  if (duplicateOf) {
    candidate.rejectionReasons.push(buildReason(
      'dedupe',
      'duplicate_candidate',
      'Blocked because a higher-ranked near-duplicate was already kept.',
      {
        duplicate_of_product: duplicateOf.row.product_name || null,
        duplicate_of_url: duplicateOf.row.product_url || null,
        duplicate_of_score: duplicateOf.score,
      }
    ));
    continue;
  }
  deduped.push(candidate);
}

const perTopicCounts = new Map();
const providerCounts = new Map();
const selected = [];
for (const candidate of deduped) {
  const topicKey = normalizeText(candidate.row.source_topic);
  const providerKey = compact(candidate.row.source_provider).toLowerCase();
  const topicCount = perTopicCounts.get(topicKey) || 0;
  const providerCount = providerCounts.get(providerKey) || 0;

  if (topicCount >= TOPIC_CAP) {
    candidate.rejectionReasons.push(buildReason(
      'cap',
      'topic_cap_reached',
      'Blocked because this topic already reached the phase 4 queue cap.',
      { topic_cap: TOPIC_CAP, topic: candidate.row.source_topic }
    ));
    continue;
  }

  if (providerKey === 'cj_dropshipping' && providerCount >= CJ_PROVIDER_CAP) {
    candidate.rejectionReasons.push(buildReason(
      'cap',
      'provider_cap_reached',
      'Blocked because the CJ provider cap was reached.',
      { provider_cap: CJ_PROVIDER_CAP, source_provider: providerKey }
    ));
    continue;
  }

  if (providerKey === 'browserbase_marketplace' && providerCount >= BROWSERBASE_PROVIDER_CAP) {
    candidate.rejectionReasons.push(buildReason(
      'cap',
      'provider_cap_reached',
      'Blocked because the browserbase provider cap was reached.',
      { provider_cap: BROWSERBASE_PROVIDER_CAP, source_provider: providerKey }
    ));
    continue;
  }

  if (selected.length >= TOTAL_CAP) {
    candidate.rejectionReasons.push(buildReason(
      'cap',
      'total_cap_reached',
      'Blocked because the overall phase 4 queue cap was reached.',
      { total_cap: TOTAL_CAP }
    ));
    continue;
  }

  perTopicCounts.set(topicKey, topicCount + 1);
  providerCounts.set(providerKey, providerCount + 1);
  candidate.selected = true;
  selected.push(candidate);
}

if (selected.length === 0) {
  const fallbackPool = prepared
    .filter((candidate) => {
      if (hasTerminalRejection(candidate)) return false;
      if (!hasOnlyScoreRejections(candidate)) return false;
      if (!hasFallbackEvidence(candidate)) return false;
      if (candidate.score < FALLBACK_MIN_SCORE) return false;
      return true;
    })
    .sort((a, b) => b.score - a.score);

  for (const candidate of fallbackPool) {
    if (selected.length >= FALLBACK_MAX_ITEMS) break;
    candidate.selected = true;
    candidate.rejectionReasons = candidate.rejectionReasons.filter((reason) => reason.stage !== 'score');
    candidate.rejectionReasons.push(buildReason(
      'fallback',
      'fallback_selected',
      'Selected by fallback because strict phase 4 produced an empty queue.',
      { score: candidate.score, fallback_min_score: FALLBACK_MIN_SCORE }
    ));
    selected.push(candidate);
  }
}

const selectedOutput = selected.map((candidate, index) => {
  const selection = {
    phase: 'phase4_candidate_selection',
    topic_intent_type: candidate.context.topicIntentType,
    confidence_score: candidate.score,
    queue_rank: index + 1,
    selected_at: new Date().toISOString(),
    source_host: candidate.host || null,
    dedupe_name_key: candidate.normalizedName || null,
  };
  return {
    json: attachPayload(candidate, selection),
  };
});

return selectedOutput;
`;

const telegramCardPrepJs = String.raw`
const CHAT_ID = '8243518279';
const MAX_CAPTION_LENGTH = 900;

function compact(value) {
  return String(value ?? '').replace(/\s+/g, ' ').trim();
}

function escapeHtml(value) {
  return compact(value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function truncate(value, maxLength) {
  const text = compact(value);
  return text.length > maxLength ? text.slice(0, maxLength - 3) + '...' : text;
}

function money(row) {
  const priceText = compact(row.price_text);
  if (priceText) return priceText;
  const numeric = Number(row.price_numeric);
  if (!Number.isFinite(numeric)) return 'price n/a';
  const currency = compact(row.currency).toUpperCase();
  if (currency === 'INR') return 'INR ' + numeric;
  return currency ? String(numeric) + ' ' + currency : String(numeric);
}

function rating(row) {
  const value = Number(row.product_rating);
  if (!Number.isFinite(value)) return 'rating n/a';
  const reviews = Number(row.reviews_count);
  return Number.isFinite(reviews) ? String(value) + '/5 (' + reviews + ')' : String(value) + '/5';
}

function source(row) {
  return compact(row.marketplace || row.source_provider || 'source n/a');
}

function buildCaption(row) {
  const name = escapeHtml(truncate(row.product_name, 140));
  const price = escapeHtml(money(row));
  const score = row.raw_payload?.phase4_selection?.confidence_score ?? row.raw_payload?.phase4_debug?.score ?? null;
  const scoreText = score == null ? '' : '\nScore: <b>' + escapeHtml(score) + '</b>';
  const lines = [
    '<b>' + name + '</b>',
    'Price: <b>' + price + '</b>',
    'Rating: ' + escapeHtml(rating(row)),
    'Source: ' + escapeHtml(source(row)),
    'Topic: ' + escapeHtml(truncate(row.source_topic, 120)),
    scoreText.trim(),
    '<a href="' + escapeHtml(row.product_url) + '">Open product</a>',
  ].filter(Boolean);
  return truncate(lines.join('\n'), MAX_CAPTION_LENGTH);
}

return $input.all().map((item) => {
  const row = item.json || {};
  const caption = buildCaption(row);
  const text = caption + '\n\nImage unavailable: sending text card.';
  return {
    json: {
      ...row,
      review_id: row.id,
      telegram_chat_id: CHAT_ID,
      telegram_caption: caption,
      telegram_text: text,
      telegram_file_name: 'hil-review-' + (row.id || 'item') + '.jpg',
      image_url: compact(row.image_url),
    },
  };
});
`;

function replaceNodeDefinition(workflow, nodeName, nodeDef) {
  const index = workflow.nodes.findIndex((entry) => entry.name === nodeName);
  if (index === -1) {
    workflow.nodes.push(nodeDef);
    return;
  }
  workflow.nodes[index] = { ...workflow.nodes[index], ...nodeDef };
}

function replaceConnection(workflow, sourceName, connection) {
  workflow.connections[sourceName] = connection;
}

function readEnv() {
  const env = {};
  const raw = fs.readFileSync(ENV_PATH, "utf8");
  for (const lineRaw of raw.split(/\r?\n/)) {
    const line = lineRaw.trim();
    if (!line || line.startsWith("#") || !line.includes("=")) continue;
    const idx = line.indexOf("=");
    const key = line.slice(0, idx).trim();
    const value = line.slice(idx + 1).trim().replace(/^['"]|['"]$/g, "");
    env[key] = value;
  }
  return env;
}

function exportCleanWorkflow(workflow) {
  const omit = new Set([
    "updatedAt",
    "createdAt",
    "shared",
    "versionId",
    "activeVersionId",
    "versionCounter",
    "triggerCount",
    "tags",
    "parentFolder",
    "activeVersion",
  ]);
  return Object.fromEntries(Object.entries(workflow).filter(([key]) => !omit.has(key)));
}

function applyPhase4(workflow) {
  const next = JSON.parse(JSON.stringify(workflow));

  replaceNodeDefinition(next, "Phase 4 Candidate Selection", {
    parameters: {
      jsCode: candidateSelectionJs,
    },
    type: "n8n-nodes-base.code",
    typeVersion: 2,
    position: [2496, 1216],
    id: "p4sel-code-0001",
    name: "Phase 4 Candidate Selection",
    onError: "continueErrorOutput",
  });

  replaceNodeDefinition(next, "cluster:phase4-candidate-selection", {
    parameters: {
      content: "## Phase 4 - Candidate Selection\n\nMerge Review Sources still collects all normalized candidates, but Phase 4 now decides what reaches human review.\nIt computes a confidence score, filters weak or low-signal rows, removes near-duplicates,\nlimits per-topic/provider volume, and passes only the highest-confidence products into `private.hil_reviews`.",
      height: 484,
      width: 1560,
      color: 5,
    },
    type: "n8n-nodes-base.stickyNote",
    typeVersion: 1,
    position: [1408, 1040],
    id: "p4sel-sticky-0001",
    name: "cluster:phase4-candidate-selection",
  });

  replaceNodeDefinition(next, "Prepare Telegram Card", {
    parameters: {
      jsCode: telegramCardPrepJs,
    },
    type: "n8n-nodes-base.code",
    typeVersion: 2,
    position: [3024, 1216],
    id: "p4tg-prep-0001",
    name: "Prepare Telegram Card",
    onError: "continueErrorOutput",
  });

  replaceNodeDefinition(next, "Download Product Image", {
    parameters: {
      url: "={{ $json.image_url }}",
      sendHeaders: true,
      headerParameters: {
        parameters: [
          {
            name: "User-Agent",
            value: "Mozilla/5.0 (compatible; EL-HIL-Bot/1.0)",
          },
          {
            name: "Accept",
            value: "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
          },
        ],
      },
      options: {
        timeout: 15000,
        redirect: {
          redirect: {
            followRedirects: true,
            maxRedirects: 5,
          },
        },
        response: {
          response: {
            responseFormat: "file",
            outputPropertyName: "product_image",
          },
        },
      },
    },
    type: "n8n-nodes-base.httpRequest",
    typeVersion: 4.2,
    position: [3248, 1216],
    id: "p4tg-download-0001",
    name: "Download Product Image",
    onError: "continueErrorOutput",
  });

  replaceNodeDefinition(next, "Send HIL Telegram Photo", {
    parameters: {
      resource: "message",
      operation: "sendPhoto",
      chatId: HIL_CHAT_ID,
      binaryData: true,
      binaryPropertyName: "product_image",
      additionalFields: {
        caption: "={{ $('Prepare Telegram Card').item.json.telegram_caption }}",
        parse_mode: "HTML",
        fileName: "={{ $('Prepare Telegram Card').item.json.telegram_file_name }}",
      },
    },
    type: "n8n-nodes-base.telegram",
    typeVersion: 1.2,
    position: [3472, 1120],
    id: "p4tg-photo-0001",
    name: "Send HIL Telegram Photo",
    webhookId: "p4tg-photo-webhook-0001",
    credentials: {
      telegramApi: {
        id: "5w4zQqucsn6Vehh6",
        name: "EL-HIL-BOT",
      },
    },
    onError: "continueErrorOutput",
  });

  replaceNodeDefinition(next, "Mark Telegram Photo Sent", {
    parameters: {
      operation: "executeQuery",
      query: "UPDATE private.hil_reviews\nSET telegram_chat_id = $2::bigint,\n    telegram_message_id = $3::bigint,\n    telegram_media_status = 'sent',\n    telegram_sent_at = now(),\n    updated_at = now()\nWHERE id = $1::bigint\nRETURNING id, telegram_chat_id, telegram_message_id, telegram_media_status, telegram_sent_at;",
      options: {
        queryReplacement: "={{ $('Prepare Telegram Card').item.json.review_id }},{{ $json.result.chat.id }},{{ $json.result.message_id }}",
        queryBatching: "independently",
      },
    },
    type: "n8n-nodes-base.postgres",
    typeVersion: 2.5,
    position: [3696, 1120],
    id: "p4tg-mark-photo-0001",
    name: "Mark Telegram Photo Sent",
    credentials: {
      postgres: {
        id: "Tx3i0fewZ8MM6LFt",
        name: "Supabase yatralounge (Dropship Memory)",
      },
    },
    continueOnFail: true,
  });

  replaceNodeDefinition(next, "Send HIL Telegram Text Fallback", {
    parameters: {
      resource: "message",
      operation: "sendMessage",
      chatId: HIL_CHAT_ID,
      text: "={{ $('Prepare Telegram Card').item.json.telegram_text }}",
      additionalFields: {
        appendAttribution: false,
        disable_web_page_preview: false,
        parse_mode: "HTML",
      },
    },
    type: "n8n-nodes-base.telegram",
    typeVersion: 1.2,
    position: [3472, 1328],
    id: "p4tg-text-0001",
    name: "Send HIL Telegram Text Fallback",
    webhookId: "p4tg-text-webhook-0001",
    credentials: {
      telegramApi: {
        id: "5w4zQqucsn6Vehh6",
        name: "EL-HIL-BOT",
      },
    },
    onError: "continueErrorOutput",
  });

  replaceNodeDefinition(next, "Mark Telegram Text Fallback", {
    parameters: {
      operation: "executeQuery",
      query: "UPDATE private.hil_reviews\nSET telegram_chat_id = $2::bigint,\n    telegram_message_id = $3::bigint,\n    telegram_media_status = 'text_fallback',\n    telegram_sent_at = now(),\n    updated_at = now()\nWHERE id = $1::bigint\nRETURNING id, telegram_chat_id, telegram_message_id, telegram_media_status, telegram_sent_at;",
      options: {
        queryReplacement: "={{ $('Prepare Telegram Card').item.json.review_id }},{{ $json.result.chat.id }},{{ $json.result.message_id }}",
        queryBatching: "independently",
      },
    },
    type: "n8n-nodes-base.postgres",
    typeVersion: 2.5,
    position: [3696, 1328],
    id: "p4tg-mark-text-0001",
    name: "Mark Telegram Text Fallback",
    credentials: {
      postgres: {
        id: "Tx3i0fewZ8MM6LFt",
        name: "Supabase yatralounge (Dropship Memory)",
      },
    },
    continueOnFail: true,
  });

  replaceNodeDefinition(next, "cluster:phase4-telegram-delivery", {
    parameters: {
      content: "## Phase 4 - Telegram Card Delivery\n\nAfter `private.hil_reviews` upsert, this branch prepares a compact review card,\ndownloads the product image as binary, sends a Telegram photo through `EL-HIL-BOT`,\nand records Telegram delivery metadata. If image/photo delivery fails, it sends a text fallback.",
      height: 496,
      width: 1008,
      color: 6,
    },
    type: "n8n-nodes-base.stickyNote",
    typeVersion: 1,
    position: [2976, 1040],
    id: "p4tg-sticky-0001",
    name: "cluster:phase4-telegram-delivery",
  });

  replaceConnection(next, "Merge Review Sources", {
    main: [
      [
        {
          node: "Phase 4 Candidate Selection",
          type: "main",
          index: 0,
        },
      ],
    ],
  });

  replaceConnection(next, "Phase 4 Candidate Selection", {
    main: [
      [
        {
          node: "Supabase Insert (HIL Reviews)",
          type: "main",
          index: 0,
        },
      ],
    ],
  });

  replaceConnection(next, "Supabase Insert (HIL Reviews)", {
    main: [
      [
        {
          node: "Prepare Telegram Card",
          type: "main",
          index: 0,
        },
      ],
    ],
  });

  replaceConnection(next, "Prepare Telegram Card", {
    main: [
      [
        {
          node: "Download Product Image",
          type: "main",
          index: 0,
        },
      ],
      [
        {
          node: "Error Formatter",
          type: "main",
          index: 0,
        },
      ],
    ],
  });

  replaceConnection(next, "Download Product Image", {
    main: [
      [
        {
          node: "Send HIL Telegram Photo",
          type: "main",
          index: 0,
        },
      ],
      [
        {
          node: "Send HIL Telegram Text Fallback",
          type: "main",
          index: 0,
        },
      ],
    ],
  });

  replaceConnection(next, "Send HIL Telegram Photo", {
    main: [
      [
        {
          node: "Mark Telegram Photo Sent",
          type: "main",
          index: 0,
        },
      ],
      [
        {
          node: "Send HIL Telegram Text Fallback",
          type: "main",
          index: 0,
        },
      ],
    ],
  });

  replaceConnection(next, "Send HIL Telegram Text Fallback", {
    main: [
      [
        {
          node: "Mark Telegram Text Fallback",
          type: "main",
          index: 0,
        },
      ],
      [
        {
          node: "Error Formatter",
          type: "main",
          index: 0,
        },
      ],
    ],
  });

  const stickyIndex = next.nodes.findIndex((node) => node.name === "cluster:phase3d-hil-review-queue");
  if (stickyIndex !== -1) {
    next.nodes.splice(stickyIndex, 1);
  }

  const pgNode = next.nodes.find((node) => node.name === "Supabase Insert (HIL Reviews)");
  if (pgNode) {
    pgNode.position = [2784, 1216];
  }

  return next;
}

async function getLiveWorkflow(env) {
  const res = await fetch(env.N8N_URL + "/api/v1/workflows/" + WORKFLOW_ID, {
    headers: { "X-N8N-API-KEY": env.N8N_SECRET, Accept: "application/json" },
  });
  if (!res.ok) throw new Error("GET workflow failed: " + res.status + " " + await res.text());
  return res.json();
}

async function putLiveWorkflow(env, workflow) {
  const workflowSettings = workflow.settings || {};
  const body = {
    name: workflow.name,
    nodes: workflow.nodes,
    connections: workflow.connections,
    settings: Object.fromEntries(
      Object.entries({
        executionOrder: workflowSettings.executionOrder || "v1",
        errorWorkflow: workflowSettings.errorWorkflow || undefined,
      }).filter(([, value]) => value != null)
    ),
  };
  const res = await fetch(env.N8N_URL + "/api/v1/workflows/" + WORKFLOW_ID, {
    method: "PUT",
    headers: {
      "X-N8N-API-KEY": env.N8N_SECRET,
      "Content-Type": "application/json",
      Accept: "application/json",
    },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error("PUT workflow failed: " + res.status + " " + await res.text());
  return res.json();
}

async function main() {
  const applyLive = process.argv.includes("--live");
  const localWorkflow = JSON.parse(fs.readFileSync(WORKFLOW_PATH, "utf8"));
  const patchedLocal = applyPhase4(localWorkflow);
  fs.writeFileSync(WORKFLOW_PATH, JSON.stringify(patchedLocal, null, 2) + "\n", "utf8");
  console.log("Phase 4 candidate selection and Telegram delivery added to local el_workflow.json");

  if (!applyLive) return;

  const env = readEnv();
  const liveWorkflow = await getLiveWorkflow(env);
  const patchedLive = applyPhase4(liveWorkflow);
  await putLiveWorkflow(env, patchedLive);

  const refreshed = await getLiveWorkflow(env);
  fs.writeFileSync(WORKFLOW_PATH, JSON.stringify(exportCleanWorkflow(refreshed), null, 2) + "\n", "utf8");
  console.log("Phase 4 candidate selection and Telegram delivery applied to live n8n workflow");
}

main().catch((error) => {
  console.error(error && error.stack ? error.stack : String(error));
  process.exit(1);
});
