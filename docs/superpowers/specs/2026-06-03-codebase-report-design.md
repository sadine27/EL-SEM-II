# Design Spec — EL Codebase Line-by-Line Technical Report

- **Date:** 2026-06-03
- **Status:** Approved (brainstorm complete) — ready for implementation plan
- **Topic:** A complete, developer-facing, line-by-line walkthrough of the entire
  EL Python Port codebase, delivered as a multi-file Markdown report.
- **Author:** brainstormed with the maintainer (sadine27)

---

## 1. Goal & motivation

Produce an exhaustive technical reference for the EL Python Port — the Python
port of the legacy n8n dropshipping/e-commerce automation workflows. The report
must let a developer understand, run, and extend **every part** of the system,
leaving no production file undocumented ("not a single line of code left out").

This is a **documentation deliverable**, not a feature. The "implementation"
phase is the act of reading every file and writing the walkthrough.

## 2. Locked decisions (from brainstorm)

| # | Decision | Choice |
|---|----------|--------|
| 1 | **Audience** | Developer technical reference (code-first) |
| 2 | **Granularity** | Literal line-by-line walkthrough |
| 3 | **Scope of line-by-line** | All production code (`el/`, `scripts/`, `migrations/`, web templates/CSS, Liquid shells) gets line-by-line. Tests get per-file summaries. Legacy n8n JSON gets structural description. The LaTeX paper gets a summary. |
| 4 | **Format** | Multi-file Markdown under `docs/report/` + a master index. Optional single-PDF render at the end. |
| 5 | **Organization** | Hybrid (C): subsystem "Parts," flow-ordered within each, plus a file→section coverage matrix. |
| 6 | **Walkthrough density** | Chunk-and-annotate (code block per logical block, prose accounting for every line, individual call-outs for non-obvious lines). |
| 7 | **Review layer** | Documentation + light **Observations** call-outs (flag a genuine bug/risk/security concern/TODO/smell only where it actually exists; no forced findings). |

## 3. Deliverable: location & file set

All report files live in `docs/report/`. One Markdown file per Part:

```
docs/report/
  00-index.md                       Master TOC, reading guide, coverage matrix
  01-overview.md                    What EL is, port story, glossary, repo map
  02-architecture.md                ctx contract, execution order, gating, deploy
  03-entrypoints-and-orchestrator.md
  04-foundation-and-providers.md
  05-fenix-sources.md
  06-fenix-scoring-and-calibration.md
  07-forge-supplier-sourcing.md
  08-sentinel-vetting.md
  09-selection-curation-embeddings.md
  10-sheets-drive-persistence.md
  11-hil-telegram-review.md
  12-shopify-autostore.md
  13-outbound-email-crm.md
  14-web-app.md
  15-operational-scripts.md
  16-migrations-and-data.md
  17-test-suite.md
  18-legacy-and-paper.md
  19-appendix-environment-build.md
```

## 4. Organizing approach & rationale

**Approach C (hybrid).** Files are grouped into subsystem Parts that mirror the
project's own vocabulary (Fenix / Forge / Sentinel / HIL). Within each Part,
files are walked in dependency / data-flow order. The `00-index.md` coverage
matrix maps **every production file → its Part → ☐/☑**, which is how
completeness is proven.

Rejected alternatives: pure pipeline-flow order (hard to prove coverage,
providers referenced before definition); pure directory order (reads like a
filesystem dump, hides the runtime flow).

## 5. System model (the backbone every Part references)

The pipeline is a sequence of **nodes**, each a module exposing `run(ctx)` that
mutates a single shared `ctx: dict`. `el/pipeline.py::run()` wires them in the
order ported from `legacy/EL.json`. Every stage is **fail-soft** and
**credential-gated**: a missing env var or a provider exception skips that stage
(logged) instead of crashing the daily batch.

Named engines:

- **Fenix** — trend front-end: `el/sources/*` → `score_rank` (keyword) →
  `ai_score_trends` (Gemini via Vertex AI) → `ranked_payload`.
- **Forge** — supplier sourcing: `supplier_search` over `el/suppliers/*` plus the
  CJ Dropshipping path.
- **Sentinel** — vetting gate: `sentinel_vetting` applies margin/economics checks.
- **HIL** — human-in-the-loop approval over Telegram (photo cards, callbacks,
  pollers), persisted in Supabase.
- Downstream: Sheets/Drive persistence, Shopify auto-store, outbound email,
  CRM metrics, and a FastAPI web dashboard.

CLI (`python -m el`): `run` (full batch), `trends` (Fenix preview), `forge`
(supplier preview), `sentinel` (vetting preview).

