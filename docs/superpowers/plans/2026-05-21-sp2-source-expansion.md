# SP2 — Source Expansion Implementation Plan

**Spec:** `docs/superpowers/specs/2026-05-21-sp2-source-expansion-design.md`
**Branch:** `feat/sp2-source-expansion`
**Estimated effort:** ~3 focused sessions (well under master-spec's 5–7 days because the deferred sources cut scope).

Tasks executed in order. Every task ends with green tests and a commit.

---

## Task 0: .env.example documentation

- [ ] **Step 1:** Append the SP2 env vars to `.env.example` in a `# --- SP2 (Source Expansion) ---` section. Variables: `EL_SOURCES_ENABLED` (default `youtube`), `EL_SHOPIFY_COMPETITOR_STORES` (default empty), `EL_SHOPIFY_COMPETITOR_MAX_PAGES` (default `4`).
- [ ] **Step 2:** Commit:

```
docs(sp2): document EL_SOURCES_ENABLED and Shopify-competitor env vars
```

---

## Task 1: `Source` protocol + `TrendCandidate`

**Files:**
- Create: `el/sources/__init__.py`
- Create: `tests/test_sources_protocol.py`

### TDD: write tests first

- [ ] **Step 1:** Create `tests/test_sources_protocol.py`:

```python
"""Tests for el/sources/__init__.py — Source protocol + TrendCandidate."""
from __future__ import annotations

import pytest

from el.sources import Source, TrendCandidate


def test_trend_candidate_is_frozen():
    c = TrendCandidate(title="t", source_id="x", raw_payload={})
    with pytest.raises(Exception):
        c.title = "modified"  # type: ignore[misc]


def test_trend_candidate_default_fields():
    c = TrendCandidate(title="t", source_id="x", raw_payload={"k": "v"})
    assert c.region == "IN"
    assert c.score_hint is None
    assert c.fetched_at is None
    assert c.raw_payload == {"k": "v"}


def test_source_protocol_runtime_check_recognizes_conforming_class():
    class GoodSource:
        SOURCE_ID = "good"
        def fetch_trends(self, ctx):
            return []
    assert isinstance(GoodSource(), Source)


def test_source_protocol_runtime_check_rejects_missing_method():
    class BadSource:
        SOURCE_ID = "bad"
    assert not isinstance(BadSource(), Source)
```

- [ ] **Step 2:** Run the tests. Expect import-error failures.

```
.venv\Scripts\python.exe -m pytest tests/test_sources_protocol.py -v
```

### Implementation

- [ ] **Step 3:** Create `el/sources/__init__.py`:

```python
"""Trend-source protocol + shared types.

Every concrete source lives at `el/sources/<source>.py` with a top-level
`SOURCE_ID` constant and a `fetch_trends(ctx)` function returning a list
of `TrendCandidate`. See docs/superpowers/specs/2026-05-21-sp2-source-expansion-design.md.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class TrendCandidate:
    title: str
    source_id: str
    raw_payload: dict = field(default_factory=dict)
    score_hint: float | None = None
    region: str = "IN"
    fetched_at: str | None = None


@runtime_checkable
class Source(Protocol):
    SOURCE_ID: str
    def fetch_trends(self, ctx: dict) -> list[TrendCandidate]: ...
```

- [ ] **Step 4:** Tests pass.
- [ ] **Step 5:** Commit:

```
feat(sp2): add Source protocol + TrendCandidate dataclass
```

---

## Task 2: YouTube source wrapper

**Files:**
- Create: `el/sources/youtube.py`
- Create: `tests/test_sources_youtube.py`

### TDD

- [ ] **Step 1:** Create `tests/test_sources_youtube.py`:

```python
"""Tests for el/sources/youtube.py — protocol-conforming wrapper."""
from __future__ import annotations

from el.sources import Source, TrendCandidate
from el.sources import youtube as youtube_source


def test_youtube_source_id():
    assert youtube_source.SOURCE_ID == "youtube"


def test_youtube_satisfies_source_protocol():
    assert isinstance(youtube_source, Source)


def test_fetch_trends_wraps_youtube_items_as_trend_candidates(monkeypatch):
    fake_items = [
        {"id": "vid1", "snippet": {"title": "Wireless earbuds review", "channelTitle": "TechCh"}},
        {"id": "vid2", "snippet": {"title": "Best mixer grinders 2026", "channelTitle": "HomeCh"}},
    ]

    def fake_run(ctx):
        ctx["youtube_items"] = fake_items
        ctx["youtube_trending_result"] = {"ok": True, "count": len(fake_items)}
        return ctx

    monkeypatch.setattr("el.nodes.youtube_trending.run", fake_run)
    candidates = youtube_source.fetch_trends({})
    assert len(candidates) == 2
    for c, item in zip(candidates, fake_items):
        assert isinstance(c, TrendCandidate)
        assert c.title == item["snippet"]["title"]
        assert c.source_id == "youtube"
        assert c.raw_payload == item


def test_fetch_trends_returns_empty_on_failure(monkeypatch):
    def fake_run(ctx):
        ctx["youtube_items"] = []
        ctx["youtube_trending_result"] = {"ok": False, "error": "boom"}
        return ctx
    monkeypatch.setattr("el.nodes.youtube_trending.run", fake_run)
    assert youtube_source.fetch_trends({}) == []


def test_fetch_trends_skips_items_without_title(monkeypatch):
    """Defensive: an item missing snippet.title is dropped, not raised on."""
    def fake_run(ctx):
        ctx["youtube_items"] = [{"id": "x", "snippet": {}}, {"id": "y", "snippet": {"title": "kept"}}]
        return ctx
    monkeypatch.setattr("el.nodes.youtube_trending.run", fake_run)
    candidates = youtube_source.fetch_trends({})
    assert len(candidates) == 1
    assert candidates[0].title == "kept"
```

- [ ] **Step 2:** Failing tests.

### Implementation

- [ ] **Step 3:** Create `el/sources/youtube.py`:

```python
"""Trend source: YouTube Trending IN.

Thin wrapper over `el/nodes/youtube_trending.run` that adapts the existing
node's output to the `TrendCandidate` shape. No new network calls.
"""
from __future__ import annotations

from el.logger import get_logger
from el.nodes import youtube_trending
from el.sources import TrendCandidate

SOURCE_ID = "youtube"

log = get_logger(__name__)


def fetch_trends(ctx: dict) -> list[TrendCandidate]:
    try:
        youtube_trending.run(ctx)
    except Exception:
        log.exception("youtube source: youtube_trending.run crashed")
        return []
    items = ctx.get("youtube_items") or []
    candidates: list[TrendCandidate] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        snippet = item.get("snippet") or {}
        title = snippet.get("title") if isinstance(snippet, dict) else None
        if not title:
            continue
        candidates.append(TrendCandidate(
            title=str(title),
            source_id=SOURCE_ID,
            raw_payload=item,
        ))
    return candidates
```

- [ ] **Step 4:** Tests pass. Full suite green.
- [ ] **Step 5:** Commit:

```
feat(sp2): add YouTube source (protocol wrapper over youtube_trending)
```

---

## Task 3: Shopify competitor source

**Files:**
- Create: `el/sources/shopify_competitor.py`
- Create: `tests/test_sources_shopify_competitor.py`

### TDD

- [ ] **Step 1:** Create `tests/test_sources_shopify_competitor.py`. Covers:
  - `SOURCE_ID == "shopify_competitor"`.
  - Empty `EL_SHOPIFY_COMPETITOR_STORES` → returns `[]`, no HTTP calls.
  - Single store, single page with N products → N `TrendCandidate`s with correct `source_id`.
  - Pagination: page 1 returns full 250, page 2 returns 0 → stops after page 1 (no extra call).
  - `EL_SHOPIFY_COMPETITOR_MAX_PAGES=2` caps pagination.
  - HTTP 404 on one store → that store dropped, other stores still processed.
  - JSON decode error → that store dropped.
  - Timeout → that store dropped.
  - URL trailing-slash normalization (`https://shop.com/` and `https://shop.com` both work).

Use `requests_mock` or monkeypatch on `requests.get`.

- [ ] **Step 2:** Failing tests.

### Implementation

- [ ] **Step 3:** Create `el/sources/shopify_competitor.py`:

Key implementation points:
- Read `EL_SHOPIFY_COMPETITOR_STORES` (comma-separated URLs) and `EL_SHOPIFY_COMPETITOR_MAX_PAGES` (int, default 4).
- For each store URL: strip trailing slash, then GET `{url}/products.json?limit=250&page={n}` for n=1..max_pages.
- Stop pagination when a page returns 0 products or non-JSON.
- Per-store try/except — log warning and skip on error; the function never raises.
- Each product becomes `TrendCandidate(title=product["title"], source_id=f"shopify_competitor:{store_handle}", raw_payload=product, score_hint=...)`.
- `store_handle` derived from URL host: strip protocol, take first label (e.g. `https://examplestore.com` → `examplestore`).

- [ ] **Step 4:** Tests pass. Full suite green.
- [ ] **Step 5:** Commit:

```
feat(sp2): add Shopify competitor source (public /products.json endpoint)
```

---

## Task 4: Pipeline source-loop

**Files:**
- Modify: `el/pipeline.py`
- Create: `tests/test_pipeline_source_loop.py`

### TDD

- [ ] **Step 1:** Create `tests/test_pipeline_source_loop.py`. Covers:
  - `_load_enabled_sources()` default returns `[youtube_source]`.
  - `EL_SOURCES_ENABLED="youtube,shopify_competitor"` returns both.
  - `EL_SOURCES_ENABLED="youtube,doesnotexist"` returns `[youtube_source]` and logs warning.
  - When the pipeline runs with `EL_SOURCES_ENABLED="youtube"` and no other state, `ctx["source_candidates"]` is set and equal in content to the YouTube source's output.
  - A source that raises during `fetch_trends` does not crash the loop; `ctx["source_candidates"]` still gets the survivors.

- [ ] **Step 2:** Failing tests.

### Implementation

- [ ] **Step 3:** Modify `el/pipeline.py`:
  - Add import: `from el.sources import youtube as youtube_source, shopify_competitor as shopify_competitor_source` (and keep existing imports).
  - Add helper `_load_enabled_sources() -> list` that reads `EL_SOURCES_ENABLED`, maps each name to its source module (`{"youtube": youtube_source, "shopify_competitor": shopify_competitor_source}`), logs WARNING on unknown names, returns the matched modules in input order.
  - Add a block immediately after `log.info("EL pipeline run start")` that builds `ctx["source_candidates"]` by calling `fetch_trends(ctx)` on each enabled source inside a try/except (any failure logs and contributes `[]`).
  - Keep the existing `youtube_trending.run(ctx)` call as-is for now — sources don't yet feed `score_rank`. The new `ctx["source_candidates"]` is additive.

- [ ] **Step 4:** Tests pass. Full suite green.
- [ ] **Step 5:** Commit:

```
feat(sp2): pipeline loads enabled sources into ctx["source_candidates"]
```

---

## Task 5: Iteration log + roadmap update

**Files:**
- Create: `docs/SP2_LOG.md`
- Modify: `PHASE3_ROADMAP.md`

- [ ] **Step 1:** Write `docs/SP2_LOG.md` mirroring `docs/SP1_LOG.md`'s structure: summary, what changed table, commits-in-order table, deploy runbook, rollback, acceptance verification, surprises/decisions.
- [ ] **Step 2:** Update `PHASE3_ROADMAP.md`:
  - Flip SP2 status to "🟢 code complete, pre-merge".
  - Update last-updated date.
  - Update "Next action" to "Merge SP2 to main, then start SP3 brainstorming".
- [ ] **Step 3:** Commit (two commits ok):

```
docs(sp2): add SP2 iteration log + deploy runbook
docs(phase3): mark SP2 code-complete; advance Next action
```

---

## Merge

After all tasks green, merge per `PHASE3_ROADMAP.md` strategy (squash this time — branch contains only SP2 work):

```
git checkout main
git merge --squash feat/sp2-source-expansion
git commit -m "feat(sp2): Source Expansion (protocol + YouTube + Shopify competitor)"
```

Then update `PHASE3_ROADMAP.md` to flip SP2 to ✅ merged, advance next action to SP3.
