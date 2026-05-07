"""Daily-batch orchestrator. Nodes added incrementally — see docs/PORT_LOG.md."""
from __future__ import annotations

from el import config
from el.logger import get_logger
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
    supabase_insert_hil_reviews,
    write_curated_picks,
    write_rows_to_sheet,
    youtube_trending,
)

log = get_logger(__name__)


def run() -> dict:
    """Execute the daily batch. Nodes are wired in order from EL.json."""
    log.info("EL pipeline run start")
    ctx: dict = {}

    if config.get("YOUTUBE_API_KEY"):
        youtube_trending.run(ctx)
    else:
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

    if config.get("GEMINI_API_KEY"):
        curate_picks.run(ctx)
        build_search_query.run(ctx)
        if ctx.get("cj_search_queries"):
            if config.get("CJ_EMAIL") and config.get("CJ_API_KEY"):
                cj_get_token.run(ctx)
                cj_product_list.run(ctx)
                pick_top_3.run(ctx)
                normalize_cj_review.run(ctx)
                merge_review_sources.run(ctx)
                phase4_candidate_selection.run(ctx)
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
        log.warning("GEMINI_API_KEY not set — skipping Dropship AI Agent")

    log.info("EL pipeline run end (ctx keys: %s)", list(ctx.keys()))
    return ctx