## 6. Report structure — Parts and file assignments

> The assignment below is the **seed** for the coverage matrix. At implementation
> start it is regenerated from a fresh `find` of the tree and reconciled, so the
> matrix — not this list — is authoritative. Final node→Part placement is
> confirmed against actual imports while writing.

**00 — Index, reading guide & coverage matrix.** Linked TOC, how to read the
report, the glossary pointer, and the file→section coverage table.

**01 — Overview & glossary.** The n8n→Python port story (`README.md`,
`docs/PORT_LOG.md`), capabilities, the Fenix/Forge/Sentinel/HIL vocabulary, and a
top-level repo map.

**02 — Architecture & runtime model.** The `ctx` contract; full execution order
of `pipeline.run()` (Mermaid flow diagram); the fail-soft/gating philosophy;
config/env model (`el/config.py` + `.env.example`); deployment topology
(Dockerfile, docker-compose, Caddyfile, worker, `run-daily.ps1` cron).

**03 — Entry points & orchestrator** *(line-by-line)*:
`el/__main__.py` (163), `el/pipeline.py` (407), `el/worker.py` (90),
root `run.py`, `run-daily.ps1`. `el/nodes/__init__.py`.

**04 — Foundation & cross-cutting providers** *(line-by-line)*:
`el/__init__.py`, `el/config.py` (21), `el/logger.py` (18),
`el/error_handler.py` (76), `el/supabase.py` (229), `el/llm.py` (221),
`el/telegram.py` (204), `el/google_sheets.py` (102), `el/google_drive.py` (119),
`el/browserbase.py` (62).
*Assignment rule:* genuinely cross-cutting SDK wrappers live here; single-
subsystem providers live with their subsystem (`el/shopify.py`→12,
`el/email.py`+`el/crm.py`→13, `el/cj.py`+`el/tavily.py`→07,
`el/embeddings.py`→09, `el/hil_fx.py`→11).

**05 — Fenix I: trend sources** *(line-by-line)*:
all of `el/sources/*` — `youtube` (37), `rss_india_source` (82),
`google_news_india_source` (85), `ai_trend_discovery` (237),
`shopify_competitor` (102), plus retired-but-importable `pytrends_source` (144),
`reddit_source` (120), `newsapi_source` (88), `amazon_in_source` (108),
`sources/__init__.py` (30); and the `youtube_trending` (51) node.

**06 — Fenix II: scoring, ranking & Bayesian calibration** *(line-by-line)*:
`score_rank` (623), `ai_score_trends` (198), `prepare_gemini_prompt` (71),
`parse_agent_output` (97), `read_bcc_posteriors` (35),
`bcc_calibrate_selection` (85), `update_bcc_posterior` (112),
`stochastic_logger` (241).

**07 — Forge: supplier sourcing** *(line-by-line)*:
`el/suppliers/*` — `cj_source` (143), `marketplace_source` (355),
`suppliers/__init__.py` (30); providers `el/cj.py` (67), `el/tavily.py` (64);
nodes `supplier_search` (218), `cj_get_token` (39), `cj_product_list` (84),
`pick_top_3` (114), `normalize_cj_review` (115), `build_search_query` (74),
`build_tavily_query` (116), `tavily_search_in_market` (80),
`if_tavily_content_thin` (35).

**08 — Sentinel: vetting & believable economics** *(line-by-line)*:
`sentinel_vetting` (358), `normalize_sentinel_review` (125). Cross-references the
`docs/SENTINEL_ENGINE_PLAN.md` and the believable-economics spec.

**09 — Selection, curation & embeddings** *(line-by-line)*:
`phase4_candidate_selection` (878), `curate_picks` (137), `filter_top_30` (52),
`pick_indian_listings` (247), `merge_review_sources` (28),
`embed_candidate_products` (208), `el/embeddings.py` (176),
`gemini_extract_product` (129), `find_similar_products` (71).

**10 — Sheets, Drive & JSON persistence** *(line-by-line)*:
`create_day_tab` (31), `create_day_tab_scraped` (32),
`create_curated_picks_tab` (38), `prepare_sheet_rows` (47),
`prepare_sheet_rows_scraped` (86), `write_rows_to_sheet` (46),
`sheet_append_scraped` (52), `prepare_json_file` (44),
`bundle_json_scraped` (55), `drive_upload` (66), `drive_upload_scraped` (53),
`write_curated_picks` (51), `supabase_insert_scraped` (70), `strip_html` (46).

