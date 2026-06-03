"""Daily-batch orchestrator. Nodes added incrementally — see docs/PORT_LOG.md."""
from __future__ import annotations

from el import config
from el.logger import get_logger
from el.sources import TrendCandidate
from el.sources import youtube as youtube_source
from el.sources import rss_india_source
from el.sources import google_news_india_source
from el.sources import ai_trend_discovery as ai_trend_discovery_source
from el.nodes import (
    ai_score_trends,
    answer_hil_callback,
    apply_hil_callback,
    build_search_query,
    cj_get_token,
    cj_product_list,
    create_curated_picks_tab,
    create_day_tab,
    curate_picks,
    download_product_image,
    email_digest,
    email_product_detail,
    embed_candidate_products,
    drive_upload,
    filter_top_30,
    generate_shopify_theme,
    if_callback_finalized_review,
    mark_telegram_photo_sent,
    mark_telegram_text_fallback,
    merge_review_sources,
    normalize_cj_review,
    normalize_sentinel_review,
    notify_business,
    parse_hil_callback,
    phase4_candidate_selection,
    pick_top_3,
    prepare_json_file,
    prepare_sheet_rows,
    prepare_telegram_card,
    record_niche_performance,
    score_rank,
    sentinel_vetting,
    supplier_search,
    send_hil_telegram_photo,
    send_hil_telegram_text_fallback,
    stochastic_logger,
    supabase_insert_hil_reviews,
    telegram_alert,
    upload_shopify_products,
    upload_shopify_theme,
    write_curated_picks,
    write_rows_to_sheet,
    youtube_trending,
)

log = get_logger(__name__)


_SOURCE_REGISTRY = {
    "youtube": youtube_source,
    # Fenix engine — live feeds (real, no API approval needed)
    "rss_india": rss_india_source,
    "google_news_india": google_news_india_source,
    # Fenix engine — AI + web-search trend discovery (primary brain)
    "ai_trend_discovery": ai_trend_discovery_source,
}

# Default when EL_SOURCES_ENABLED is unset/empty. AI discovery runs LAST so the
# feed candidates collected before it are available as grounding headlines.
_DEFAULT_SOURCES = [
    "youtube", "rss_india", "google_news_india", "ai_trend_discovery",
]


def _load_enabled_sources():
    """Return source modules listed in EL_SOURCES_ENABLED, in given order.

    Unknown names are logged and skipped. Empty/unset env var → _DEFAULT_SOURCES.
    """
    raw = config.get("EL_SOURCES_ENABLED")
    names = [n.strip() for n in (raw or "").split(",") if n.strip()]
    if not names:
        names = list(_DEFAULT_SOURCES)
    out = []
    for name in names:
        mod = _SOURCE_REGISTRY.get(name)
        if mod is None:
            log.warning("EL_SOURCES_ENABLED: unknown source %r — skipping", name)
            continue
        out.append(mod)
    return out


def _fetch_all_sources(sources, ctx: dict) -> list[TrendCandidate]:
    """Call fetch_trends on each source, isolating per-source failures.

    ``ctx["source_candidates"]`` is updated incrementally so a later source
    (e.g. ai_trend_discovery, ordered last) can read the candidates already
    collected by the feed sources and use their titles as grounding.
    """
    aggregated: list[TrendCandidate] = []
    ctx["source_candidates"] = aggregated
    for src in sources:
        try:
            candidates = src.fetch_trends(ctx)
        except Exception:
            log.exception("_fetch_all_sources: source %s crashed", src.SOURCE_ID)
            continue
        for c in (candidates or []):
            aggregated.append(c)
            ctx["source_candidates"] = aggregated
        log.info("_fetch_all_sources: %s → %d", src.SOURCE_ID, len(candidates or []))
    return aggregated


