# EL Pipeline → Python Port — Design Spec

**Date:** 2026-05-07
**Author:** divyesh + Claude (port collaborator)
**Source workflows:** `legacy/EL.json` (70 nodes, ~61 functional + sticky notes), `legacy/el_error_handler.json` (3 nodes)
**Goal:** Replace the n8n Cloud runtime with a self-hosted Python project that runs the same daily-batch dropshipping intelligence pipeline plus its error alerter and (eventually) its always-on Telegram HIL callback listener.

---

## Why port

n8n Cloud is fine for prototyping but the project is increasingly Python-flavoured (BCC calibration, Bayesian eval scripts, paper artifacts) and a unified Python codebase is easier to test, version, deploy, and reason about. The user is also more comfortable iterating on Python than tweaking n8n JSON.

## Scope

Three independent runtimes live inside the n8n workflows; we port them in this order:

1. **Error handler** (`el_error_handler.json`, 2 functional nodes) — top-level Telegram alerter on uncaught exception. **First**, because every other node we port runs underneath it.
2. **Daily batch** (`EL.json`, Phases 1–3 + BCC calibration, ~50 functional nodes) — the once-a-day pipeline: trend fetch → AI curation → CJ + Browserbase scrape → Sheets/Drive/Supabase storage → BCC posterior update.
3. **Phase 4 HIL Telegram delivery** (~6 nodes, part of `EL.json`) — sends candidate cards to the developer for approval. Runs at the end of the daily batch.
4. **Phase 6 Telegram callback listener** (~10 nodes, part of `EL.json`, always-on Telegram trigger) — reacts to button presses on HIL messages. Long-running process (separate entry point), ported last.

This spec covers structure for all four. Each runtime gets its own implementation plan when its turn comes.

## Architecture

```
el/                           Python package — the port
├── __init__.py
├── config.py                 .env loading via python-dotenv
├── logger.py                 structured per-node logger (stdlib logging)
├── error_handler.py          context manager: catches exc, posts to Telegram
├── pipeline.py               orchestrates daily-batch nodes in execution order
└── nodes/                    one module per n8n node
    ├── __init__.py
    └── <snake_case_node>.py  exposes: def run(ctx: dict) -> dict

run.py                        entrypoint — runs daily batch under error_handler
hil_listener.py               (later) entrypoint — runs Phase 6 Telegram listener
requirements.txt              pinned deps, grown incrementally per iteration
.venv/                        local venv (gitignored)
docs/PORT_LOG.md              running journal: one entry per iteration
docs/superpowers/specs/       this spec lives here
tests/test_<node>.py          one quick unit test per ported node
```

### Node-port convention

Each n8n functional node maps 1:1 to one file in `el/nodes/`. Each module exposes:

```python
def run(ctx: dict) -> dict:
    """One n8n node. Reads from ctx, returns updates merged into ctx."""
```

`ctx` is a plain dict that mirrors n8n's `$input.first().json`. The orchestrator (`pipeline.py`) calls each node in execution order, merges its returned dict into the running ctx, and continues. This makes each node independently testable: feed it a fixture dict, assert the output dict.

Sticky-note nodes are skipped — they're documentation in n8n, irrelevant in Python.

### Credentials

All n8n credential references map to env vars in the existing `.env` (already populated). The error handler uses `EL_DEVELOPER_ALERT_TOKEN_KEY` and `EL_DEVELOPER_ALERT_CHAT_ID`. Future nodes pick up `YOUTUBE_API_KEY`, `GEMINI_API_KEY`, `CJ_DROPSHIPPING_API_KEY`, etc.

### Error handling

Two layers, mirroring the original:

1. **Per-node** — each node's `run()` may catch and re-raise with context, or return a soft-failure marker for nodes that n8n marked `continueOnFail: true` (storage nodes mostly). The orchestrator decides whether to halt or continue based on a per-node policy registered in `pipeline.py`.
2. **Workflow-level** — the `error_handler` context manager wraps `run_pipeline()` in `run.py`. Any uncaught exception is formatted (node name from the call frame, exc message truncated to 400 chars, IST timestamp) and POSTed to the developer Telegram chat before the process exits non-zero.

### Iteration cadence

1–2 nodes per session. Each iteration:
1. Pick next node(s) in execution order from `EL.json`.
2. Implement `el/nodes/<name>.py`.
3. Add `tests/test_<name>.py` with at least one happy-path case.
4. Wire into `pipeline.py` orchestration order.
5. Run pytest, fix anything broken.
6. Append entry to `docs/PORT_LOG.md` (date, nodes ported, decisions, gotchas, what's next).
7. Commit.

The PORT_LOG entry is the recovery anchor: a fresh session reads it and knows exactly where we are.

### Dependencies

Grown incrementally — added only when an iteration actually needs them. Initial set (iter 0+1):

- `python-dotenv` — config loading
- `requests` — Telegram API
- `pytest` — testing

Foreseeable future additions (NOT installed yet): `feedparser` (Trends/News RSS), `google-api-python-client` (YouTube + Sheets + Drive), `google-generativeai` or `langchain-google-genai` (Gemini agent), `psycopg[binary]` (Supabase Postgres), `python-telegram-bot` (HIL listener). Each is justified at the iteration that needs it.

## Out of scope

- Re-creating n8n's visual editor or any UI.
- Hosting / scheduling — out of band for now (cron, systemd timer, or GitHub Actions chosen later).
- Migrating n8n execution history — irrelevant; we start fresh.
- The Phase 6 HIL listener's deployment story — we'll port the code now and decide on a hosting model when that iteration arrives.

## Success criteria

- `python run.py` produces the same outputs (Sheets rows, Drive JSON files, Supabase rows) as the n8n daily batch on the same input window.
- An induced exception in any node fires the Telegram alert.
- Each ported node has at least one passing pytest test.
- A new contributor can run `python -m venv .venv && pip install -r requirements.txt && python run.py` and have it work, given a populated `.env`.