**11 — HIL: Telegram human-in-the-loop** *(line-by-line)*:
`supabase_insert_hil_reviews` (76), `prepare_telegram_card` (121),
`download_product_image` (108), `send_hil_telegram_photo` (73),
`mark_telegram_photo_sent` (84), `send_hil_telegram_text_fallback` (60),
`mark_telegram_text_fallback` (74), `parse_hil_callback` (83),
`answer_hil_callback` (69), `apply_hil_callback` (212),
`if_callback_finalized_review` (25), `edit_hil_message` (89),
`delete_hil_message` (56), `log_hil_message_edited` (92),
`log_hil_message_deleted` (92), `send_hil_fx` (41),
`normalize_browserbase_review` (328), `browserbase_fetch` (71),
`el/hil_fx.py` (159), `el/hil_poller.py` (90). Includes a Mermaid HIL state
machine.

**12 — Shopify auto-store** *(line-by-line)*:
`generate_shopify_theme` (122), `upload_shopify_theme` (355),
`upload_shopify_products` (141), `el/shopify.py` (246),
`el/assets/theme_shells/sections/*.liquid` (5 files, 379). Cross-ref
`docs/runbooks/shopify.md`.

**13 — Outbound: email, notifications & CRM** *(line-by-line)*:
`email_digest` (96), `email_product_detail` (76), `el/email.py` (226),
`notify_business` (53), `telegram_alert` (48), `error_formatter` (63),
`record_niche_performance` (71), `el/crm.py` (127).

**14 — Web app: FastAPI HIL dashboard + chat** *(line-by-line)*:
`el/web/app.py` (67), `auth.py` (36), `deps.py` (24), `errors.py` (46),
`rate_limit.py` (60), `settings.py` (61), `chat_rag.py` (102),
`run_service.py` (116), `web/__init__.py` (17), `routes/pages.py` (29),
`routes/runs.py` (48), `routes/chat.py` (50), `routes/crm.py` (41),
`routes/health.py` (69), `routes/__init__.py`; templates `base.html` (48),
`index.html` (50), `run.html` (18), `chat.html` (101), `crm.html` (98);
`static/app.css` (3). Cross-ref `el/web/run_service` ↔ `pipeline.run_for_request`.

**15 — Operational scripts** *(line-by-line)*:
`scripts/bayesian_calibration.py` (156), `calibration_eval.py` (317),
`test_bayesian_calibration.py` (147), `build_phase3_hil.py` (924),
`verify_env.py` (277), `verify_env_runtime.py` (58), `shopify_smoke.py` (119),
`fix_sa_json.py` (21).

**16 — Database migrations & data assets** *(line-by-line for SQL)*:
`migrations/sp1/001_hil_logging_events.sql` (43),
`migrations/sp3/001_pgvector_and_embeddings.sql` (118),
`migrations/sp4/001_run_requests.sql` (45),
`migrations/sp4/002_post_advisor_hardening.sql` (79),
`migrations/sp6/001_crm_tables.sql` (82),
`migrations/sp9_allow_forge_sentinel_hil_provider.sql` (13),
`migrations/combined_apply_all.sql` (248); plus `data/` assets
(`bcc_posteriors_schema.sql`, `category_posteriors.json`, `eval_results.json`,
`sample_phase1_run.json`) documented as schema/shape.

**17 — Test suite** *(per-file summaries)*: all 122 files
(106 `tests/`, 2 `tests/integration/`, 14 `tests/web/`). Grouped by subsystem,
each file: what it verifies, key fixtures/mocks, and a subsystem→tests coverage
map. Per decision #3, summarized — not transcribed line-by-line.

**18 — Legacy n8n workflows & research paper.** Structural description of
`legacy/EL.json` (2,991 lines) and `legacy/el_error_handler.json` with a
**node→Python mapping table** (legacy node → porting `el/nodes/*` file);
line-by-line of `legacy/apply_bcc_phase_i.py` (220) and summary of
`legacy/sync_workflows.js` (73); summary of the LaTeX paper in `paper/`
(`main.tex`, `references.bib`, the Bayesian-calibration figures/tables).

**19 — Appendix: environment & build reference.** `.env.example` key catalog,
`requirements.txt` / `requirements-dev.txt`, `Dockerfile`,
`docker-compose.yml`, `docker-entrypoint.sh`, `Caddyfile`, `Makefile`,
`pytest.ini`, `.dockerignore`, `.mcp.json`.

## 7. Per-file walkthrough template

Every production-file section follows the same skeleton:

1. **`### <path>`** — *N lines · one-line purpose*.
2. **Role** — where it sits in the flow, callers, dependencies, and — for
   `el/nodes/*` — the exact `ctx` keys **read** and **written**.