def run(ctx: dict) -> dict:
    """Run the daily pipeline batch against *ctx*.

    Steps (in order):

    1. Load enabled sources, fetch trend candidates
    2. Merge review-sources into a single review list
    3. Score, dedupe, rank (Fenix Engine — keyword + AI)
    4. Filter top 30 trends
    5. Forge → Sentinel (supplier search + product vetting)
    6. Phase-4 candidate selection (HIL queue build)
    7. CJ product search for approved picks
    8. Embed candidate products (pgvector)
    9. Prepare day-sheet, sheet-rows, drive-upload, curated-picks
    10. Curate picks, download images, prepare Telegram cards
    11. Email digest, email product detail, notify business
    12. Record niche performance
    13. Upload Shopify theme + products (if store configured)
    """
    log.info("EL pipeline: batch start")

    # ── Step 1: sources ─────────────────────────────────────────────────────
    enabled_sources = _load_enabled_sources()
    ctx["source_candidates"] = _fetch_all_sources(enabled_sources, ctx)
    log.info("EL pipeline: loaded %d candidate(s) from %d source(s)",
             len(ctx["source_candidates"]), len(enabled_sources))

    # ── Step 2: merge review sources ────────────────────────────────────────
    try:
        ctx = merge_review_sources.run(ctx)
    except Exception:
        log.exception("EL pipeline: merge_review_sources crashed")
        ctx["review_sources"] = ctx.get("review_sources", [])

    # ── Step 3: score, dedupe, rank (Fenix Engine) ──────────────────────────
    try:
        ctx = score_rank.run(ctx)
    except Exception:
        log.exception("EL pipeline: score_rank crashed")
    try:
        ctx = ai_score_trends.run(ctx)
    except Exception:
        log.exception("EL pipeline: ai_score_trends crashed")

    # ── Step 4: filter top 30 ────────────────────────────────────────────────
    try:
        ctx = filter_top_30.run(ctx)
    except Exception:
        log.exception("EL pipeline: filter_top_30 crashed")
        ctx["top_trends"] = ctx.get("top_trends", [])

    # ── Step 5: Forge → Sentinel ═══════════════════════════════════════════
    forge_pipeline = (config.get("EL_FORGE_PIPELINE_ENABLED", "true") or "").strip().lower() in {
        "1", "true", "yes", "on",
    }
    if forge_pipeline:
        try:
            ctx = supplier_search.run(ctx)
        except Exception:
            log.exception("EL pipeline: supplier_search crashed")
        try:
            ctx = sentinel_vetting.run(ctx)
        except Exception:
            log.exception("EL pipeline: sentinel_vetting crashed")
    else:
        log.info("EL pipeline: Forge pipeline disabled — skipping supplier_search + sentinel_vetting")

    # ── Step 6: Phase-4 candidate selection ─────────────────────────────────
    try:
        ctx = phase4_candidate_selection.run(ctx)
    except Exception:
        log.exception("EL pipeline: phase4_candidate_selection crashed")

    # ── Step 7: CJ product search ────────────────────────────────────────────
    try:
        ctx = cj_get_token.run(ctx)
    except Exception:
        log.exception("EL pipeline: cj_get_token crashed")
    try:
        ctx = cj_product_list.run(ctx)
    except Exception:
        log.exception("EL pipeline: cj_product_list crashed")

    # ── Step 8: Embed candidates ─────────────────────────────────────────────
    try:
        ctx = embed_candidate_products.run(ctx)
    except Exception:
        log.exception("EL pipeline: embed_candidate_products crashed")

    # ── Step 9: Sheets + Drive ───────────────────────────────────────────────
    try:
        ctx = create_day_tab.run(ctx)
    except Exception:
        log.exception("EL pipeline: create_day_tab crashed")
    try:
        ctx = prepare_sheet_rows.run(ctx)
    except Exception:
        log.exception("EL pipeline: prepare_sheet_rows crashed")
    try:
        ctx = write_rows_to_sheet.run(ctx)
    except Exception:
        log.exception("EL pipeline: write_rows_to_sheet crashed")
    try:
        ctx = drive_upload.run(ctx)
    except Exception:
        log.exception("EL pipeline: drive_upload crashed")
    try:
        ctx = create_curated_picks_tab.run(ctx)
    except Exception:
        log.exception("EL pipeline: create_curated_picks_tab crashed")

    # ── Step 10: Curate picks → Telegram ──────────────────────────────────────
    try:
        ctx = curate_picks.run(ctx)
    except Exception:
        log.exception("EL pipeline: curate_picks crashed")
    try:
        ctx = download_product_image.run(ctx)
    except Exception:
        log.exception("EL pipeline: download_product_image crashed")
    try:
        ctx = prepare_telegram_card.run(ctx)
    except Exception:
        log.exception("EL pipeline: prepare_telegram_card crashed")

    # ── Step 11: Outbound (email + notify) ────────────────────────────────────
    try:
        ctx = email_digest.run(ctx)
    except Exception:
        log.exception("EL pipeline: email_digest crashed")
    try:
        ctx = email_product_detail.run(ctx)
    except Exception:
        log.exception("EL pipeline: email_product_detail crashed")
    try:
        ctx = notify_business.run(ctx)
    except Exception:
        log.exception("EL pipeline: notify_business crashed")

    # ── Step 12: Record niche performance ────────────────────────────────────
    try:
        ctx = record_niche_performance.run(ctx)
    except Exception:
        log.exception("EL pipeline: record_niche_performance crashed")

    # ── Step 13: Shopify ─────────────────────────────────────────────────────
    try:
        ctx = generate_shopify_theme.run(ctx)
    except Exception:
        log.exception("EL pipeline: generate_shopify_theme crashed")
    try:
        ctx = upload_shopify_theme.run(ctx)
    except Exception:
        log.exception("EL pipeline: upload_shopify_theme crashed")
    try:
        ctx = upload_shopify_products.run(ctx)
    except Exception:
        log.exception("EL pipeline: upload_shopify_products crashed")

    log.info("EL pipeline: batch done")
    return ctx
