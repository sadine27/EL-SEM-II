# EL Python Port — Running Journal

One entry per iteration. Newest entry on top. A fresh Claude session should read this from the top to know exactly where the port is.

Design spec: [`docs/superpowers/specs/2026-05-07-el-python-port-design.md`](superpowers/specs/2026-05-07-el-python-port-design.md)
Source workflows: `legacy/EL.json` (70 nodes), `legacy/el_error_handler.json` (3 nodes)

---

## 2026-05-07 — Iter 3 — `Fetch . Score . Dedupe . Rank`

The big intent-scoring Code node from `EL.json`. This is where the business logic of EL lives — every downstream Phase 2 node consumes its output.

**Mapping:**

| n8n node                          | Python                                       |
| --------------------------------- | -------------------------------------------- |
| `Fetch . Score . Dedupe . Rank` (Code) | `el/nodes/score_rank.py :: run(ctx)` |

**What it does:**
1. Reads `ctx["youtube_items"]` (set by iter 2's node) → `{topic, source, tags}` shape.
2. Fetches Google Trends Daily RSS (geo=IN) and Google News RSS (en-IN, top 100) — same endpoints as the n8n original.
3. Scores product-purchase intent using four keyword tiers (T1 buyer signals 0.30 ea, T2 research 0.15 ea, T3 ambient 0.10 ea, NEG -0.20 ea), clamped to `[0, 1]` and rounded to 3 decimals.
4. Maps each topic to one or more of 13 product categories via word-boundary regex (or `["uncategorized"]`).
5. Dedupes by word-overlap ratio (overlap / smaller-set > 0.70 → duplicate). On collision, keeps the entry with more `related_queries`. Stopwords stripped before comparison.
6. Sorts by score desc, assigns 1-indexed `rank`, emits payload with metadata at `ctx["ranked_payload"]`.

**Decisions:**
- **One module, helpers exported.** `score_intent`, `map_categories`, `normalize_words`, `dedupe`, `parse_youtube`, `parse_rss_titles` are all module-level functions so tests can hit them directly. Constants (`T1_BUYER`, `T2_RESEARCH`, `T3_AMBIENT`, `NEG`, `CAT`, `STOPWORDS`) are tuples/frozenset at module top — readable and immutable.
- **Faithful regex port of the RSS title extractor.** The n8n version used a single regex with optional CDATA wrappers and skipped the first match (channel title). Same behavior here — no `feedparser` dependency added.
- **Graceful RSS failure.** Wrapped in try/except → log warning, return `[]`. Matches the n8n original's swallowed errors. The pipeline continues with whatever sources succeeded.
- **Word-boundary category matching** uses `\b{re.escape(kw)}\b` so `cat` doesn't match inside `category` (test covers this).
- **Equivalent rounding semantics.** Python's `round(x, 3)` uses banker's rounding while JS uses round-half-up; for this pipeline (3-decimal scores, clamped to `[0, 1]`) the divergence is at the noise floor and not worth a manual half-up shim.
- **`raise_for_status()` on RSS fetches** so the try/except actually catches HTTP errors (a missing call would silently treat 4xx/5xx bodies as feed XML).

**Tests added (`tests/test_score_rank.py`, 20 cases):**
Scoring (T1/T2/T3 hit, clamp-to-one, NEG clamp-to-zero, related affects score, rounding); category mapping (known keyword, uncategorized fallback, word boundary, multi-category); `normalize_words` punctuation+stopwords; dedupe (distinct kept, high-overlap collapsed, replace-with-richer, empty-topic skipped); YouTube parser (whitespace, missing fields); RSS parser (channel-title skip, limit); `run` integration (mocked YT+Trends+News with sort+rank verification, RSS-failure resilience, no-YT-items path).

**Verification:**
- `pytest tests/ -v` → **32/32 passing** (was 12, added 20).
- `python run.py` against the live web → 50 YT + 38 News → 86 ranked topics in `ctx["ranked_payload"]`.
- **Caveat surfaced by the live run:** the Google Trends Daily RSS endpoint (`/trends/trendingsearches/daily/rss?geo=IN`) now returns 404. Google deprecated it; the same n8n node was hitting the same wall in production. The graceful-failure path absorbs it cleanly — pipeline still produces useful output from YouTube + News alone. A future iter can swap to the `realtime` endpoint or the SerpApi `google-trends` API.

**What's next (iter 4):**

Now into Phase 2 of `EL.json`. The next downstream consumer of `ranked_payload` is the LLM-driven product-idea expansion chain — a prompt + Mistral/OpenAI call + JSON-output parser → product candidate list. That's a single iter once the LLM credentials are sorted. Will likely need to add an `el/llm.py` provider abstraction so we can swap models without rewriting the node.

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
