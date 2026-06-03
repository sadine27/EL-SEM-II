# EL Codebase Line-by-Line Technical Report — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce a complete, developer-facing, line-by-line Markdown walkthrough of the entire EL codebase under `docs/report/`, with a coverage checker proving no production file is left undocumented.

**Architecture:** One Markdown file per subsystem **Part** (20 files), flow-ordered within each Part. A stdlib-only Python coverage checker (`scripts/check_report_coverage.py`) enumerates the 146 in-scope production files and asserts each appears as a `### \`<path>\`` section heading somewhere under `docs/report/`, and that each of the 122 test files is named in Part 17. The checker starts **red** (all uncovered) and goes **green** as Parts are written — this is the deliverable's "test." Work is committed Part-by-Part so it is fully resumable.

**Tech Stack:** Markdown (GitHub-flavored), inline Mermaid diagrams, Python 3.12 standard library (checker only — no new dependencies, no PDF/pandoc tooling), git.

**Spec:** `docs/superpowers/specs/2026-06-03-codebase-report-design.md` (authoritative for scope, organization, per-file template, and conventions).

---

## Scope check

Single coherent deliverable (one report document) — not multiple independent subsystems. One plan, 21 tasks: scaffold + harness (Task 1), one Part each (Tasks 2–20), final verification (Task 21).

## File structure

Created by this plan:

```
docs/report/
  00-index.md                       TOC, reading guide, coverage matrix
  01-overview.md                    prose: port story, glossary, repo map
  02-architecture.md                prose + Mermaid: ctx contract, exec order, deploy
  03-entrypoints-and-orchestrator.md  line-by-line
  04-foundation-and-providers.md      line-by-line
  05-fenix-sources.md                 line-by-line
  06-fenix-scoring-and-calibration.md line-by-line
  07-forge-supplier-sourcing.md       line-by-line
  08-sentinel-vetting.md              line-by-line
  09-selection-curation-embeddings.md line-by-line
  10-sheets-drive-persistence.md      line-by-line
  11-hil-telegram-review.md           line-by-line + Mermaid state machine
  12-shopify-autostore.md             line-by-line
  13-outbound-email-crm.md            line-by-line
  14-web-app.md                       line-by-line
  15-operational-scripts.md           line-by-line
  16-migrations-and-data.md           line-by-line (SQL) + data shapes
  17-test-suite.md                    per-file summaries (122 files)
  18-legacy-and-paper.md              structural map + paper summary
  19-appendix-environment-build.md    config/build reference
scripts/
  check_report_coverage.py          stdlib coverage gate (the "test")
```

Each report file has **one responsibility**: a single subsystem's walkthrough. Files that change together (a subsystem's nodes) live together in one Part file.

---

## Standard Part Procedure (read once; every Part task follows it)

Every line-by-line Part task (Tasks 4–17, 20) executes these five steps. The per-file template and verification are fully specified here so each task only needs to supply its **file list**.

**Per-file section template** — for each file in the Part, write, in order:

````
### `<relative/path>`

*<N> lines · <one-line purpose>*

**Role.** Where it sits in the flow; who calls it; what it depends on. For
`el/nodes/*`: the exact `ctx` keys it **reads** and the keys it **writes**.

**Walkthrough.** The real code in logical chunks (one function/block per chunk).
Each chunk = a fenced code block of the actual code, followed by a bullet list
that accounts for **every line**: trivial lines grouped in one bullet, non-obvious
lines called out individually with the *why*, edge cases, and gotchas.

**Failure & gating.** Fail-soft behavior, env gates, what it logs.

**Observations.** *(optional)* One short call-out only where a genuine bug, risk,
security concern, TODO, or smell exists. Omit the heading entirely if none.

**See also.** Cross-links to related report sections / `path:line` refs.
````

The chunk-and-annotate texture is the worked example in spec §7 (`_forge_pipeline_enabled`). The heading **must** be `### ` followed by the backtick-quoted path exactly as listed (this is what the checker greps for).

Each Part file opens with a short **Part intro**: the subsystem, its files, how they interconnect, and a Mermaid diagram where it helps.

