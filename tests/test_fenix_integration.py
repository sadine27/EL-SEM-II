"""Full Fenix Engine integration smoke-test.

Exercises the complete Fenix path end-to-end:
  1. Source pipeline (multiple sources → TrendCandidate list)
  2. Keyword scoring + dedupe + rank (score_rank)
  3. AI scoring overlay (ai_score_trends, no-op when Vertex creds absent)
  4. Filter top 30

Uses monkeypatched sources so the test is self-contained (no network/API keys).
"""
from __future__ import annotations

from el import pipeline
from el.sources import TrendCandidate


def _make_src(source_id: str, titles: list[str]) -> object:
    """Build a fake source module that yields *titles* as TrendCandidate."""
    class _FakeSource:
        SOURCE_ID = source_id
        def fetch_trends(self, ctx) -> list[TrendCandidate]:
            now = "2026-06-03T12:00:00.000Z"
            return [
                TrendCandidate(
                    title=t,
                    source_id=source_id,
                    score_hint=0.8,
                    velocity=0.5,
                    fetched_at=now,
                )
                for t in titles
            ]
    return _FakeSource()


def _monkeypatch_downstream(monkeypatch):
    """Disable every pipeline node that requires credentials or real APIs."""
    monkeypatch.setattr(pipeline, "_load_enabled_sources", lambda: [])

    # Disable score_rank's inline Google News RSS (would pollute test with real data)
    monkeypatch.setattr(pipeline.score_rank, "fetch_news_rss", lambda: [])

    nodes = [
        "merge_review_sources", "supplier_search", "sentinel_vetting",
        "phase4_candidate_selection", "cj_get_token", "cj_product_list",
        "embed_candidate_products", "create_day_tab", "prepare_sheet_rows",
        "write_rows_to_sheet", "drive_upload", "create_curated_picks_tab",
        "curate_picks", "download_product_image", "prepare_telegram_card",
        "email_digest", "email_product_detail", "notify_business",
        "record_niche_performance", "generate_shopify_theme",
        "upload_shopify_theme", "upload_shopify_products",
    ]
    for name in nodes:
        monkeypatch.setattr(getattr(pipeline, name), "run", lambda ctx: ctx)


class TestFenixIntegration:

    def _run_fenix_pipeline(self, sources, monkeypatch) -> dict:
        """Run the Fenix subset of pipeline steps with given sources."""
        _monkeypatch_downstream(monkeypatch)
        monkeypatch.setattr(pipeline, "_load_enabled_sources", lambda: sources)

        ctx: dict = {}
        return pipeline.run(ctx)

    def test_fenix_with_multiple_sources(self, monkeypatch):
        """Feed topics from 3 sources; verify ranked output."""
        # NOTE: source_id "youtube" is filtered by score_rank's dedicated YouTube
        # processing path. Use distinct non-youtube source names for the fakes.
        sources = [
            _make_src("yt_test", ["Wireless Earbuds 2026", "Phone Case Clear"]),
            _make_src("rss_india", ["Gaming Mouse Trend India"]),
            _make_src("google_news_india", ["Standing Desk Popular"]),
        ]
        ctx = self._run_fenix_pipeline(sources, monkeypatch)

        payload = ctx["ranked_payload"]
        trends = payload.get("trends", [])
        assert len(trends) == 4, f"Expected 4 trends, got {len(trends)}"
        assert any("earbud" in t.get("topic", "").lower() for t in trends), (
            f"Expected 'Wireless Earbuds' in ranked trends: {[t['topic'] for t in trends]}"
        )

    def test_fenix_with_no_candidates(self, monkeypatch):
        """Empty source list → empty ranked payload."""
        sources: list[object] = []
        ctx = self._run_fenix_pipeline(sources, monkeypatch)
        payload = ctx.get("ranked_payload", {})
        assert payload.get("trends", []) == []

    def test_fenix_dedupe_near_duplicates(self, monkeypatch):
        """Two sources yield near-identical titles; dedupe collapses them."""
        sources = [
            _make_src("yt_test", ["Wireless Earbuds Noise Cancelling"]),
            _make_src("rss_india", ["wireless earbuds with noise cancellation"]),
        ]
        ctx = self._run_fenix_pipeline(sources, monkeypatch)
        payload = ctx["ranked_payload"]
        trends = payload.get("trends", [])
        # Should be 1 trend (deduped) — "noise cancellation" overlap triggers dedupe
        assert len(trends) == 1, (
            f"Expected 1 trend after dedupe, got {len(trends)}: {[t['topic'] for t in trends]}"
        )

    def test_fenix_dedupe_keeps_distinct_items(self, monkeypatch):
        """Two very different titles from 2 sources → 2 distinct trends."""
        sources = [
            _make_src("yt_test", ["Wireless Earbuds Top Quality"]),
            _make_src("rss_india", ["Standing Desk Adjustable"]),
        ]
        ctx = self._run_fenix_pipeline(sources, monkeypatch)
        payload = ctx["ranked_payload"]
        trends = payload.get("trends", [])
        assert len(trends) == 2, (
            f"Expected 2 distinct trends, got {len(trends)}"
        )

    def test_fenix_score_rank_keyword_priorities(self, monkeypatch):
        """Buyer keywords ('buy', 'cheap') should outrank ambient keywords."""
        sources = [
            _make_src("test_source", [
                "Best Wireless Earbuds 2026",
                "buy cheap phone case online",
                "Movie Trailer New Release",
            ]),
        ]
        ctx = self._run_fenix_pipeline(sources, monkeypatch)
        trends = ctx["ranked_payload"]["trends"]

        # Find ranks
        phone_rank = next(
            (t["rank"] for t in trends if "phone case" in t["topic"].lower()), None
        )
        movie_rank = next(
            (t["rank"] for t in trends if "movie" in t["topic"].lower()), None
        )
        # Phone case has buyer keywords → should outrank movie trailer
        if phone_rank is not None and movie_rank is not None:
            assert phone_rank < movie_rank, (
                f"'phone case' (rank {phone_rank}) should outrank "
                f"'movie trailer' (rank {movie_rank})"
            )

    def test_fenix_pipeline_survives_error_in_one_source(self, monkeypatch):
        """A crashing source does not block other sources."""
        class _CrashSource:
            SOURCE_ID = "crash"
            def fetch_trends(self, ctx):
                raise RuntimeError("network error")

        sources = [
            _CrashSource(),
            _make_src("good_source", ["Wireless Earbuds"]),
        ]
        ctx = self._run_fenix_pipeline(sources, monkeypatch)
        trends = ctx["ranked_payload"]["trends"]
        assert len(trends) == 1, f"Expected 1 trend despite crash, got {len(trends)}"

    def test_fenix_with_ai_scoring_disabled(self, monkeypatch):
        """AI-scored topics = 0 when Vertex creds absent."""
        monkeypatch.delenv("GOOGLE_SERVICE_ACCOUNT_JSON", raising=False)
        sources = [
            _make_src("test_source", ["Wireless Earbuds"]),
        ]
        ctx = self._run_fenix_pipeline(sources, monkeypatch)
        meta = ctx["ranked_payload"].get("metadata", {})
        assert meta.get("ai_scored_count", 0) == 0
        for t in ctx["ranked_payload"]["trends"]:
            assert "product_intent_score" in t
