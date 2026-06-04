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


def collect_and_rank(initial_ctx: dict | None = None) -> dict:
    """Run only fetch → score → AI → rank (no downstream nodes).

    Returns ``ctx["ranked_payload"]`` — a dict with ``metadata`` and ``trends``.
    Useful for the ``python -m el trends`` preview CLI and for Forge/Sentinel
    preview commands that need ranked topics without full pipeline execution.
    """
    ctx = dict(initial_ctx or {})
    enabled_sources = _load_enabled_sources()
    ctx["source_candidates"] = _fetch_all_sources(enabled_sources, ctx)
    try:
        ctx = score_rank.run(ctx)
    except Exception:
        log.exception("collect_and_rank: score_rank crashed")
    try:
        ctx = ai_score_trends.run(ctx)
    except Exception:
        log.exception("collect_and_rank: ai_score_trends crashed")
    return ctx.get("ranked_payload") or {"metadata": {}, "trends": []}


def preview_forge(*, query: str | None = None, from_fenix: bool = False, top: int = 10) -> dict:
    """Preview supplier matches for a query or from Fenix-ranked trends.

    Args:
        query:    Single product query to source. Mutually exclusive with from_fenix.
        from_fenix: If True, source the top-ranked Fenix trends.
        top:      Number of trends/queries to process.

    Returns dict with ``metadata`` and ``supplier_matches``, suitable for JSON
    serialisation or CLI pretty-printing.
    """
    if not query and not from_fenix:
        raise ValueError("preview_forge requires query or from_fenix=True")
    try:
        ctx: dict = {}
        if from_fenix:
            payload = collect_and_rank()
            trends = (payload.get("trends") or [])[:top]
            queries = [t["topic"] for t in trends if t.get("topic")]
            ctx["fenix_payload"] = payload
            mode = "fenix"
        else:
            queries = [query] if query else []
            mode = "query"

        if not queries:
            return {"metadata": {"mode": mode, "queries": 0}, "supplier_matches": []}

        import copy as _copy
        from el import supabase
        supabase_ctx = {}
        try:
            supabase_ctx = {"supabase": supabase.default_client()}
        except Exception:
            pass

        # Load supplier sources, run each query
        supplier_sources = supplier_search._load_enabled_sources()
        supplier_matches = []
        for q in queries:
            q_matches = []
            for src in supplier_sources:
                try:
                    cands = src.search_products(q, {**ctx, **supabase_ctx})
                    for c in (cands or []):
                        q_matches.append({
                            "title": c.title,
                            "source_id": c.source_id,
                            "supplier_product_id": c.supplier_product_id,
                            "cost": c.cost,
                            "shipping_cost": c.shipping_cost,
                            "stock": c.stock,
                            "currency": getattr(c, "currency", "USD"),
                            "landed_cost": getattr(c, "landed_cost", None),
                            "match_score": getattr(c, "match_score", None),
                            "shipping_days_min": getattr(c, "shipping_days_min", None),
                            "shipping_days_max": getattr(c, "shipping_days_max", None),
                            "image_url": getattr(c, "image_url", None),
                            "product_url": getattr(c, "product_url", None),
                        })
                except Exception:
                    log.exception("preview_forge: source %s crashed on query %r", src.SOURCE_ID, q)
            supplier_matches.append({"query": q, "matches": q_matches})

        return {
            "metadata": {"mode": mode, "queries": len(queries)},
            "supplier_matches": supplier_matches,
        }
    except Exception:
        log.exception("preview_forge crashed")
        return {"metadata": {"mode": "error"}, "supplier_matches": []}


def _forge_pipeline_enabled() -> bool:
    return (config.get("EL_FORGE_PIPELINE_ENABLED", "true") or "").strip().lower() in {
        "1", "true", "yes", "on",
    }


