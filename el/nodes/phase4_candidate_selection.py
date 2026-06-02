"""Port of n8n node `Phase 4 Candidate Selection`."""
from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from el.logger import get_logger

log = get_logger(__name__)

MIN_SCORE = 25
FALLBACK_MIN_SCORE = 20
FALLBACK_MAX_ITEMS = 2
TOPIC_CAP = 2
CJ_PROVIDER_CAP = 5
BROWSERBASE_PROVIDER_CAP = 7
SENTINEL_PROVIDER_CAP = 5
TOTAL_CAP = 10

STOP = {
    "the", "and", "for", "with", "from", "that", "this", "your", "into", "online",
    "india", "buy", "shop", "store", "official", "new", "latest", "best",
}
TOPIC_NOISE = {
    "trailer", "teaser", "official", "movie", "season", "episode", "youtube", "news",
    "video", "song", "lyrics", "review", "return", "returns", "opening", "challenge",
    "build", "back", "everyone", "nerdy",
}
GENERIC_PRODUCT_TERMS = [
    "t shirt", "tshirt", "shirt", "hoodie", "poster", "mug", "keychain", "sticker",
    "phone case", "cover", "jersey", "figurine", "action figure", "collectible",
    "merchandise", "plush", "toy", "mouse pad", "desk mat", "notebook", "cap",
]
ALLOWED_MEDIA_PRODUCT_TERMS = [
    "t shirt", "tshirt", "shirt", "hoodie", "poster", "mug", "keychain", "sticker",
    "phone case", "cover", "figurine", "action figure", "collectible", "plush",
    "toy", "mouse pad", "desk mat", "notebook", "cap",
]
ALLOWED_GAMING_PRODUCT_TERMS = [
    "mouse pad", "desk mat", "phone case", "cover", "sticker", "poster", "hoodie",
    "t shirt", "tshirt", "shirt", "mug", "keychain", "figurine", "action figure",
    "collectible", "controller skin", "controller grip", "gaming sleeve",
]
HARD_BLOCK_TERMS = [
    "repair tool", "tool box", "opening tool", "service hard case", "hard case",
    "skin care lotion", "pruritus", "earrings", "flats", "dress", "sleeveless",
    "women s shoes", "ointment", "cream", "medical", "body care", "shoe", "shoes",
    "heels", "sandals",
]
ENTERTAINMENT_TERMS = [
    "trailer", "teaser", "movie", "season", "episode", "song", "lyrics", "youtube",
    "music", "video", "album", "gana", "gaana", "magahi", "bhojpuri", "punjabi",
    "singer", "artist", "official video", "new song",
]
CJ_ENTERTAINMENT_BLOCKLIST = [
    "flats", "earrings", "dress", "sleeveless", "body care", "medical", "ointment",
    "cream", "skin care", "pruritus", "women s shoes", "soft bottomed", "lightweight shoes",
]
GAMING_TERMS = [
    "bgmi", "pubg", "gta", "gameplay", "gaming", "gamer", "franklin", "mr meat",
    "indian bike driving", "3d", "jonathan", "battlegrounds",
]
ENTITY_FAMILIES = [
    {
        "topic": ["wolverine", "ultron", "avengers", "wakanda", "marvel", "doomsday", "hulk"],
        "product": [
            "marvel", "wolverine", "ultron", "avengers", "wakanda", "hulk",
            "iron man", "captain america", "thor",
        ],
    },
    {
        "topic": ["bgmi", "pubg", "jonathan", "battlegrounds"],
        "product": ["bgmi", "pubg", "battlegrounds", "gaming", "gamer", "joystick", "controller", "mouse pad"],
    },
    {
        "topic": ["sidhu", "moose", "wala"],
        "product": ["sidhu", "moose", "wala", "punjabi", "music", "singer", "artist"],
    },
    {
        "topic": ["ashish", "khushi", "amarpali", "nache"],
        "product": ["ashish", "khushi", "amarpali", "music", "song", "artist", "poster", "t shirt"],
    },
]
TERMINAL_REJECTION_STAGES = {"reviewability", "mismatch", "dedupe", "cap"}
TERMINAL_REJECTION_CODES = {
    "missing_product_name",
    "missing_product_url",
    "missing_source_topic",
    "bad_product_url",
    "out_of_stock",
    "missing_price_and_image",
    "hard_block_term",
    "browserbase_repair_tool",
    "cj_not_listed",
    "cj_blocked_category",
    "gaming_missing_allowed_noun",
    "gaming_missing_entity_signal",
    "media_missing_allowed_noun",
    "media_missing_entity_signal",
    "direct_product_hard_block",
    "duplicate_candidate",
    "topic_cap_reached",
    "provider_cap_reached",
    "total_cap_reached",
}