3. **Walkthrough** — the real code in logical chunks (function/block). Each chunk
   is a fenced code block followed by an annotation that accounts for **every
   line**: trivial lines grouped, non-obvious lines called out individually with
   the *why*, edge cases, and gotchas.
4. **Failure & gating** — fail-soft behavior, env gates, logging.
5. **Observations** *(optional)* — a short call-out only where a genuine bug,
   risk, security concern, TODO, or smell exists.
6. **See also** — cross-links to related sections.

Each Part opens with an intro: the subsystem, its files, how they interconnect,
and a diagram where it helps.

### Worked example of the chunk-and-annotate style

```python
def _forge_pipeline_enabled() -> bool:
    """Master switch for the in-pipeline Forge→Sentinel stage (default on)."""
    return (config.get("EL_FORGE_PIPELINE_ENABLED", "true") or "").strip().lower() in {
        "1", "true", "yes", "on",
    }
```

- `config.get(..., "true")` — reads the env flag, **defaulting to `"true"`** so
  the stage is opt-*out*.
- `(... or "")` — guards a `None` return (key present but empty) before
  `.strip()`, preventing `AttributeError`.
- `.strip().lower()` — normalizes whitespace/case (`" TRUE "` works).
- `in {"1","true","yes","on"}` — the truthy vocabulary; anything else disables
  the stage; `set` membership for O(1) lookup.

## 8. Conventions

- **`ctx` contract** is the spine: node sections always state keys read/written
  so the data flow is reconstructable across Parts.
- **Diagrams** (Mermaid): pipeline execution order (Part 02), `ctx` lifecycle
  (Part 02), HIL callback state machine (Part 11), deploy topology (Part 02).
- **Observations** are sparse and evidence-based; this is documentation, not an
  audit.
- **Cross-links** use relative paths to other report files and `path:line`
  references into the codebase.

## 9. Production process & completeness guarantee

- **Phased, resumable** — one Part per work-unit (~20 units). Each unit: read
  every file in the Part *in full*; write its section(s); tick the coverage
  matrix; commit.
- **Completeness** — `00-index.md` holds the file→Part→status matrix, seeded at
  start from a fresh `find` of all production files. A Part is "done" only when
  every file in it is ☑. Final step cross-checks the matrix against the tree.
- **Accuracy** — read before write; quote real code; describe behavior as
  written; never invent.
- **Optional PDF** — after the Markdown is complete, optionally render a single
  paginated PDF via pandoc (+ LaTeX engine) for a literal page count; Markdown
  remains source of truth.

## 10. Out of scope (deliberately not transcribed)

`.venv/`, `.claude/` (skills/tooling), the bundled `n8n-skills` resources,
`__pycache__/`, `.dist/`, `.pytest_cache/`, build artifacts (`main.aux`,
`main.log`, etc.), and any secret material (`.env`). These are tooling or
generated, not project source.

## 11. Acceptance criteria

1. `docs/report/` contains all 20 files listed in §3.
2. Every production file in the §6/Appendix inventory is ☑ in the coverage
   matrix and has a line-by-line section (SQL and web templates included).
3. Each node section documents its `ctx` reads/writes.
4. All 122 test files are summarized in Part 17.
5. Legacy JSON has a node→Python mapping table; the paper is summarized.
6. Mermaid diagrams for execution order and the HIL state machine render.
7. The report builds to a single PDF on request (toolchain permitting).

## Appendix A — Production-file inventory (coverage-matrix seed)

- `el/` Python: **13,311** lines across 119 files (21 top-level modules,
  70 `nodes/`, 10 `sources/`, 3 `suppliers/`, 15 `web/`).
- `scripts/` Python: **2,019** lines, 8 files.
- `migrations/` SQL: **628** lines, 7 files.
- `el/web` templates + CSS: **318** lines, 6 files.
- `el/assets` Liquid: **379** lines, 5 files.
- **Core line-by-line total: ~16,655 lines.**
- Plus legacy `apply_bcc_phase_i.py` (220) line-by-line in Part 18.

## Appendix B — Test layout (Part 17 input)

- `tests/` (root): 106 files
- `tests/integration/`: 2 files
- `tests/web/`: 14 files
- **Total: 122 files, ~14,149 lines** (summarized, not transcribed).

## Appendix C — Legacy & paper assets (Part 18 input)

- `legacy/EL.json` (2,991), `legacy/el_error_handler.json` (88) — structural
  description + node→Python mapping table.
- `legacy/apply_bcc_phase_i.py` (220) — line-by-line.
- `legacy/sync_workflows.js` (73) — summary.
- `paper/main.tex` + `references.bib` + figures — summary of the Bayesian-
  calibration research.