def run_for_request(request_id: str, *, db_provider=None) -> str:
    """Run the full pipeline on behalf of an on-demand request.

    Args:
        request_id:  Supabase row ID in the ``requests`` table.
        db_provider: Injectable database provider (defaults to supabase).

    Returns the final status string (``"running"``, ``"done"``, or ``"error"``).
    """
    from el import supabase as _supabase
    try:
        db = db_provider or _supabase.default_client()
        # Support both supabase table() interface and minimal FakeDB interface
        if hasattr(db, "select_rows"):
            rows = db.select_rows(schema="public", table="requests", filters={"id": request_id}) or []
            if not rows:
                raise ValueError(f"request {request_id} not found")
            record = rows[0]
            db.update_rows(schema="public", table="requests", filters={"id": request_id}, updates={"status": "running"})
        else:
            row = db.table("requests").select("*").eq("id", request_id).execute()
            if not row.data:
                raise ValueError(f"request {request_id} not found")
            record = row.data[0]
            db.table("requests").update({"status": "running"}).eq("id", request_id).execute()
        ctx = {
            "run_request_id": request_id,
            "niche": record.get("niche"),
            "budget_usd": record.get("budget_usd"),
            "dislikes": record.get("dislikes"),
        }
        run(ctx)
        if hasattr(db, "update_rows"):
            db.update_rows(schema="public", table="requests", filters={"id": request_id}, updates={"status": "done"})
        else:
            db.table("requests").update({"status": "done"}).eq("id", request_id).execute()
        return "done"
    except ValueError:
        raise
    except Exception:
        log.exception("run_for_request: %s failed", request_id)
        try:
            import traceback as _tb
            err_msg = _tb.format_exc()
            updates = {"status": "error", "error_message": err_msg}
            if hasattr(db, "update_rows"):
                db.update_rows(schema="public", table="requests", filters={"id": request_id}, updates=updates)
            else:
                db.table("requests").update(updates).eq("id", request_id).execute()
        except Exception:
            pass
        return "error"


def preview_sentinel(*, query: str | None = None, from_fenix: bool = False, top: int = 10) -> dict:
    """Preview supplier matches passed through the Sentinel vetting gate.

    Args:
        query:    Single product query to source and vet. Mutually exclusive with from_fenix.
        from_fenix: If True, source and vet the top-ranked Fenix trends.
        top:      Number of trends/queries to process.

    Returns dict with ``metadata`` and ``sentinel_matches``.
    """
    if not query and not from_fenix:
        raise ValueError("preview_sentinel requires query or from_fenix=True")
    try:
        # Get Forge matches first (reuse preview_forge internal logic)
        forge_result = preview_forge(query=query, from_fenix=from_fenix, top=top)

        # Run Sentinel vetting on each match
        import copy as _copy
        sentinel_matches = []
        for item in forge_result.get("supplier_matches", []):
            q = item["query"]
            matches = item.get("matches", [])
            # Convert dict matches back to SupplierCandidate-like objects for vetting
            vetted = []
            rejected = []
            for m in matches:
                try:
                    from el.suppliers import SupplierCandidate
                    cand = SupplierCandidate(
                        title=m["title"],
                        source_id=m["source_id"],
                        supplier_product_id=m["supplier_product_id"],
                        cost=m.get("cost", 0),
                        shipping_cost=m.get("shipping_cost", 0),
                        stock=m.get("stock", 0),
                        currency=m.get("currency", "USD"),
                        landed_cost=m.get("landed_cost"),
                        match_score=m.get("match_score"),
                        shipping_days_min=m.get("shipping_days_min"),
                        shipping_days_max=m.get("shipping_days_max"),
                        image_url=m.get("image_url"),
                        product_url=m.get("product_url"),
                    )
                    # Convert to dict for sentinel_vetting which expects dicts with .get()
                    cand_dict = {k: getattr(cand, k, None) for k in (
                        "title", "source_id", "supplier_product_id", "cost", "currency",
                        "shipping_cost", "stock", "landed_cost", "match_score",
                        "shipping_days_min", "shipping_days_max", "image_url", "product_url",
                    )}
                    v_ctx = {"supplier_matches": [{"trend": {"topic": q, "rank": 1}, "query": q, "matches": [cand_dict]}]}
                    v_ctx = sentinel_vetting.run(v_ctx)
                    for group in v_ctx.get("sentinel_matches", []):
                        for p in group.get("matches", []):
                            vetted.append({
                                "title": p.get("title"),
                                "source_id": p.get("source_id"),
                                "supplier_product_id": p.get("supplier_product_id"),
                                "cost": p.get("cost"),
                                "shipping_cost": p.get("shipping_cost"),
                                "stock": p.get("stock"),
                                "landed_cost": p.get("landed_cost"),
                                "currency": p.get("currency"),
                                "match_score": p.get("match_score"),
                                "sentinel_score": p.get("sentinel_score"),
                                "sentinel_decision": p.get("sentinel_decision"),
                                "sentinel_warnings": p.get("sentinel_warnings"),
                                "projected_sell_price": p.get("projected_sell_price"),
                                "projected_margin_pct": p.get("projected_margin_pct"),
                                "image_url": p.get("image_url"),
                                "product_url": p.get("product_url"),
                            })
                        for r in group.get("rejected", []):
                            rejected.append({
                                "title": r.get("title"),
                                "source_id": r.get("source_id"),
                                "supplier_product_id": r.get("supplier_product_id"),
                                "sentinel_rejection_reasons": r.get("sentinel_rejection_reasons"),
                            })
                except Exception:
                    log.exception("preview_sentinel: vetting crashed for %r", m.get("title"))
            sentinel_matches.append({
                "query": q,
                "matches": vetted,
                "rejected": rejected,
                "summary": {"evaluated": len(matches), "passed": len(vetted), "rejected": len(rejected)},
            })

        return {
            "metadata": forge_result.get("metadata", {}),
            "sentinel_matches": sentinel_matches,
        }
    except Exception:
        log.exception("preview_sentinel crashed")
        return {"metadata": {"mode": "error"}, "sentinel_matches": []}