**The five steps:**

- [ ] **Step 1 — Read.** Read every file in this Part's file list *in full* (use the Read tool; do not skim). Also read any cross-referenced doc named in the Part notes.
- [ ] **Step 2 — Write.** Create `docs/report/<NN-name>.md`: Part intro, then one section per file using the template above, in the order listed.
- [ ] **Step 3 — Verify coverage.** Run `python scripts/check_report_coverage.py`. Expected: the files in this Part move from UNCOVERED to covered; if any file you just wrote still shows UNCOVERED, your heading text doesn't match its path — fix the heading. Any *other* file the checker flags that belongs in this Part must be added now.
- [ ] **Step 4 — Tick the matrix.** Update the coverage matrix rows in `docs/report/00-index.md` for this Part (☐ → ☑).
- [ ] **Step 5 — Commit.** `git add docs/report/<NN-name>.md docs/report/00-index.md && git commit -m "docs(report): Part <NN> — <name>"`.

---

## Task 1: Scaffold + coverage harness

**Files:**
- Create: `scripts/check_report_coverage.py`
- Create: `docs/report/00-index.md`

- [ ] **Step 1: Write the coverage checker**

```python
#!/usr/bin/env python3
"""Coverage gate for the docs/report/ line-by-line codebase report.

Verifies every in-scope production file has a line-by-line section (a
'### `<path>`' heading) somewhere under docs/report/, and that every test file is
named in docs/report/17-test-suite.md. Stdlib-only; no third-party deps.

Exit 0 when fully covered, 1 otherwise. Run from the repo root:
    python scripts/check_report_coverage.py
"""
from __future__ import annotations

import glob
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPORT_DIR = ROOT / "docs" / "report"

# Created by the reporting effort itself — not part of the documented product.
SELF = {"scripts/check_report_coverage.py"}

# Production globs that get a line-by-line section (spec §3, §6).
PROD_PATTERNS = [
    "el/**/*.py",
    "scripts/**/*.py",
    "migrations/**/*.sql",
    "el/web/templates/*.html",
    "el/web/static/*.css",
    "el/assets/theme_shells/sections/*.liquid",
    "legacy/apply_bcc_phase_i.py",
]


def _posix(p: Path) -> str:
    return p.relative_to(ROOT).as_posix()


def _iter(patterns):
    for pat in patterns:
        for hit in glob.glob(str(ROOT / pat), recursive=True):
            path = Path(hit)
            if path.is_file() and "__pycache__" not in path.parts:
                yield path


def in_scope_production() -> list[str]:
    files = sorted({_posix(p) for p in _iter(PROD_PATTERNS)})
    return [f for f in files if f not in SELF]


def test_files() -> list[str]:
    return sorted({_posix(p) for p in _iter(["tests/**/*.py"])})


def heading_paths() -> set[str]:
    """Backtick-quoted paths appearing on a '###'+ heading line in any report md."""
    found: set[str] = set()
    for md in glob.glob(str(REPORT_DIR / "*.md")):
        for line in Path(md).read_text(encoding="utf-8").splitlines():
            stripped = line.lstrip()
            if stripped.startswith("###"):
                parts = stripped.split("`")
                for i in range(1, len(parts), 2):  # odd indices = inside backticks
                    found.add(parts[i].strip())
    return found


def tests_doc_text() -> str:
    f = REPORT_DIR / "17-test-suite.md"
    return f.read_text(encoding="utf-8") if f.exists() else ""


def main() -> int:
    if not REPORT_DIR.exists():
        print(f"FAIL: {REPORT_DIR} does not exist yet")
        return 1

    headings = heading_paths()
    prod = in_scope_production()
    uncovered = [f for f in prod if f not in headings]

    tests = test_files()
    tdoc = tests_doc_text()
    tests_missing = [f for f in tests if f not in tdoc]

    print(f"Production files in scope : {len(prod)}")
    print(f"  covered (### heading)   : {len(prod) - len(uncovered)}")
    print(f"  UNCOVERED               : {len(uncovered)}")
    for f in uncovered:
        print(f"    - {f}")
    print(f"Test files                : {len(tests)}")
    print(f"  named in 17-test-suite  : {len(tests) - len(tests_missing)}")
    print(f"  MISSING                 : {len(tests_missing)}")
    for f in tests_missing:
        print(f"    - {f}")

    ok = not uncovered and not tests_missing
    print("\nRESULT:", "PASS - full coverage" if ok else "FAIL - see lists above")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Create the report directory + index skeleton**