@dataclass
class PreparedCandidate:
    row: dict
    score: float
    url: str
    img: str | None
    host: str
    normalized_name: str
    name_tokens: set[str]
    raw_payload: dict
    context: dict
    rejection_reasons: list[dict]
    selected: bool = False


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def compact(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def normalize_text(value: Any) -> str:
    text = compact(value).lower()
    text = re.sub(r"[^a-z0-9\s]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def tokenize(value: Any) -> list[str]:
    return [
        token for token in normalize_text(value).split(" ")
        if len(token) > 2 and token not in STOP
    ]


def to_number(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
        return float(value)
    text = compact(value).replace(",", "")
    if not text:
        return None
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    if not match:
        return None
    parsed = float(match.group(0))
    return parsed if math.isfinite(parsed) else None


def matched_terms(text: Any, terms: list[str]) -> list[str]:
    normalized = normalize_text(text)
    matches = []
    for term in terms:
        needle = normalize_text(term)
        if needle and f" {needle} " in f" {normalized} ":
            matches.append(needle)
    return list(dict.fromkeys(matches))


def count_term_matches(text: Any, terms: list[str]) -> int:
    return len(matched_terms(text, terms))


def clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def safe_url(value: Any):
    parsed = urlparse(str(value or "").strip())
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return parsed
    return None


def extract_hostname(value: Any) -> str | None:
    match = re.match(r"^https?://([^/?#]+)", compact(value), flags=re.I)
    return match.group(1).lower() if match else None


def canonical_url(value: Any) -> str:
    parsed = safe_url(value)
    if parsed is None:
        return compact(value).lower()
    keep = {"pid", "sku", "id", "product_id"}
    params = [(key, val) for key, val in parse_qsl(parsed.query, keep_blank_values=True) if key in keep]
    canonical = parsed._replace(query=urlencode(params), fragment="")
    return urlunparse(canonical).rstrip("/")


def host_of(value: Any) -> str:
    parsed = safe_url(value)
    if parsed and parsed.hostname:
        return parsed.hostname.lower()
    return extract_hostname(value) or compact(value).lower()


def image_key(value: Any) -> str | None:
    parsed = safe_url(value)
    if parsed is None:
        return None
    clean = parsed._replace(query="", fragment="")
    return urlunparse(clean).rstrip("/")


def overlap_ratio(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0
    return len(a.intersection(b)) / min(len(a), len(b))


def looks_bad_url(value: Any) -> bool:
    text = compact(value).lower()
    return bool(
        re.search(r"[?&](q|k|keyword|search)=", text)
        or re.search(r"/s(\?|/|$)", text)
        or re.search(r"(search|showroom|wholesale|collection|collections|category|categories|browse|results|blog|article)", text)
    )


def parse_raw_payload(value: Any) -> dict:
    if not value:
        return {}
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return {"raw": value}
    return parsed if isinstance(parsed, dict) else {"raw": parsed}


def topic_tokens_for_match(text: Any) -> list[str]:
    return [token for token in tokenize(text) if token not in TOPIC_NOISE]


def classify_topic_intent(text: Any) -> str:
    normalized = normalize_text(text)
    entertainment_hits = count_term_matches(normalized, ENTERTAINMENT_TERMS)
    gaming_hits = count_term_matches(normalized, GAMING_TERMS)
    hashtag_hits = len(re.findall(r"#\S+", str(text or "")))
    separator_hits = len(re.findall(r"[|&]|\bft\b|\bfeat\b", str(text or ""), flags=re.I))
    if gaming_hits > 0:
        return "gaming_merch"
    if entertainment_hits > 0 or hashtag_hits >= 2 or separator_hits >= 2:
        return "media_merch"
    return "direct_product"


def entertainment_topic_signals(text: Any) -> dict:
    raw = str(text or "")
    normalized = normalize_text(text)
    term_hits = count_term_matches(normalized, ENTERTAINMENT_TERMS)
    hashtag_hits = len(re.findall(r"#\S+", raw))
    quoted_entity_hits = len(re.findall(r"[|&]|\bft\b|\bfeat\b", raw, flags=re.I))
    return {
        "termHits": term_hits,
        "hashtagHits": hashtag_hits,
        "quotedEntityHits": quoted_entity_hits,
        "isEntertainment": (
            term_hits > 0
            or hashtag_hits >= 2
            or quoted_entity_hits >= 2
            or bool(re.search(r"\b(video|gana|gaana|song|lyrics|teaser|trailer)\b", raw, flags=re.I))
        ),
    }


def overlap_count(a: set[str], b: set[str]) -> int:
    if not a or not b:
        return 0
    return len(a.intersection(b))


def preview_text(text: Any, max_length: int) -> str:
    value = compact(text)
    return value[: max_length - 3] + "..." if len(value) > max_length else value


def _get(mapping: dict, *path: str) -> Any:
    value: Any = mapping
    for key in path:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def build_context(row: dict, raw_payload: dict) -> dict:
    product_core_text = " ".join(
        compact(part)
        for part in [
            row.get("product_name"),
            row.get("description"),
            row.get("supplier_name"),
            row.get("marketplace"),
            _get(raw_payload, "extract", "description"),
            _get(raw_payload, "extract", "product_name"),
            _get(raw_payload, "extract", "supplier_name"),
            _get(raw_payload, "offer", "categoryName"),
            _get(raw_payload, "raw_payload", "categoryName"),
            _get(raw_payload, "raw_payload", "productNameEn"),
            _get(raw_payload, "raw_payload", "productName"),
        ]
        if part
    )
    product_text = " ".join(
        compact(part)
        for part in [
            product_core_text,
            raw_payload.get("tavily_query"),
            raw_payload.get("tavily_title"),
        ]
        if part
    )
    topic_text = " ".join(
        compact(part)
        for part in [row.get("source_topic"), raw_payload.get("tavily_query")]
        if part
    )
    topic_tokens = set(topic_tokens_for_match(topic_text))
    product_tokens = set(tokenize(product_text))
    topic_overlap = overlap_count(topic_tokens, product_tokens)
    generic_merch_terms = matched_terms(product_core_text, GENERIC_PRODUCT_TERMS)
    media_allowed_terms = matched_terms(product_core_text, ALLOWED_MEDIA_PRODUCT_TERMS)
    gaming_allowed_terms = matched_terms(product_core_text, ALLOWED_GAMING_PRODUCT_TERMS)
    hard_block_terms = matched_terms(product_core_text, HARD_BLOCK_TERMS)
    cj_blocked_terms = matched_terms(product_core_text, CJ_ENTERTAINMENT_BLOCKLIST)
    browserbase_entity_matches = to_number(raw_payload.get("tavily_entity_matches")) or 0
    browserbase_product_matches = to_number(raw_payload.get("tavily_product_matches")) or 0
    listed_source = _get(raw_payload, "offer", "listedNum")
    if listed_source is None:
        listed_source = _get(raw_payload, "raw_payload", "listedNum")
    listed_num = to_number(listed_source)
    topic_signals = entertainment_topic_signals(topic_text)
    topic_intent_type = classify_topic_intent(topic_text)
    normalized_topic_text = normalize_text(topic_text)
    normalized_product_text = normalize_text(product_text)
    family_matches = []

    for family in ENTITY_FAMILIES:
        topic_hits = [term for term in family["topic"] if normalize_text(term) in normalized_topic_text]
        product_hits = [term for term in family["product"] if normalize_text(term) in normalized_product_text]
        if topic_hits and product_hits:
            family_matches.append({
                "topic_terms": list(dict.fromkeys(normalize_text(term) for term in topic_hits)),
                "product_terms": list(dict.fromkeys(normalize_text(term) for term in product_hits)),
            })

    return {
        "product_core_text": product_core_text,
        "product_text": product_text,
        "topic_text": topic_text,
        "topic_tokens": topic_tokens,
        "product_tokens": product_tokens,
        "topic_overlap": topic_overlap,
        "generic_merch_terms": generic_merch_terms,
        "generic_merch_matches": len(generic_merch_terms),
        "media_allowed_terms": media_allowed_terms,
        "media_allowed_matches": len(media_allowed_terms),
        "gaming_allowed_terms": gaming_allowed_terms,
        "gaming_allowed_matches": len(gaming_allowed_terms),
        "hard_block_terms": hard_block_terms,
        "hard_block_matches": len(hard_block_terms),
        "cj_blocked_terms": cj_blocked_terms,
        "browserbase_entity_matches": browserbase_entity_matches,
        "browserbase_product_matches": browserbase_product_matches,
        "listed_num": listed_num,
        "media_topic": topic_intent_type != "direct_product",
        "topic_intent_type": topic_intent_type,
        "topic_signals": topic_signals,
        "family_match": bool(family_matches),
        "family_matches": family_matches,
        "normalized_topic_text": normalized_topic_text,
        "normalized_product_text": normalized_product_text,
        "normalized_product_core_text": normalize_text(product_core_text),
    }


def build_reason(stage: str, code: str, message: str, details: dict | None = None) -> dict:
    return {
        "stage": stage,
        "code": code,
        "message": message,
        "details": details or {},
    }


def has_terminal_rejection(candidate: PreparedCandidate) -> bool:
    return any(
        reason.get("stage") in TERMINAL_REJECTION_STAGES
        or reason.get("code") in TERMINAL_REJECTION_CODES
        for reason in candidate.rejection_reasons
    )


def has_only_score_rejections(candidate: PreparedCandidate) -> bool:
    return bool(candidate.rejection_reasons) and all(
        reason.get("stage") == "score" for reason in candidate.rejection_reasons
    )


def has_fallback_evidence(candidate: PreparedCandidate) -> bool:
    row = candidate.row
    context = candidate.context
    price = to_number(row.get("price_numeric"))
    has_commercial_signal = bool(row.get("image_url") and (row.get("price_text") or price is not None))
    has_topic_signal = (
        context["topic_overlap"] > 0
        or context["family_match"]
        or context["browserbase_entity_matches"] > 0
        or context["topic_intent_type"] == "direct_product"
    )
    return has_commercial_signal and has_topic_signal


def mismatch_reasons(row: dict, context: dict) -> list[dict]:
    reasons = []
    has_entity_signal = (
        context["topic_overlap"] > 0
        or context["family_match"]
        or context["browserbase_entity_matches"] > 0
    )
    has_allowed_media_noun = context["media_allowed_matches"] > 0
    has_allowed_gaming_noun = context["gaming_allowed_matches"] > 0

    if context["hard_block_terms"]:
        reasons.append(build_reason(
            "mismatch",
            "hard_block_term",
            "Blocked because the product text contains banned drift terms.",
            {"matched_terms": context["hard_block_terms"]},
        ))

    if (
        row.get("source_provider") == "browserbase_marketplace"
        and re.search(r"repair tool|tool box|opening tool|service hard case|hard case", context["normalized_product_core_text"])
    ):
        reasons.append(build_reason(
            "mismatch",
            "browserbase_repair_tool",
            "Blocked browserbase result because the product looks like a repair tool or service case.",
            {"matched_terms": matched_terms(context["product_core_text"], [
                "repair tool", "tool box", "opening tool", "service hard case", "hard case",
            ])},
        ))

    if row.get("source_provider") == "cj_dropshipping" and context["listed_num"] is not None and context["listed_num"] <= 0:
        reasons.append(build_reason(
            "mismatch",
            "cj_not_listed",
            "Blocked CJ product because listedNum is missing or non-positive.",
            {"listed_num": context["listed_num"]},
        ))

    if row.get("source_provider") == "cj_dropshipping" and context["cj_blocked_terms"]:
        reasons.append(build_reason(
            "mismatch",
            "cj_blocked_category",
            "Blocked CJ product because it falls into an entertainment-topic category blocklist.",
            {"matched_terms": context["cj_blocked_terms"]},
        ))

    if context["topic_intent_type"] == "gaming_merch" and not has_allowed_gaming_noun:
        reasons.append(build_reason(
            "mismatch",
            "gaming_missing_allowed_noun",
            "Blocked gaming topic because the product text has no allowed gaming merch noun.",
            {"allowed_terms_found": context["gaming_allowed_terms"]},
        ))

    if context["topic_intent_type"] == "gaming_merch" and not has_entity_signal:
        reasons.append(build_reason(
            "mismatch",
            "gaming_missing_entity_signal",
            "Blocked gaming topic because the product has no topic/entity overlap.",
            {
                "topic_overlap": context["topic_overlap"],
                "family_match": context["family_match"],
                "browserbase_entity_matches": context["browserbase_entity_matches"],
            },
        ))

    if context["topic_intent_type"] == "media_merch" and not has_allowed_media_noun:
        reasons.append(build_reason(
            "mismatch",
            "media_missing_allowed_noun",
            "Blocked media topic because the product text has no allowed merch noun.",
            {"allowed_terms_found": context["media_allowed_terms"]},
        ))

    if context["topic_intent_type"] == "media_merch" and not has_entity_signal:
        reasons.append(build_reason(
            "mismatch",
            "media_missing_entity_signal",
            "Blocked media topic because the product has no topic/entity overlap.",
            {
                "topic_overlap": context["topic_overlap"],
                "family_match": context["family_match"],
                "browserbase_entity_matches": context["browserbase_entity_matches"],
            },
        ))

    if context["topic_intent_type"] == "direct_product" and context["hard_block_matches"] > 0 and not has_entity_signal:
        reasons.append(build_reason(
            "mismatch",
            "direct_product_hard_block",
            "Blocked direct-product topic because the item only matches banned drift terms and lacks entity support.",
            {
                "matched_terms": context["hard_block_terms"],
                "topic_overlap": context["topic_overlap"],
                "family_match": context["family_match"],
                "browserbase_entity_matches": context["browserbase_entity_matches"],
            },
        ))

    return reasons


def selection_score(row: dict, context: dict) -> float:
    opportunity = to_number(row.get("opportunity_score")) or 0
    pick_rank = to_number(row.get("source_pick_rank"))
    rating = to_number(row.get("product_rating"))
    reviews = to_number(row.get("reviews_count"))
    price = to_number(row.get("price_numeric"))
    availability = compact(row.get("availability_status")).lower()
    host = host_of(row.get("product_url") or row.get("marketplace") or "")

    score = 0.0
    score += clamp(opportunity, 0, 10) * 6
    if pick_rank is not None:
        score += clamp(12 - pick_rank, 0, 10) * 1.8
    if rating is not None:
        score += clamp(rating, 0, 5) * 4
    if reviews is not None:
        score += clamp(math.log10(reviews + 1) * 8, 0, 22)
    if row.get("image_url"):
        score += 7
    if row.get("price_text") or price is not None:
        score += 5
    if row.get("description"):
        score += 3
    if availability == "in_stock":
        score += 4
    if availability == "out_of_stock":
        score -= 20
    if looks_bad_url(row.get("product_url")):
        score -= 20
    if re.search(r"amazon\.in|flipkart\.com|myntra\.com|ajio\.com|nykaa\.com|meesho\.com|croma\.com|firstcry\.com", host):
        score += 4
    if row.get("source_provider") == "browserbase_marketplace":
        score += 2
    if row.get("source_provider") == "cj_dropshipping":
        score += 1
    if price is not None and price > 0:
        score += 2
    if context["topic_overlap"] > 0:
        score += clamp(context["topic_overlap"] * 6, 0, 18)
    if context["family_match"]:
        score += 8
    if context["generic_merch_matches"] > 0:
        score += clamp(context["generic_merch_matches"] * 2, 0, 8)
    if context["browserbase_entity_matches"] > 0:
        score += clamp(context["browserbase_entity_matches"] * 5, 0, 15)
    if context["browserbase_product_matches"] > 0:
        score += clamp(context["browserbase_product_matches"] * 3, 0, 9)
    if context["hard_block_matches"] > 0:
        score -= clamp(context["hard_block_matches"] * 20, 0, 60)
    if context["media_topic"] and context["topic_overlap"] == 0 and not context["family_match"]:
        score -= 25
    if not row.get("product_name"):
        score -= 100
    if not row.get("product_url"):
        score -= 100
    return round(score, 2)


def reviewability_reasons(row: dict, context: dict) -> list[dict]:
    reasons = []
    if not compact(row.get("product_name")):
        reasons.append(build_reason("reviewability", "missing_product_name", "Blocked because product_name is empty."))
    if not compact(row.get("product_url")):
        reasons.append(build_reason("reviewability", "missing_product_url", "Blocked because product_url is empty."))
    if not compact(row.get("source_topic")):
        reasons.append(build_reason("reviewability", "missing_source_topic", "Blocked because source_topic is empty."))
    if looks_bad_url(row.get("product_url")):
        reasons.append(build_reason(
            "reviewability",
            "bad_product_url",
            "Blocked because the URL looks like a search/listing page.",
            {"product_url": row.get("product_url")},
        ))
    if compact(row.get("availability_status")).lower() == "out_of_stock":
        reasons.append(build_reason("reviewability", "out_of_stock", "Blocked because the item is marked out of stock."))
    if not row.get("image_url") and not row.get("price_text") and to_number(row.get("price_numeric")) is None:
        reasons.append(build_reason(
            "reviewability",
            "missing_price_and_image",
            "Blocked because the candidate has neither image nor price signal.",
        ))
    reasons.extend(mismatch_reasons(row, context))
    return reasons


def build_diagnostics(entry: PreparedCandidate) -> dict:
    return {
        "decision": "selected" if entry.selected else "rejected",
        "score": entry.score,
        "min_score": MIN_SCORE,
        "topic_intent_type": entry.context["topic_intent_type"],
        "source_provider": compact(entry.row.get("source_provider")).lower() or None,
        "source_host": entry.host or None,
        "dedupe_name_key": entry.normalized_name or None,
        "topic_overlap": entry.context["topic_overlap"],
        "family_match": entry.context["family_match"],
        "family_matches": entry.context["family_matches"],
        "browserbase_entity_matches": entry.context["browserbase_entity_matches"],
        "browserbase_product_matches": entry.context["browserbase_product_matches"],
        "generic_merch_terms": entry.context["generic_merch_terms"],
        "media_allowed_terms": entry.context["media_allowed_terms"],
        "gaming_allowed_terms": entry.context["gaming_allowed_terms"],
        "hard_block_terms": entry.context["hard_block_terms"],
        "cj_blocked_terms": entry.context["cj_blocked_terms"],
        "listed_num": entry.context["listed_num"],
        "topic_signals": entry.context["topic_signals"],
        "product_text_preview": preview_text(entry.context["product_core_text"], 220),
        "topic_text_preview": preview_text(entry.context["topic_text"], 180),
        "rejection_reasons": entry.rejection_reasons,
    }


def attach_payload(entry: PreparedCandidate, selection: dict | None) -> dict:
    raw_payload = {
        **entry.raw_payload,
        "phase4_selection": selection,
        "phase4_debug": build_diagnostics(entry),
    }
    return {
        **entry.row,
        "raw_payload": json.dumps(raw_payload, separators=(",", ":")),
    }


def prepare_candidate(row: dict) -> PreparedCandidate:
    ordered_name_tokens = list(dict.fromkeys(tokenize(row.get("product_name"))))
    name_tokens = set(ordered_name_tokens)
    raw_payload = parse_raw_payload(row.get("raw_payload"))
    context = build_context(row, raw_payload)
    score = selection_score(row, context)
    rejection_reasons = reviewability_reasons(row, context)
    if score < MIN_SCORE:
        rejection_reasons.append(build_reason(
            "score",
            "below_min_score",
            "Blocked because the candidate score is below the phase 4 threshold.",
            {"score": score, "min_score": MIN_SCORE},
        ))
    return PreparedCandidate(
        row=row,
        score=score,
        url=canonical_url(row.get("product_url")),
        img=image_key(row.get("image_url")),
        host=host_of(row.get("product_url") or row.get("marketplace") or ""),
        normalized_name=" ".join(ordered_name_tokens),
        name_tokens=name_tokens,
        raw_payload=raw_payload,
        context=context,
        rejection_reasons=rejection_reasons,
    )


def _sort_key(candidate: PreparedCandidate) -> tuple[float, float, float]:
    opportunity = to_number(candidate.row.get("opportunity_score"))
    rank = to_number(candidate.row.get("source_pick_rank"))
    return (-candidate.score, -(opportunity if opportunity is not None else -1), rank if rank is not None else 999)


def _select_internal(
    rows: list[dict], *, selected_at: str | None = None
) -> tuple[list[dict], list[PreparedCandidate]]:
    """Internal: return (selected_rows, deduped_candidates).

    deduped_candidates is the post-mismatch/dedupe pool BEFORE caps.
    selected_rows is the same list select_candidates returned historically.
    """
    now_value = selected_at or _now_iso()
    prepared = [prepare_candidate(row) for row in rows]
    eligible = sorted(
        [entry for entry in prepared if not entry.rejection_reasons],
        key=_sort_key,
    )

    deduped: list[PreparedCandidate] = []
    for candidate in eligible:
        duplicate_of = None
        for kept in deduped:
            same_url = bool(candidate.url and kept.url and candidate.url == kept.url)
            same_image = bool(candidate.img and kept.img and candidate.img == kept.img)
            same_topic = normalize_text(candidate.row.get("source_topic")) == normalize_text(kept.row.get("source_topic"))
            same_host = bool(candidate.host and kept.host and candidate.host == kept.host)
            similar_name = overlap_ratio(candidate.name_tokens, kept.name_tokens) >= 0.8
            if same_url or same_image or (same_topic and same_host and similar_name):
                duplicate_of = kept
                break
        if duplicate_of:
            candidate.rejection_reasons.append(build_reason(
                "dedupe",
                "duplicate_candidate",
                "Blocked because a higher-ranked near-duplicate was already kept.",
                {
                    "duplicate_of_product": duplicate_of.row.get("product_name") or None,
                    "duplicate_of_url": duplicate_of.row.get("product_url") or None,
                    "duplicate_of_score": duplicate_of.score,
                },
            ))
            continue
        deduped.append(candidate)

    per_topic_counts: dict[str, int] = {}
    provider_counts: dict[str, int] = {}
    selected: list[PreparedCandidate] = []
    for candidate in deduped:
        topic_key = normalize_text(candidate.row.get("source_topic"))
        provider_key = compact(candidate.row.get("source_provider")).lower()
        topic_count = per_topic_counts.get(topic_key, 0)
        provider_count = provider_counts.get(provider_key, 0)

        if topic_count >= TOPIC_CAP:
            candidate.rejection_reasons.append(build_reason(
                "cap",
                "topic_cap_reached",
                "Blocked because this topic already reached the phase 4 queue cap.",
                {"topic_cap": TOPIC_CAP, "topic": candidate.row.get("source_topic")},
            ))
            continue
        if provider_key == "cj_dropshipping" and provider_count >= CJ_PROVIDER_CAP:
            candidate.rejection_reasons.append(build_reason(
                "cap",
                "provider_cap_reached",
                "Blocked because the CJ provider cap was reached.",
                {"provider_cap": CJ_PROVIDER_CAP, "source_provider": provider_key},
            ))
            continue
        if provider_key == "browserbase_marketplace" and provider_count >= BROWSERBASE_PROVIDER_CAP:
            candidate.rejection_reasons.append(build_reason(
                "cap",
                "provider_cap_reached",
                "Blocked because the browserbase provider cap was reached.",
                {"provider_cap": BROWSERBASE_PROVIDER_CAP, "source_provider": provider_key},
            ))
            continue
        if provider_key == "forge_sentinel" and provider_count >= SENTINEL_PROVIDER_CAP:
            candidate.rejection_reasons.append(build_reason(
                "cap",
                "provider_cap_reached",
                "Blocked because the Sentinel provider cap was reached.",
                {"provider_cap": SENTINEL_PROVIDER_CAP, "source_provider": provider_key},
            ))
            continue
        if len(selected) >= TOTAL_CAP:
            candidate.rejection_reasons.append(build_reason(
                "cap",
                "total_cap_reached",
                "Blocked because the overall phase 4 queue cap was reached.",
                {"total_cap": TOTAL_CAP},
            ))
            continue

        per_topic_counts[topic_key] = topic_count + 1
        provider_counts[provider_key] = provider_count + 1
        candidate.selected = True
        selected.append(candidate)

    if not selected:
        fallback_pool = sorted(
            [
                candidate for candidate in prepared
                if not has_terminal_rejection(candidate)
                and has_only_score_rejections(candidate)
                and has_fallback_evidence(candidate)
                and candidate.score >= FALLBACK_MIN_SCORE
            ],
            key=lambda candidate: -candidate.score,
        )
        for candidate in fallback_pool[:FALLBACK_MAX_ITEMS]:
            candidate.selected = True
            candidate.rejection_reasons = [
                reason for reason in candidate.rejection_reasons
                if reason.get("stage") != "score"
            ]
            candidate.rejection_reasons.append(build_reason(
                "fallback",
                "fallback_selected",
                "Selected by fallback because strict phase 4 produced an empty queue.",
                {"score": candidate.score, "fallback_min_score": FALLBACK_MIN_SCORE},
            ))
            selected.append(candidate)

    output = []
    for index, candidate in enumerate(selected, start=1):
        selection = {
            "phase": "phase4_candidate_selection",
            "topic_intent_type": candidate.context["topic_intent_type"],
            "confidence_score": candidate.score,
            "queue_rank": index,
            "selected_at": now_value,
            "source_host": candidate.host or None,
            "dedupe_name_key": candidate.normalized_name or None,
        }
        output.append(attach_payload(candidate, selection))
    return output, deduped


def select_candidates(rows: list[dict], *, selected_at: str | None = None) -> list[dict]:
    """Public: return the selected candidates list, exactly as before."""
    selected, _pool = _select_internal(rows, selected_at=selected_at)
    return selected


def build_eligible_pool(
    deduped: list[PreparedCandidate], selected_rows: list[dict]
) -> list[dict]:
    """Serialize the pre-cap deduped pool for ctx["eligible_pool"].

    Each entry: {candidate_payload, candidate_score, candidate_rank, in_greedy_slate}.
    candidate_rank is 1-based, in deduped order (sorted desc by selection_score).
    in_greedy_slate is True iff the candidate's row appears in selected_rows.
    """
    selected_keys = {
        (compact(r.get("product_url")).lower(), compact(r.get("product_sku")).lower())
        for r in selected_rows
    }
    pool: list[dict] = []
    for idx, candidate in enumerate(deduped, start=1):
        key = (
            compact(candidate.row.get("product_url")).lower(),
            compact(candidate.row.get("product_sku")).lower(),
        )
        pool.append({
            "candidate_payload": dict(candidate.row),
            "candidate_score": float(candidate.score),
            "candidate_rank": idx,
            "in_greedy_slate": key in selected_keys,
        })
    return pool


def run(ctx: dict, *, selected_at: str | None = None) -> dict:
    rows = [item for item in (ctx.get("review_candidates") or []) if isinstance(item, dict)]
    selected, deduped = _select_internal(rows, selected_at=selected_at)
    ctx["phase4_candidates"] = selected
    ctx["eligible_pool"] = build_eligible_pool(deduped, selected)
    log.info(
        "Phase 4 Candidate Selection: selected %d of %d candidates (eligible pool %d)",
        len(selected), len(rows), len(ctx["eligible_pool"]),
    )
    return ctx