def _archive_approved_hil_rows() -> None:
    """Archive all approved HIL rows to a local file and reset to 'archived' in Supabase.

    Runs at pipeline start so old approvals never bleed into the new run's Shopify sync.
    The archive file is write-only history — nothing in the sync path reads it.
    """
    import json
    import os
    from datetime import datetime, timezone
    from el.supabase import HIL_REVIEWS_SCHEMA, HIL_REVIEWS_TABLE, SupabaseRestProvider
    try:
        db = SupabaseRestProvider()
        approved = db.select_rows(
            schema=HIL_REVIEWS_SCHEMA,
            table=HIL_REVIEWS_TABLE,
            filters={"approval_status": "eq.approved"},
            limit=500,
        )
        if not approved:
            log.info("EL pipeline: no approved rows to archive")
            return

        archive_path = "/app/data/approved_products_archive.json"
        os.makedirs(os.path.dirname(archive_path), exist_ok=True)
        existing: list = []
        if os.path.exists(archive_path):
            try:
                with open(archive_path) as f:
                    existing = json.load(f)
            except Exception:
                existing = []

        existing.append({
            "archived_at": datetime.now(timezone.utc).isoformat(),
            "products": approved,
        })
        with open(archive_path, "w") as f:
            json.dump(existing, f, indent=2, ensure_ascii=False, default=str)
        log.info("EL pipeline: archived %d approved row(s) to %s", len(approved), archive_path)

        db.update_rows(
            schema=HIL_REVIEWS_SCHEMA,
            table=HIL_REVIEWS_TABLE,
            filters={"approval_status": "eq.approved"},
            updates={"approval_status": "skipped"},
        )
        log.info("EL pipeline: reset %d approved row(s) to 'skipped' in Supabase", len(approved))
    except Exception:
        log.exception("EL pipeline: archive approved rows failed — continuing")


