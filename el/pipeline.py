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
    notify_business,
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


def run(initial_ctx: dict | None = None) -> dict:
    """Execute the daily batch. Nodes are wired in order from EL.json.

    ``initial_ctx`` (SP4): optional seed values placed into the ctx before any
    node runs. Used by ``run_for_request`` to inject user-supplied niche /
    dislikes / budget. Existing callers pass nothing and behavior is unchanged.
    """
    log.info("EL pipeline run start")
    ctx: dict = dict(initial_ctx) if initial_ctx else {}

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

    # SP5a: end-of-run outbound (gated by Gmail SMTP creds).
    if config.get("GMAIL_SMTP_USER") and config.get("GMAIL_SMTP_APP_PASSWORD"):
        email_digest.run(ctx)
        email_product_detail.run(ctx)
    else:
        log.warning("GMAIL_SMTP_* not set - skipping outbound email nodes")

    # SP5b: Shopify auto-store (theme + products). Gated on Shopify creds.
    if config.get("SHOPIFY_STORE_DOMAIN") and (
        config.get("SHOPIFY_ADMIN_API_TOKEN")
        or (config.get("SHOPIFY_CLIENT_ID") and config.get("SHOPIFY_CLIENT_SECRET"))
    ):
        generate_shopify_theme.run(ctx)
        upload_shopify_theme.run(ctx)
        upload_shopify_products.run(ctx)
    else:
        log.warning("SHOPIFY_* not set - skipping Shopify auto-store")

    # SP5a: business notification + dev alert (both safe with TELEGRAM bot token).
    if config.get("TELEGRAM_HIL_BOT_TOKEN"):
        notify_business.run(ctx)
        if ctx.get("formatted_error"):
            telegram_alert.run(ctx)
    elif ctx.get("formatted_error"):
        log.warning("TELEGRAM_HIL_BOT_TOKEN not set - skipping notify_business + telegram_alert")

    log.info("EL pipeline run end (ctx keys: %s)", list(ctx.keys()))
    return ctx


def run_for_request(request_id: str, *, db_provider=None) -> str:
    """SP4: run the pipeline for a user-submitted request row.

    Reads the row from ``private.run_requests``, marks it ``running``, seeds
    ctx with the user-supplied niche/dislikes/budget, calls ``run()``, and
    marks the row ``done`` or ``error``. Returns the final status.
    """
    from el.supabase import SupabaseRestProvider
    from el.web import run_service

    db = db_provider or SupabaseRestProvider()
    row = run_service.get_run(request_id=request_id, db_provider=db)
    if row is None:
        raise ValueError(f"run_request {request_id} not found")

    run_service.mark_running(
        request_id=request_id, pipeline_run_id=None, db_provider=db,
    )
    try:
        initial_ctx = {
            "niche": row.get("niche"),
            "dislikes": row.get("dislikes"),
            "budget_usd": row.get("budget_usd"),
            "run_request_id": request_id,
        }
        run(initial_ctx=initial_ctx)
    except Exception as exc:
        run_service.mark_error(
            request_id=request_id, error_message=str(exc), db_provider=db,
        )
        return "error"

    run_service.mark_done(request_id=request_id, db_provider=db)
    return "done"
