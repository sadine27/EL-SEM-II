# EL Python Port — Running Journal

One entry per iteration. Newest entry on top. A fresh Claude session should read this from the top to know exactly where the port is.

Design spec: [`docs/superpowers/specs/2026-05-07-el-python-port-design.md`](superpowers/specs/2026-05-07-el-python-port-design.md)
Source workflows: `legacy/EL.json` (70 nodes), `legacy/el_error_handler.json` (3 nodes)

---

## 2026-05-07 — Iter 2 — `YouTube Trending IN`

**Correction to iter 1's plan:** I had predicted iter 2 would also include `Google Trends RSS` and `Google News RSS` fetchers. Those nodes do **not** exist in `EL.json`. The only Phase 1 fetcher is `YouTube Trending IN`, which feeds straight into `Fetch . Score . Dedupe . Rank`.

**Mapping:**

| n8n node                          | Python                                       |
| --------------------------------- | -------------------------------------------- |
| `YouTube Trending IN` (httpRequest) | `el/nodes/youtube_trending.py :: run(ctx)` |

**API call:** `GET https://www.googleapis.com/youtube/v3/videos?chart=mostPopular&regionCode=IN&maxResults=50&part=snippet&key=$YOUTUBE_API_KEY` — identical to the n8n node, including the `httpQueryAuth` credential mapped to a `key=` query param.

**Decisions:**
- Strict env policy inside the node (`config.require("YOUTUBE_API_KEY")`) — consistent with how n8n would have failed without the credential. Pipeline-level fallback (`pipeline.py` checks `config.get` and skips with a warning if unset) so dev runs without a key still smoke-test cleanly.
- Returns `ctx` with `ctx["youtube_items"]` = `response.json()["items"]`. Downstream `Fetch.Score.Dedupe.Rank` will read from this key.
- 30s timeout on the GET (the n8n node had no explicit timeout but a default would still apply server-side — explicit is better than implicit).
- `resp.raise_for_status()` lets the error handler catch & alert on 4xx/5xx with the correct node name in the Telegram message.

**Tests added (`tests/test_youtube_trending.py`, 6 cases):** correct URL/params/key/timeout, ctx storage, empty-items handling, HTTP error propagation, missing-key raises, ctx key preservation.

**Verification:**
- `pytest tests/ -v` → 12/12 passing.
- `python run.py` against the live YouTube API → 49 items fetched and stored in `ctx["youtube_items"]`.

**What's next (iter 3):**

The single chunky `Fetch . Score . Dedupe . Rank` Code node — likely a full iteration on its own. It consumes `ctx["youtube_items"]` and produces a ranked candidate list for Phase 2. Will probably introduce scoring constants (recency, view velocity, channel authority) — read the source carefully before porting since this is where business logic lives.

---

## 2026-05-07 — Iter 0 + Iter 1 — Skeleton + Error Handler

**Iter 0 — Project skeleton**

Created:
- `el/` package with `__init__.py`, `config.py` (.env loader), `logger.py` (stdlib), `pipeline.py` (stub orchestrator), `nodes/` (empty).
- `run.py` entrypoint at repo root.
- `tests/` directory with `__init__.py`.
- `requirements.txt` — `python-dotenv`, `requests`, `pytest`. Will grow per iteration.
- Local `.venv/` (gitignored — added `.venv/` to `.gitignore`).
- This file: `docs/PORT_LOG.md`.
- Spec: `docs/superpowers/specs/2026-05-07-el-python-port-design.md`.

**Iter 1 — Port `legacy/el_error_handler.json` (2 functional nodes → `el/error_handler.py`)**

Mapping:

| n8n node                  | Python                                                          |
| ------------------------- | --------------------------------------------------------------- |
| `EL Workflow Error` (errorTrigger) | `error_handler()` context manager catching `BaseException` |
| `Format Error Message` (Code) | `format_error_message(node_name, exc, ts) -> str`           |
| `Alert Developer` (Telegram) | `send_telegram_alert(text) -> bool`                          |

Decisions:
- The original n8n message includes a `View Execution` link to the n8n Cloud UI. There is no equivalent in a local Python run, so the link is replaced with a static `_Local Python run — see stderr for traceback_` note. The traceback is also printed to stderr by the handler.
- `node_name` is extracted from the deepest traceback frame's `__name__`, with `el.nodes.` stripped — so a crash in `el/nodes/youtube_trending.py` shows up as `youtube_trending` in the alert.
- The handler **re-raises** after alerting so the process exits non-zero, which is the right signal for cron / systemd / GitHub Actions schedulers.
- Telegram creds missing → log a warning and return False (no crash). Lets local dev runs work without a populated `.env`.
- IST timezone hardcoded as `UTC+5:30` (no DST in India), matching `Asia/Kolkata` from the n8n version.

Tests added (`tests/test_error_handler.py`, 6 cases): message format, 400-char truncation, missing-creds skip, expected POST payload, re-raise + alert on exc, no-alert on clean exit.

**What's next (iter 2):**

Start on `EL.json` proper. First node in execution order is `Every 24 Hours` (scheduleTrigger) — trivially "just run `python run.py` from cron", so skip implementing it and move on to the first real node: `YouTube Trending IN` (httpRequest to YouTube Data API v3 → top 50 IN videos). Will add `google-api-python-client` (or just `requests`, since the call is a single GET) to `requirements.txt`.

Suggested iter-2 pairing: `YouTube Trending IN` + the parallel `Google Trends RSS` and `Google News RSS` fetchers (they all feed into `Fetch . Score . Dedupe . Rank`). May be one node per session if any of them turns out tricky.
