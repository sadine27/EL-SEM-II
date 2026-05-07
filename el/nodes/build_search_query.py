"""Port of n8n node `Build Search Query`."""
from __future__ import annotations

import re
from datetime import datetime, timezone

from el.logger import get_logger

log = get_logger(__name__)

FILLER_RE = re.compile(
    r"\b(merchandise|themed|product|products|specific|official|fan[- ]?made|"
    r"gaming|movie|music|artist|web|series|character|celebrity|focused|"
    r"collectible|collectibles|accessories|apparel|cultural|items|memorabilia|"
    r"regional|song|songs|romantic|symbol|symbols|new|latest)\b"
)


def _today_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _compact_spaces(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def clean_keyword(pick: dict) -> str:
    if pick.get("search_query_in") and str(pick["search_query_in"]).strip():
        cleaned = str(pick["search_query_in"]).lower()
        cleaned = re.sub(r"[^a-z0-9\s\-]+", " ", cleaned)
        cleaned = _compact_spaces(cleaned)
        words = [w for w in cleaned.split(" ") if len(w) > 1]
        return " ".join(words[:6])

    raw = str(pick.get("suggested_product_type") or pick.get("topic") or "")
    match = re.search(r"\(([^)]+)\)", raw)
    if match:
        raw = match.group(1)
    cleaned = raw.lower()
    cleaned = re.sub(r"[^a-z0-9\s\-,]+", " ", cleaned)
    cleaned = re.sub(r"[,\-]+", " ", cleaned)
    cleaned = _compact_spaces(FILLER_RE.sub(" ", _compact_spaces(cleaned)))
    cleaned = " ".join(w for w in cleaned.split(" ") if len(w) > 2)
    cleaned = " ".join(cleaned.split(" ")[:3])
    if cleaned:
        return cleaned

    cleaned = str(pick.get("topic") or "").lower()
    cleaned = re.sub(r"[^a-z0-9\s]+", " ", cleaned)
    cleaned = _compact_spaces(cleaned)
    return " ".join(cleaned.split(" ")[:3])


def build_query(pick: dict) -> dict | None:
    if pick.get("error"):
        return None
    keyword = clean_keyword(pick)
    if not keyword:
        return None
    return {
        "keyword": keyword,
        "source_topic": pick.get("topic") or keyword,
        "source_pick_rank": pick.get("rank"),
        "opportunity_score": pick.get("opportunity_score"),
        "run_date": pick.get("run_date") or _today_str(),
    }


def run(ctx: dict) -> dict:
    picks = ctx.get("curated_picks") or []
    queries = [query for pick in picks if (query := build_query(pick))]
    ctx["cj_search_queries"] = queries
    log.info("Build Search Query: built %d CJ keyword searches", len(queries))
    return ctx