Create `docs/report/00-index.md`:

```markdown
# EL Codebase — Line-by-Line Technical Report

Developer reference for the EL Python Port. Read **01-overview** then
**02-architecture** first; the per-subsystem Parts can be read in any order.

## Reading guide
- **01 Overview** — what EL is, the n8n→Python port, glossary, repo map.
- **02 Architecture** — the `ctx` contract, pipeline execution order, gating, deploy.
- **03–16, 18** — line-by-line walkthroughs (every production file).
- **17** — test-suite summaries.
- **19** — environment & build reference.

## Coverage matrix
Authoritative gate: `python scripts/check_report_coverage.py` (PASS = complete).
This table mirrors it for humans; ☑ = section written.

| Part | File | Status |
|------|------|--------|
| 03 | 03-entrypoints-and-orchestrator.md | ☐ |
| 04 | 04-foundation-and-providers.md | ☐ |
| 05 | 05-fenix-sources.md | ☐ |
| 06 | 06-fenix-scoring-and-calibration.md | ☐ |
| 07 | 07-forge-supplier-sourcing.md | ☐ |
| 08 | 08-sentinel-vetting.md | ☐ |
| 09 | 09-selection-curation-embeddings.md | ☐ |
| 10 | 10-sheets-drive-persistence.md | ☐ |
| 11 | 11-hil-telegram-review.md | ☐ |
| 12 | 12-shopify-autostore.md | ☐ |
| 13 | 13-outbound-email-crm.md | ☐ |
| 14 | 14-web-app.md | ☐ |
| 15 | 15-operational-scripts.md | ☐ |
| 16 | 16-migrations-and-data.md | ☐ |
| 17 | 17-test-suite.md | ☐ |
| 18 | 18-legacy-and-paper.md | ☐ |
| 19 | 19-appendix-environment-build.md | ☐ |
```

- [ ] **Step 3: Run the checker to verify it fails (red)**

Run: `python scripts/check_report_coverage.py`
Expected: `Production files in scope : 146`, `UNCOVERED : 146`, `Test files : 122`, `MISSING : 122`, `RESULT: FAIL`. (Exit code 1.)

- [ ] **Step 4: Commit**

```bash
git add scripts/check_report_coverage.py docs/report/00-index.md
git commit -m "docs(report): scaffold report dir + stdlib coverage gate"
```

---

## Task 2: Part 01 — Overview & glossary

**Files:** Create `docs/report/01-overview.md`. (Prose Part — no per-file coverage headings.)

- [ ] **Step 1: Read** `README.md`, `docs/PORT_LOG.md`, `docs/FENIX_LOG.md`, `docs/FORGE_ENGINE_HANDOFF.md`, `docs/SENTINEL_ENGINE_PLAN.md`, `PHASE3_ROADMAP.md`.
- [ ] **Step 2: Write** `01-overview.md`: what EL is and does; the n8n→Python port story and "legacy is source of truth" principle; capabilities tour; the **glossary** (Fenix, Forge, Sentinel, HIL, BCC/posteriors, `ctx`, node, source, supplier, provider); a top-level repo map (table of top-level dirs → responsibility).
- [ ] **Step 3: Commit** `git add docs/report/01-overview.md && git commit -m "docs(report): Part 01 — overview & glossary"`.

---

## Task 3: Part 02 — Architecture & runtime model

**Files:** Create `docs/report/02-architecture.md`. (Prose + diagrams.)