def _wait_for_hil_approvals(ctx: dict, *, timeout_minutes: int = 30, poll_interval: int = 30) -> None:
    """Block until all HIL rows from this run are reviewed or the timeout expires.

    Refreshes ctx['hil_review_rows'] with the latest data from Supabase before returning
    so that the Shopify upload at Step 13 sees the actual approval statuses.
    """
    import time
    from el.supabase import HIL_REVIEWS_SCHEMA, HIL_REVIEWS_TABLE, SupabaseRestProvider

    rows = ctx.get("hil_review_rows") or []
    if not rows:
        return

    row_ids = [str(r["id"]) for r in rows if r.get("id")]
    if not row_ids:
        return

    id_filter = f"in.({','.join(row_ids)})"
    db = SupabaseRestProvider()
    deadline = time.time() + timeout_minutes * 60
    log.info(
        "EL pipeline: waiting up to %d min for HIL approvals on %d row(s)",
        timeout_minutes, len(row_ids),
    )

    while time.time() < deadline:
        try:
            pending = db.select_rows(
                schema=HIL_REVIEWS_SCHEMA,
                table=HIL_REVIEWS_TABLE,
                filters={"approval_status": "eq.pending", "id": id_filter},
            )
            if not pending:
                log.info("EL pipeline: all HIL rows reviewed — proceeding")
                updated = db.select_rows(
                    schema=HIL_REVIEWS_SCHEMA,
                    table=HIL_REVIEWS_TABLE,
                    filters={"id": id_filter},
                )
                ctx["hil_review_rows"] = updated
                return
            log.info(
                "EL pipeline: %d row(s) still pending — next check in %ds",
                len(pending), poll_interval,
            )
        except Exception:
            log.exception("EL pipeline: HIL approval poll error — retrying")
        time.sleep(poll_interval)

    log.warning(
        "EL pipeline: HIL approval timeout (%d min) — proceeding with current approvals",
        timeout_minutes,
    )
    try:
        updated = db.select_rows(
            schema=HIL_REVIEWS_SCHEMA,
            table=HIL_REVIEWS_TABLE,
            filters={"id": id_filter},
        )
        ctx["hil_review_rows"] = updated
    except Exception:
        log.exception("EL pipeline: final HIL row refresh failed")


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

    # ── Step 0: Archive old approved rows + clear Shopify ───────────────────
    _archive_approved_hil_rows()
    if config.get("SHOPIFY_STORE_DOMAIN"):
        try:
            from el.nodes.upload_shopify_products import _clear_existing_products
            from el import shopify as _shopify
            _clear_existing_products(_shopify.default_provider())
            log.info("EL pipeline: cleared old Shopify products")
        except Exception:
            log.exception("EL pipeline: Shopify clear on startup failed — continuing")

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
        # Normalize passing Sentinel matches into HIL review rows so they feed
        # into phase4_candidate_selection alongside CJ/browserbase candidates.
        try:
            ctx = normalize_sentinel_review.run(ctx)
        except Exception:
            log.exception("EL pipeline: normalize_sentinel_review crashed")
        # Re-merge review sources so sentinel_review_items are included.
        try:
            ctx = merge_review_sources.run(ctx)
        except Exception:
            log.exception("EL pipeline: merge_review_sources (re-merge) crashed")
    else:
        log.info("EL pipeline: Forge pipeline disabled — skipping supplier_search + sentinel_vetting")

    # ── Step 6: Phase-4 candidate selection ─────────────────────────────────
    try:
        ctx = phase4_candidate_selection.run(ctx)
    except Exception:
        log.exception("EL pipeline: phase4_candidate_selection crashed")

    # ── Step 6b: Stochastic logger + HIL reviews insert ─────────────────────
    try:
        ctx = stochastic_logger.run(ctx)
    except Exception:
        log.exception("EL pipeline: stochastic_logger crashed")
    try:
        ctx = supabase_insert_hil_reviews.run(ctx)
    except Exception:
        log.exception("EL pipeline: supabase_insert_hil_reviews crashed")

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
        ctx = prepare_json_file.run(ctx)
    except Exception:
        log.exception("EL pipeline: prepare_json_file crashed")
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

    # ── Step 10: Curate picks → search queries → Telegram ────────────────────
    try:
        ctx = curate_picks.run(ctx)
    except Exception:
        log.exception("EL pipeline: curate_picks crashed")
    try:
        ctx = build_search_query.run(ctx)
    except Exception:
        log.exception("EL pipeline: build_search_query crashed")
    try:
        ctx = write_curated_picks.run(ctx)
    except Exception:
        log.exception("EL pipeline: write_curated_picks crashed")
    try:
        ctx = prepare_telegram_card.run(ctx)
    except Exception:
        log.exception("EL pipeline: prepare_telegram_card crashed")
    try:
        ctx = download_product_image.run(ctx)
    except Exception:
        log.exception("EL pipeline: download_product_image crashed")
    try:
        ctx = send_hil_telegram_photo.run(ctx)
    except Exception:
        log.exception("EL pipeline: send_hil_telegram_photo crashed")
    try:
        ctx = mark_telegram_photo_sent.run(ctx)
    except Exception:
        log.exception("EL pipeline: mark_telegram_photo_sent crashed")
    try:
        ctx = send_hil_telegram_text_fallback.run(ctx)
    except Exception:
        log.exception("EL pipeline: send_hil_telegram_text_fallback crashed")
    try:
        ctx = mark_telegram_text_fallback.run(ctx)
    except Exception:
        log.exception("EL pipeline: mark_telegram_text_fallback crashed")

    # ── Step 10b: Wait for human to approve/reject Telegram cards ────────────
    try:
        _wait_for_hil_approvals(ctx)
    except Exception:
        log.exception("EL pipeline: HIL approval wait crashed — continuing")

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
