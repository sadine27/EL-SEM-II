"""Daily-batch orchestrator. Nodes added incrementally — see docs/PORT_LOG.md."""
from __future__ import annotations

from el import config
from el.logger import get_logger
from el.nodes import (
    create_day_tab,
    curate_picks,
    filter_top_30,
    prepare_sheet_rows,
    score_rank,
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
    else:
        log.warning("GOOGLE_SERVICE_ACCOUNT_JSON not set - skipping Create Day Tab")

    prepare_sheet_rows.run(ctx)

    if config.get("GOOGLE_SERVICE_ACCOUNT_JSON"):
        write_rows_to_sheet.run(ctx)
    else:
        log.warning("GOOGLE_SERVICE_ACCOUNT_JSON not set - skipping Write Rows to Sheet")

    filter_top_30.run(ctx)

    if config.get("GEMINI_API_KEY"):
        curate_picks.run(ctx)
    else:
        log.warning("GEMINI_API_KEY not set — skipping Dropship AI Agent")

    log.info("EL pipeline run end (ctx keys: %s)", list(ctx.keys()))
    return ctx
