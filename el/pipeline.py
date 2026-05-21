"""Daily-batch orchestrator. Nodes added incrementally — see docs/PORT_LOG.md."""
from __future__ import annotations

from el import config
from el.logger import get_logger
from el.sources import TrendCandidate
from el.sources import shopify_competitor as shopify_competitor_source
from el.sources import youtube as youtube_source
from el.nodes import (
    answer_hil_callback,
    apply_hil_callback,
    build_search_query,
    cj_get_token,
    cj_product_list,
    create_curated_picks_tab,
    create_day_tab,
    curate_picks,
    download_product_image,
    embed_candidate_products,
    drive_upload,
    filter_top_30,
    if_callback_finalized_review,
    mark_telegram_photo_sent,
    mark_telegram_text_fallback,
    merge_review_sources,
    normalize_cj_review,
    parse_hil_callback,
    phase4_candidate_selection,
    pick_top_3,
    prepare_json_file,
    prepare_sheet_rows,
    prepare_telegram_card,
    score_rank,
    send_hil_telegram_photo,
    send_hil_telegram_text_fallback,
    stochastic_logger,
    supabase_insert_hil_reviews,
    write_curated_picks,
    write_rows_to_sheet,
    youtube_trending,
)

log = get_logger(__name__)


_SOURCE_REGISTRY = {
    "youtube": youtube_source,
    "shopify_competitor": shopify_competitor_source,
}


def _load_enabled_sources():
    """Return source modules listed in EL_SOURCES_ENABLED, in given order.

    Unknown names are logged and skipped. Empty/unset env var → ["youtube"].
    """
    raw = config.get("EL_SOURCES_ENABLED")
    names = [n.strip() for n in (raw or "").split(",") if n.strip()]
    if not names:
        names = ["youtube"]
    out = []
    for name in names:
        mod = _SOURCE_REGISTRY.get(name)
        if mod is None:
            log.warning("EL_SOURCES_ENABLED: unknown source %r — skipping", name)
            continue
        out.append(mod)
    return out


def _fetch_all_sources(sources, ctx: dict) -> list[TrendCandidate]:
    """Call fetch_trends on each source, isolating per-source failures."""
    aggregated: list[TrendCandidate] = []
    for src in sources:
        try:
            aggregated.extend(src.fetch_trends(ctx))
        except Exception:
            log.exception("source %s: fetch_trends crashed", getattr(src, "SOURCE_ID", "?"))
    return aggregated


def run() -> dict:
    """Execute the daily batch. Nodes are wired in order from EL.json."""
    log.info("EL pipeline run start")
    ctx: dict = {}

    # SP2: load enabled sources into ctx["source_candidates"]. This is additive —
    # no downstream node consumes source_candidates yet; score_rank still reads
    # ctx["youtube_items"] populated by the YouTube source via youtube_trending.
    enabled_sources = _load_enabled_sources()
    ctx["source_candidates"] = _fetch_all_sources(enabled_sources, ctx)
    log.info("EL pipeline: loaded %d candidate(s) from %d source(s)",
             len(ctx["source_candidates"]), len(enabled_sources))

    if config.get("YOUTUBE_API_KEY") and not any(
        s.SOURCE_ID == "youtube" for s in enabled_sources
    ):
        # YouTube was not in EL_SOURCES_ENABLED — fall back to direct call so
        # score_rank still gets ctx["youtube_items"].
        youtube_trending.run(ctx)
    elif not config.get("YOUTUBE_API_KEY"):
        log.warning("YOUTUBE_API_KEY not set — skipping YouTube Trending IN")

    score_rank.run(ctx)

    if config.get("GOOGLE_SERVICE_ACCOUNT_JSON"):
        create_day_tab.run(ctx)
        create_curated_picks_tab.run(ctx)
    else:
        log.warning(
            "GOOGLE_SERVICE_ACCOUNT_JSON not set - skipping Create Day Tab and "
            "Create Curated Picks Tab"
        )

    prepare_sheet_rows.run(ctx)
    prepare_json_file.run(ctx)

    if config.get("GOOGLE_SERVICE_ACCOUNT_JSON"):
        drive_upload.run(ctx)
    else:
        log.warning("GOOGLE_SERVICE_ACCOUNT_JSON not set - skipping Drive Upload")

    if config.get("GOOGLE_SERVICE_ACCOUNT_JSON"):
        write_rows_to_sheet.run(ctx)
    else:
        log.warning("GOOGLE_SERVICE_ACCOUNT_JSON not set - skipping Write Rows to Sheet")

    filter_top_30.run(ctx)

    if config.get("GOOGLE_SERVICE_ACCOUNT_JSON"):
        curate_picks.run(ctx)
        build_search_query.run(ctx)
        if ctx.get("cj_search_queries"):
            if config.get("CJ_EMAIL") and config.get("CJ_API_KEY"):
                cj_get_token.run(ctx)
                cj_product_list.run(ctx)
                pick_top_3.run(ctx)
                if config.get("EL_EMBEDDINGS_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}:
                    embed_candidate_products.run(ctx)
                normalize_cj_review.run(ctx)
                merge_review_sources.run(ctx)
                phase4_candidate_selection.run(ctx)
                stochastic_logger.run(ctx)
                if config.get("SUPABASE_URL") and (
                    config.get("SUPABASE_SERVICE_ROLE_KEY")
                    or config.get("SUPABASE_SECRET_KEY")
                    or config.get("SUPABASE_KEY")
                ):
                    supabase_insert_hil_reviews.run(ctx)
                    if ctx.get("hil_review_rows"):
                        prepare_telegram_card.run(ctx)
                        download_product_image.run(ctx)
                        send_hil_telegram_photo.run(ctx)
                        mark_telegram_photo_sent.run(ctx)
                        send_hil_telegram_text_fallback.run(ctx)
                        mark_telegram_text_fallback.run(ctx)
                else:
                    log.warning("Supabase env vars not set - skipping Supabase Insert (HIL Reviews)")
            else:
                log.warning("CJ_EMAIL/CJ_API_KEY not set - skipping CJ Get Token")
        if config.get("GOOGLE_SERVICE_ACCOUNT_JSON"):
            write_curated_picks.run(ctx)
        else:
            log.warning("GOOGLE_SERVICE_ACCOUNT_JSON not set - skipping Write Curated Picks")
    else:
        log.warning("GOOGLE_SERVICE_ACCOUNT_JSON not set - skipping Dropship AI Agent (Vertex AI)")

    log.info("EL pipeline run end (ctx keys: %s)", list(ctx.keys()))
    return ctx