- [ ] **Step 1: Read** `el/pipeline.py`, `el/__main__.py`, `el/config.py`, `Dockerfile`, `docker-compose.yml`, `docker-entrypoint.sh`, `Caddyfile`, `run-daily.ps1`, `Makefile`.
- [ ] **Step 2: Write** `02-architecture.md`:
  - The **`ctx` contract**: one shared dict threaded through nodes; how keys accrue.
  - **Execution order**: a Mermaid `flowchart TD` mirroring `pipeline.run()` (sources → `score_rank` → `ai_score_trends` → Forge/Sentinel → Sheets/Drive → CJ path → HIL/Telegram → email → Shopify → notify → CRM), annotated with the env gate on each stage.
  - **Fail-soft & gating philosophy**: continue-on-fail, credential gates, retired sources.
  - **Config/env model**: `config.get/require`, `.env.example` as the catalog.
  - **Deploy topology**: Mermaid of Docker + Caddy + worker + cron (`run-daily.ps1`), referencing `docs/runbooks/deploy*.md`.
  - The CLI surface (`run`/`trends`/`forge`/`sentinel`).
- [ ] **Step 3: Verify** the Mermaid renders (no syntax error) by eyeballing fenced ```mermaid blocks.
- [ ] **Step 4: Commit** `git add docs/report/02-architecture.md && git commit -m "docs(report): Part 02 — architecture & runtime model"`.

---

## Task 4: Part 03 — Entry points & orchestrator

Follow the **Standard Part Procedure** for `docs/report/03-entrypoints-and-orchestrator.md`.

**Files (in order):**
- `el/__main__.py`
- `el/pipeline.py`
- `el/worker.py`
- `run.py`
- `run-daily.ps1`
- `el/nodes/__init__.py`

**Part notes:** Open with a Mermaid sequence of `python -m el run` → `error_handler()` → `pipeline.run(ctx)`. For `pipeline.py`, document each gated stage and the `ctx` keys it threads (this section is the spine other Parts link back to). `run-daily.ps1` is the cron entry; `run.py` is the thin root launcher. Verify command (Step 3): `python scripts/check_report_coverage.py`.

---

## Task 5: Part 04 — Foundation & cross-cutting providers

Follow the **Standard Part Procedure** for `docs/report/04-foundation-and-providers.md`.

**Files (in order):**
- `el/__init__.py`
- `el/config.py`
- `el/logger.py`
- `el/error_handler.py`
- `el/supabase.py`
- `el/llm.py`
- `el/telegram.py`
- `el/google_sheets.py`
- `el/google_drive.py`
- `el/browserbase.py`

**Part notes:** These are the cross-cutting wrappers many subsystems import. For each provider, document auth (env vars), the public surface other modules call, and retry/timeout/fail-soft behavior. Note the assignment rule: single-subsystem providers are documented with their subsystem (`shopify`→12, `email`/`crm`→13, `cj`/`tavily`→07, `embeddings`→09, `hil_fx`→11).

---

## Task 6: Part 05 — Fenix I: trend sources

Follow the **Standard Part Procedure** for `docs/report/05-fenix-sources.md`.

**Files (in order):**
- `el/sources/__init__.py`
- `el/sources/youtube.py`
- `el/sources/rss_india_source.py`
- `el/sources/google_news_india_source.py`
- `el/sources/ai_trend_discovery.py`
- `el/sources/shopify_competitor.py`
- `el/sources/pytrends_source.py`
- `el/sources/reddit_source.py`
- `el/sources/newsapi_source.py`
- `el/sources/amazon_in_source.py`
- `el/nodes/youtube_trending.py`

**Part notes:** Open with the `TrendCandidate` shape and the `SOURCE_ID`/`fetch_trends(ctx)` contract from `sources/__init__.py`. Mark the four default-enabled sources vs. the retired-but-importable ones (per `_SOURCE_REGISTRY` in `pipeline.py`). Each source: which `ctx` key it feeds.

---

## Task 7: Part 06 — Fenix II: scoring, ranking & Bayesian calibration

Follow the **Standard Part Procedure** for `docs/report/06-fenix-scoring-and-calibration.md`.

**Files (in order):**
- `el/nodes/score_rank.py`
- `el/nodes/ai_score_trends.py`
- `el/nodes/prepare_gemini_prompt.py`
- `el/nodes/parse_agent_output.py`
- `el/nodes/read_bcc_posteriors.py`
- `el/nodes/bcc_calibrate_selection.py`
- `el/nodes/update_bcc_posterior.py`
- `el/nodes/stochastic_logger.py`

**Part notes:** `score_rank.py` (623L) and the BCC posterior nodes are the analytical core — budget extra detail. Cross-link the Bayesian calibration to Part 15 (`scripts/bayesian_calibration.py`) and Part 18 (paper). Read `data/category_posteriors.json` and `data/bcc_posteriors_schema.sql` for context.

---

## Task 8: Part 07 — Forge: supplier sourcing

Follow the **Standard Part Procedure** for `docs/report/07-forge-supplier-sourcing.md`.

**Files (in order):**
- `el/suppliers/__init__.py`
- `el/suppliers/cj_source.py`
- `el/suppliers/marketplace_source.py`
- `el/cj.py`
- `el/tavily.py`
- `el/nodes/supplier_search.py`
- `el/nodes/build_search_query.py`
- `el/nodes/build_tavily_query.py`
- `el/nodes/tavily_search_in_market.py`
- `el/nodes/if_tavily_content_thin.py`
- `el/nodes/cj_get_token.py`
- `el/nodes/cj_product_list.py`
- `el/nodes/pick_top_3.py`
- `el/nodes/normalize_cj_review.py`

**Part notes:** Distinguish the Forge engine (`supplier_search` over `suppliers/`) from the legacy CJ path (`cj_*` nodes). Document the supplier-match dict shape (landed_cost, stock, shipping_days). Cross-ref `docs/FORGE_ENGINE_HANDOFF.md`.

---

## Task 9: Part 08 — Sentinel: vetting & believable economics

Follow the **Standard Part Procedure** for `docs/report/08-sentinel-vetting.md`.

**Files (in order):**
- `el/nodes/sentinel_vetting.py`
- `el/nodes/normalize_sentinel_review.py`

**Part notes:** Read `docs/SENTINEL_ENGINE_PLAN.md` and `docs/superpowers/specs/2026-06-03-pipeline-believable-economics-design.md` first. Document the economics model (projected margin/sell price, pass/reject reasons, warnings) and how vetted picks fold into the HIL pool as the `forge_sentinel` provider (link to Part 11).

---

## Task 10: Part 09 — Selection, curation & embeddings

Follow the **Standard Part Procedure** for `docs/report/09-selection-curation-embeddings.md`.

**Files (in order):**
- `el/nodes/merge_review_sources.py`
- `el/nodes/phase4_candidate_selection.py`
- `el/nodes/curate_picks.py`
- `el/nodes/filter_top_30.py`
- `el/nodes/pick_indian_listings.py`
- `el/embeddings.py`
- `el/nodes/embed_candidate_products.py`
- `el/nodes/find_similar_products.py`
- `el/nodes/gemini_extract_product.py`

**Part notes:** `phase4_candidate_selection.py` (878L) is the largest file — budget the most detail; break it function-by-function. Document the provider-capping/merge logic and the pgvector embedding flow (link to Part 16 migration `sp3`).

---

## Task 11: Part 10 — Sheets, Drive & JSON persistence

Follow the **Standard Part Procedure** for `docs/report/10-sheets-drive-persistence.md`.

**Files (in order):**
- `el/nodes/create_day_tab.py`
- `el/nodes/create_curated_picks_tab.py`
- `el/nodes/prepare_sheet_rows.py`
- `el/nodes/write_rows_to_sheet.py`
- `el/nodes/prepare_json_file.py`
- `el/nodes/drive_upload.py`
- `el/nodes/write_curated_picks.py`
- `el/nodes/strip_html.py`
- `el/nodes/create_day_tab_scraped.py`
- `el/nodes/prepare_sheet_rows_scraped.py`
- `el/nodes/sheet_append_scraped.py`
- `el/nodes/bundle_json_scraped.py`
- `el/nodes/drive_upload_scraped.py`
- `el/nodes/supabase_insert_scraped.py`

**Part notes:** Group the main path and the parallel `_scraped` path; note where each reads/writes Sheets vs. Drive vs. Supabase. Providers `google_sheets`/`google_drive` were documented in Part 04 — link, don't repeat.

---

## Task 12: Part 11 — HIL: Telegram human-in-the-loop

Follow the **Standard Part Procedure** for `docs/report/11-hil-telegram-review.md`.

**Files (in order):**
- `el/nodes/supabase_insert_hil_reviews.py`
- `el/nodes/prepare_telegram_card.py`
- `el/nodes/download_product_image.py`
- `el/nodes/send_hil_telegram_photo.py`
- `el/nodes/mark_telegram_photo_sent.py`
- `el/nodes/send_hil_telegram_text_fallback.py`
- `el/nodes/mark_telegram_text_fallback.py`
- `el/nodes/parse_hil_callback.py`
- `el/nodes/answer_hil_callback.py`
- `el/nodes/apply_hil_callback.py`
- `el/nodes/if_callback_finalized_review.py`
- `el/nodes/edit_hil_message.py`
- `el/nodes/delete_hil_message.py`
- `el/nodes/log_hil_message_edited.py`
- `el/nodes/log_hil_message_deleted.py`
- `el/nodes/send_hil_fx.py`
- `el/nodes/normalize_browserbase_review.py`
- `el/nodes/browserbase_fetch.py`
- `el/hil_fx.py`
- `el/hil_poller.py`

**Part notes:** Open with a Mermaid `stateDiagram-v2` of the HIL lifecycle (sent → callback → approve/reject/edit → finalized → applied). Read `docs/hil-review-contract.md` first. Document the callback payload shape and the poller loop. Cross-ref migration `sp1` (Part 16).

---

## Task 13: Part 12 — Shopify auto-store

Follow the **Standard Part Procedure** for `docs/report/12-shopify-autostore.md`.

**Files (in order):**
- `el/shopify.py`
- `el/nodes/generate_shopify_theme.py`
- `el/nodes/upload_shopify_theme.py`
- `el/nodes/upload_shopify_products.py`
- `el/assets/theme_shells/sections/hero-shell.liquid`
- `el/assets/theme_shells/sections/featured-collections-shell.liquid`
- `el/assets/theme_shells/sections/product-grid-shell.liquid`
- `el/assets/theme_shells/sections/promo-shell.liquid`
- `el/assets/theme_shells/sections/footer-shell.liquid`

**Part notes:** Read `docs/runbooks/shopify.md`. Document the theme-shell → rendered-section pipeline and the Admin API auth (token vs. client id/secret). For each `.liquid`, explain the placeholders the generator fills.

---

## Task 14: Part 13 — Outbound: email, notifications & CRM

Follow the **Standard Part Procedure** for `docs/report/13-outbound-email-crm.md`.

**Files (in order):**
- `el/email.py`
- `el/nodes/email_digest.py`
- `el/nodes/email_product_detail.py`
- `el/crm.py`
- `el/nodes/record_niche_performance.py`
- `el/nodes/notify_business.py`
- `el/nodes/error_formatter.py`
- `el/nodes/telegram_alert.py`

**Part notes:** Group SMTP email, CRM niche-metrics, and the dev/business alert path. `error_formatter` feeds `telegram_alert`; document the error payload shape (link to `el/error_handler.py` in Part 04). Cross-ref migration `sp6` (Part 16).

---

## Task 15: Part 14 — Web app: FastAPI HIL dashboard + chat

Follow the **Standard Part Procedure** for `docs/report/14-web-app.md`.

**Files (in order):**
- `el/web/__init__.py`
- `el/web/app.py`
- `el/web/settings.py`
- `el/web/deps.py`
- `el/web/auth.py`
- `el/web/rate_limit.py`
- `el/web/errors.py`
- `el/web/run_service.py`
- `el/web/chat_rag.py`
- `el/web/routes/__init__.py`
- `el/web/routes/pages.py`
- `el/web/routes/runs.py`
- `el/web/routes/chat.py`
- `el/web/routes/crm.py`
- `el/web/routes/health.py`
- `el/web/templates/base.html`
- `el/web/templates/index.html`
- `el/web/templates/run.html`
- `el/web/templates/chat.html`
- `el/web/templates/crm.html`
- `el/web/static/app.css`

**Part notes:** Open with the FastAPI app wiring (router includes, middleware, auth dependency). Document `run_service` ↔ `pipeline.run_for_request` (Part 03) and `chat_rag`'s retrieval over pgvector (Part 16 `sp3`). For each template, note which route renders it and the context vars used.

---

## Task 16: Part 15 — Operational scripts

Follow the **Standard Part Procedure** for `docs/report/15-operational-scripts.md`.

**Files (in order):**
- `scripts/verify_env.py`
- `scripts/verify_env_runtime.py`
- `scripts/bayesian_calibration.py`
- `scripts/test_bayesian_calibration.py`
- `scripts/calibration_eval.py`
- `scripts/shopify_smoke.py`
- `scripts/build_phase3_hil.py`
- `scripts/fix_sa_json.py`

**Part notes:** `build_phase3_hil.py` (924L) is large — break by function/CLI command. Note `bayesian_calibration`/`calibration_eval` tie to Part 06 and the paper (Part 18).

---

## Task 17: Part 16 — Database migrations & data assets

Follow the **Standard Part Procedure** for `docs/report/16-migrations-and-data.md`.

**Files (in order):**
- `migrations/sp1/001_hil_logging_events.sql`
- `migrations/sp3/001_pgvector_and_embeddings.sql`
- `migrations/sp4/001_run_requests.sql`
- `migrations/sp4/002_post_advisor_hardening.sql`
- `migrations/sp6/001_crm_tables.sql`
- `migrations/sp9_allow_forge_sentinel_hil_provider.sql`
- `migrations/combined_apply_all.sql`

**Part notes:** For SQL, "line-by-line" = per-statement: each table/column/index/policy with its purpose and the subsystem it serves (sp1→HIL, sp3→embeddings, sp4→run_requests/web, sp6→CRM, sp9→provider enum). After the migrations, add a non-heading subsection documenting the **shapes** of `data/category_posteriors.json`, `data/eval_results.json`, `data/sample_phase1_run.json`, and `data/bcc_posteriors_schema.sql` (these are data, not line-by-line targets).

---

## Task 18: Part 17 — Test suite (summaries)

**Files:** Create `docs/report/17-test-suite.md`.

- [ ] **Step 1: Enumerate** the test files: `python -c "import glob; [print(p) for p in sorted(glob.glob('tests/**/*.py', recursive=True))]"` (122 files). Read each (skim acceptable for repetitive ones; read enough to state what it verifies).
- [ ] **Step 2: Write** `17-test-suite.md`, grouped by subsystem (entrypoints, fenix, forge, sentinel, selection, persistence, hil, shopify, outbound, web, scripts, integration). For **every** file, one row/bullet: the file path (as plain text `tests/...py`), what it verifies, and notable fixtures/mocks. Add a subsystem→tests map. **Every** `tests/**/*.py` path string must literally appear in this file (the checker greps for it).
- [ ] **Step 3: Verify** `python scripts/check_report_coverage.py` → `Test files ... MISSING : 0`.
- [ ] **Step 4: Tick** Part 17 in `00-index.md`.
- [ ] **Step 5: Commit** `git add docs/report/17-test-suite.md docs/report/00-index.md && git commit -m "docs(report): Part 17 — test-suite summaries"`.

---

## Task 19: Part 18 — Legacy n8n workflows & research paper

Follow the **Standard Part Procedure** for `docs/report/18-legacy-and-paper.md`, with the legacy-specific handling below.

**Files (line-by-line):**
- `legacy/apply_bcc_phase_i.py`

**Structural / summary (NOT line-by-line headings):**
- `legacy/EL.json` (2,991 lines) — describe the workflow graph; build a **node→Python mapping table** (legacy node name → `el/nodes/*.py`), using `docs/PORT_LOG.md` as the cross-walk.
- `legacy/el_error_handler.json` — map to `el/error_handler.py` + `el/nodes/error_formatter.py`.
- `legacy/sync_workflows.js` — one-paragraph summary.
- `paper/main.tex` + `paper/references.bib` + `paper/figures/*` — summarize the Bayesian-calibration research: thesis, method, the posterior/calibration figures, how it maps to Part 06 / `scripts/bayesian_calibration.py`.

**Part notes:** Only `legacy/apply_bcc_phase_i.py` needs a `### \`legacy/apply_bcc_phase_i.py\`` heading (the checker tracks it). The JSON/paper get prose subsections. Verify (Step 3): the checker shows `legacy/apply_bcc_phase_i.py` covered.

---

## Task 20: Part 19 — Appendix: environment & build reference

Follow the **Standard Part Procedure** for `docs/report/19-appendix-environment-build.md` (these config files are documented, but only those matching production globs are checker-tracked — none here are, so this Part is prose/reference).

**Files to document (read all):**
- `.env.example` (key catalog: name → required? → which subsystem uses it)
- `requirements.txt`, `requirements-dev.txt`
- `Dockerfile`, `docker-compose.yml`, `docker-entrypoint.sh`, `.dockerignore`
- `Caddyfile`, `Makefile`, `pytest.ini`, `.mcp.json`

**Part notes:** Present `.env.example` as a reference table (the single most useful appendix for operators). For Docker/compose/Caddy, explain the service topology (link to Part 02). Commit at the end.

---

## Task 21: Final verification & sign-off

**Files:** `docs/report/00-index.md` (final matrix), no new content.

- [ ] **Step 1: Full coverage gate.** Run `python scripts/check_report_coverage.py`.
  Expected: `UNCOVERED : 0`, `MISSING : 0`, `RESULT: PASS - full coverage` (exit 0).
- [ ] **Step 2: Reconcile the tree.** Run the in-scope enumeration once more and confirm the checker's `Production files in scope : 146` and `Test files : 122` still match the repo (guards against files added mid-effort):
  `python scripts/check_report_coverage.py | findstr "in scope Test files"`
- [ ] **Step 3: Diagram check.** Grep every report file for ` ```mermaid ` blocks and eyeball each for syntax (balanced, valid node ids). Run: `python -c "import glob,re; [print(p) for p in glob.glob('docs/report/*.md') if '```mermaid' in open(p,encoding='utf-8').read()]"`.
- [ ] **Step 4: Acceptance criteria.** Re-read spec §11; confirm each of the 6 criteria holds (all 20 files present; every prod file ☑; node sections list ctx reads/writes; 122 tests summarized; legacy mapping table present; Mermaid renders).
- [ ] **Step 5: Finalize index + commit.** Ensure every matrix row is ☑. `git add docs/report/00-index.md && git commit -m "docs(report): final coverage gate green (146 prod files, 122 tests)"`.

---

## Self-Review (performed against the spec)

**1. Spec coverage.** Spec §6 Parts 00–19 → plan Tasks 1–20; spec §9 completeness guarantee → checker (Task 1) + per-task Step 3 + Task 21; spec §3 file set → File structure section; spec §7 template → Standard Part Procedure; spec §8 conventions (ctx contract, Mermaid, sparse Observations) → embedded in the procedure and Part notes (02 exec diagram, 11 state machine); acceptance criteria §11 → Task 21. Tests (§3/Part 17) → Task 18 with its own checker dimension. Legacy + paper (§Appendix C) → Task 19. No spec requirement left without a task.

**2. Placeholder scan.** No "TBD/TODO/handle edge cases" left as instructions. The only intentionally deferred item — exact node→Part placement — is backstopped by the checker, which *names* any uncovered file for immediate assignment. The checker code is complete and runnable.

**3. Type/name consistency.** The heading convention `### \`<path>\`` is defined once and is exactly what `heading_paths()` parses (backtick-delimited tokens on `###` lines). The checker's `PROD_PATTERNS` matches the spec's §3 scope and the verified counts (146 prod / 122 tests). Part filenames in the File structure, the `00-index.md` matrix rows, and each task's target file all use identical names.

All checks pass.
