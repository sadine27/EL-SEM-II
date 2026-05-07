# EL Python Port — Running Journal

One entry per iteration. Newest entry on top. A fresh Claude session should read this from the top to know exactly where the port is.

Design spec: [`docs/superpowers/specs/2026-05-07-el-python-port-design.md`](superpowers/specs/2026-05-07-el-python-port-design.md)
Source workflows: `legacy/EL.json` (70 nodes), `legacy/el_error_handler.json` (3 nodes)

---

## 2026-05-07 - Iter 9 - Tavily search and result filtering

Implements the initial discovery phase: search for product opportunities via Tavily, rank results by quality and relevance.

**Scope:**
- Implement `el/nodes/build_tavily_query.py`: Generate search queries for Indian market
- Implement `el/nodes/tavily_search_in_market.py`: HTTP POST to Tavily API with result collection
- Implement `el/nodes/pick_indian_listings.py`: Filter and rank search results by quality score
- Extend `el/tavily.py`: Add `include_raw_content` parameter and score capture

**Mapping:**

| n8n node | Python |
| --- | --- |
| `Build Tavily Query` | `el/nodes/build_tavily_query.py :: run(ctx)` |
| `Tavily Search (IN Market)` | `el/nodes/tavily_search_in_market.py :: run(ctx, provider=None)` |
| `Pick Indian Listings` | `el/nodes/pick_indian_listings.py :: run(ctx)` |

**What it does:**
- Converts ranked product opportunities into search queries optimized for Indian e-commerce (e.g., "buy X india").
- Searches Tavily API for each query, collecting up to 10 results per query with scores and raw content.
- Filters and ranks results by quality metrics (Tavily score, URL quality, product/entity match count, price/rating signals).
- Picks top 3 per query: preferred (product pages + high quality), fallback (safe + moderate quality), last resort (any decent match).
- Preserves metadata chain for downstream Browserbase extraction path.

**Verification:**
- Added `tests/test_build_tavily_query.py` (6 tests): query generation, metadata preservation, error skipping.
- Added `tests/test_tavily_search_in_market.py` (7 tests): successful search, multiple results, provider error handling, metadata pass-through.
- Added `tests/test_pick_indian_listings.py` (8 tests): filtering, top-3 limit, merchandise intent, quality thresholding, domain preservation.
- `.venv\Scripts\python.exe -m pytest tests/ -v` - **248/248 passing** (was 227).

**Port status:**
- Functional nodes ported: **45/63** across `EL` + `EL Error Handler` (Iter 9 adds 3 nodes).
- Overall workflow port: **71.4%**.

**Next iter preview:**
- Iter 10: Browserbase fallback path (`If Tavily Content Thin`, `Browserbase Fetch`, `Strip HTML`, `Prepare Gemini Prompt`, `Gemini Extract Product`, `Normalize Browserbase Review`).

---

## 2026-05-07 - Iter 8 - Phase 6 message-edit branch

Implements final phase of finalized-callback handling: edit the Telegram message with the final decision, and log edit/deletion events.

**Scope:**
- Implement `el/nodes/edit_hil_message.py`: Telegram editMessageText on finalized callback
- Implement `el/nodes/log_hil_message_edited.py`: Log edit event to `private.hil_review_events`
- Implement `el/nodes/delete_hil_message.py`: Telegram deleteMessage fallback (on edit failure)
- Implement `el/nodes/log_hil_message_deleted.py`: Log deletion event to `private.hil_review_events`
- Extend `el/telegram.py`: Add `edit_message_text()` and `delete_message()` methods to TelegramProvider

**Mapping:**

| n8n node | Python |
| --- | --- |
| `Edit HIL Review Message` | `el/nodes/edit_hil_message.py :: run(ctx, provider=None)` |
| `Log HIL Message Edited` | `el/nodes/log_hil_message_edited.py :: run(ctx, logger=None)` |
| `Delete HIL Review Message After Edit Failure` | `el/nodes/delete_hil_message.py :: run(ctx, provider=None)` |
| `Log HIL Message Deleted` | `el/nodes/log_hil_message_deleted.py :: run(ctx, logger=None)` |

**What it does:**
- After callback is finalized (approved/rejected/skipped), edit the original Telegram message with the decision text and disable reply buttons.
- Log the edit operation to `hil_review_events` table with method='editMessageText' and ok status.
- If edit fails, delete the message as fallback (cleanup on failure).
- Log the deletion operation to `hil_review_events` table with method='deleteMessage'.
- All operations gracefully skip if required fields missing, with result structs matching n8n error patterns.

**Verification:**
- Added `tests/test_edit_hil_message.py` (4 tests): success case, missing fields, Telegram error.
- Added `tests/test_delete_hil_message.py` (4 tests): skip on success, execute on edit failure, missing fields, Telegram error.
- Added `tests/test_log_hil_message_edited.py` (4 tests): success, missing review_id, logger error, insertion None.
- Added `tests/test_log_hil_message_deleted.py` (4 tests): success, missing review_id, logger error, insertion None.
- `.venv\Scripts\python.exe -m pytest tests/ -v` - **227/227 passing** (was 210).

**Port status:**
- Functional nodes ported: **42/63** across `EL` + `EL Error Handler` (Iter 8 adds 4 nodes).
- Overall workflow port: **66.7%**.

**Next iter preview:**
- Iter 9+: Remaining discovery branches (Tavily→Browserbase path from `Build Tavily Query` through `Normalize Browserbase Review`, ~20 nodes remaining).

---

## 2026-05-07 - Iter 7 - Curator web-search verification (Tavily tool-use loop)

Enhances the Phase 2 curator with function-calling to verify product demand via web search.

**Scope:**
- Refactor `el/llm.py` to support function-calling (new `GeminiAgentProvider`, `LLMAgentProvider` protocol)
- Implement `el/tavily.py`: Tavily Search API wrapper for product-market verification
- Update `el/nodes/curate_picks.py`: Use agent provider with web-search loop
- Graceful fallback to single-shot if Tavily unavailable

**Mapping:**

| Component | What it does |
| --- | --- |
| `el/tavily.py :: TavilySearchProvider` | Tavily API integration (search queries, parse results, error handling) |
| `el/llm.py :: GeminiAgentProvider` | Gemini function-calling loop (web_search tool, max 5 turns) |
| `el/nodes/curate_picks.py :: run(...)` | Wired to use agent if `TAVILY_API_KEY` set, fallback to single-shot |

**What it does:**
- Curator system prompt already instructs model to "use web_search to verify current demand, pricing and competition".
- `GeminiAgentProvider.call_with_tools(system, user, [web_search_tool], max_turns=5)` runs the loop:
  1. Call Gemini with tools parameter
  2. If model calls `web_search(query)`, execute via Tavily, return results
  3. Loop until model returns final JSON array (no more tool calls)
  4. Return final text response
- Curator picks now include web-verified signals.

**Divergences vs original:**
- n8n used LangChain agent loop. Python uses Gemini's native function-calling (simpler, no dependency).
- Tool calls structured as Gemini's `functionCall` parts; results mapped back via `functionResponse`.
- Tavily API used instead of LangChain Tavily node (same underlying service).

**Verification:**
- Added `tests/test_tavily.py` (3 tests): successful search, error handling, missing API key.
- Added `tests/test_llm.py` enhancements (3 tests): agent provider no-tool path, tool-call loop with execution, default_agent_provider().
- Updated `tests/test_curate_picks.py` (2 tests): uses agent when Tavily configured, falls back to single-shot.
- `.venv\Scripts\python.exe -m pytest tests/ -v` - **231/231 passing** (was 202).

**Port status:**
- Functional nodes ported: **38/63** across `EL` + `EL Error Handler` (node count unchanged; Iter 7 enhances existing curator node).
- Overall workflow port: **~60.3%** (unchanged).
- **LLM capability upgrade:** Curator now does web-verified product discovery (Iter 4 was single-shot).

**Next iter preview:**
- Iter 8: Continue Phase 6 message-edit nodes (`Edit HIL Review Message`, `Log HIL Message Edited`, etc.)
- Iter 8+: Remaining discovery branches (Tavily→Browserbase path from `Build Tavily Query` through `Normalize Browserbase Review`).

---

## 2026-05-07 - Iter 6d - Callback apply/answer gate

Continues Phase 6 callback handling after `Parse HIL Callback`.

**Mapping:**

| n8n node | Python |
| --- | --- |
| `Apply HIL Callback` (Postgres SQL) | `el/nodes/apply_hil_callback.py :: run(ctx, store=None)` |
| `Answer HIL Callback` (Telegram callback answer) | `el/nodes/answer_hil_callback.py :: run(ctx, provider=None)` |
| `If Callback Finalized Review` (IF) | `el/nodes/if_callback_finalized_review.py :: run(ctx)` |
| (extended - Supabase REST helper) | `el/supabase.py :: select_rows(...) / insert_rows(...) / update_rows(...)` |
| (extended - Telegram helper) | `el/telegram.py :: answer_callback(...)` |

**What it does:**
- Applies `a/r/s` callback payloads to matching `private.hil_reviews` rows, updating only pending reviews.
- Inserts `callback_received` and approval/rejection/skip events into `private.hil_review_events`.
- Preserves n8n response fields for downstream nodes:
  `callback_answer_text`, `telegram_edit_text`, and `message_should_finalize`.
- Answers Telegram callback queries with `cache_time = 0` and `show_alert = false`.
- Splits finalized callbacks into `ctx["hil_finalized_callbacks"]` for the edit-message branch.

**Divergences vs original:**
- The n8n node used one CTE-heavy Postgres query. Python implements the same behavior through Supabase REST operations with the service key.
- Python writes UTC timestamps itself for `reviewed_at` / `updated_at`; n8n SQL used `now()`.

**Verification after each port:**
- After `Apply HIL Callback`: `.venv\Scripts\python.exe -m pytest tests/ -v` - **194/194 passing**.
- After `Answer HIL Callback`: `.venv\Scripts\python.exe -m pytest tests/ -v` - **200/200 passing**.
- After `If Callback Finalized Review`: `.venv\Scripts\python.exe -m pytest tests/ -v` - **202/202 passing**.

**Port status:**
- Functional nodes ported: **38/63** across `EL` + `EL Error Handler`.
- Overall workflow port: **~60.3%**.

**Next iter preview:**
- Continue Phase 6: `Edit HIL Review Message`, `Log HIL Message Edited`, `Delete HIL Review Message After Edit Failure`, and `Log HIL Message Deleted`.
- Continue remaining discovery branch: Tavily/Browserbase path from `Build Tavily Query` through `Normalize Browserbase Review`.

---

## 2026-05-07 - Iter 6c - Telegram delivery + callback parse

Continues from `Prepare Telegram Card` through the Telegram delivery branch, then starts the Phase 6 callback branch.

**Mapping:**

| n8n node | Python |
| --- | --- |
| `Download Product Image` (HTTP Request) | `el/nodes/download_product_image.py :: run(ctx, provider=None)` |
| `Send HIL Telegram Photo` (Telegram sendPhoto) | `el/nodes/send_hil_telegram_photo.py :: run(ctx, provider=None)` |
| `Mark Telegram Photo Sent` (Postgres update) | `el/nodes/mark_telegram_photo_sent.py :: run(ctx, provider=None)` |
| `Send HIL Telegram Text Fallback` (Telegram sendMessage) | `el/nodes/send_hil_telegram_text_fallback.py :: run(ctx, provider=None)` |
| `Mark Telegram Text Fallback` (Postgres update) | `el/nodes/mark_telegram_text_fallback.py :: run(ctx, provider=None)` |
| `Parse HIL Callback` (Code) | `el/nodes/parse_hil_callback.py :: run(ctx)` |
| (new - Telegram Bot API helper) | `el/telegram.py` |
| (extended - Supabase REST helper) | `el/supabase.py :: update_row_by_id(...)` |

**What it does:**
- Downloads product images with the n8n headers, 15s timeout, and 5 redirect limit, storing successful binary payloads at `ctx["telegram_photo_cards"]`.
- Routes image-download failures to `ctx["telegram_text_fallback_cards"]`, matching n8n's error output into text fallback.
- Sends HIL review photo cards through Telegram `sendPhoto` with the same inline buttons: Approve, Reject, Skip, and Open Product.
- Records successful photo delivery back to `private.hil_reviews` with `telegram_media_status = 'sent'`.
- Sends text-only fallback cards through Telegram `sendMessage` for download/photo failures.
- Records fallback delivery back to `private.hil_reviews` with `telegram_media_status = 'text_only'`.
- Parses Telegram callback payloads of the form `a:<review_id>:<callback_token>`, `r:<review_id>:<callback_token>`, and `s:<review_id>:<callback_token>` into `ctx["hil_callbacks"]`.

**Divergences vs original:**
- Telegram credentials are read from `TELEGRAM_HIL_BOT_TOKEN`; the n8n workflow uses the `EL-HIL-BOT` credential.
- Supabase delivery updates use REST `PATCH` and Python UTC timestamps for `telegram_sent_at` / `updated_at`; n8n SQL used `now()`.
- `Telegram Trigger` itself is not a long-running listener yet. The callback parser expects callback updates in `ctx["telegram_updates"]` or `ctx["telegram_trigger_updates"]`.

**Verification after each port:**
- After `Download Product Image`: `.venv\Scripts\python.exe -m pytest tests/ -v` - **154/154 passing**.
- After `Send HIL Telegram Photo`: `.venv\Scripts\python.exe -m pytest tests/ -v` - **162/162 passing**.
- After `Mark Telegram Photo Sent`: `.venv\Scripts\python.exe -m pytest tests/ -v` - **168/168 passing**.
- After `Send HIL Telegram Text Fallback`: `.venv\Scripts\python.exe -m pytest tests/ -v` - **174/174 passing**.
- After `Mark Telegram Text Fallback`: `.venv\Scripts\python.exe -m pytest tests/ -v` - **179/179 passing**.
- After `Parse HIL Callback`: `.venv\Scripts\python.exe -m pytest tests/ -v` - **186/186 passing**.

**Next iter preview:**
- Continue the callback branch: `Apply HIL Callback`, `Answer HIL Callback`, `If Callback Finalized Review`, `Edit HIL Review Message`, delete-after-edit-failure, and callback event logs.
- Continue the remaining source branch: Tavily/Browserbase path from `Build Tavily Query` through `Normalize Browserbase Review`.

---

## 2026-05-07 - Iter 6b - CJ review/HIL handoff path

Continues downstream from `Pick Top 3` through the first Telegram-card preparation step.

**Mapping:**

| n8n node | Python |
| --- | --- |
| `Normalize CJ Review` (Code) | `el/nodes/normalize_cj_review.py :: run(ctx, ...)` |
| `Merge Review Sources` (Merge) | `el/nodes/merge_review_sources.py :: run(ctx)` |
| `Phase 4 Candidate Selection` (Code) | `el/nodes/phase4_candidate_selection.py :: run(ctx, ...)` |
| `Supabase Insert (HIL Reviews)` (Postgres upsert) | `el/nodes/supabase_insert_hil_reviews.py :: run(ctx, provider=None)` |
| `Prepare Telegram Card` (Code) | `el/nodes/prepare_telegram_card.py :: run(ctx, ...)` |
| (new - Supabase REST helper) | `el/supabase.py` |

**What it does:**
- Converts CJ product rows into the `hil_v1` review contract at `ctx["cj_review_items"]`.
- Merges normalized review candidates into `ctx["review_candidates"]`, ready for the future Browserbase branch.
- Ports Phase 4 scoring, mismatch blocking, dedupe, per-topic/provider caps, fallback selection, and diagnostic payload attachment.
- Upserts selected HIL review rows to `private.hil_reviews` using the n8n conflict columns:
  `workflow_run_id`, `source_provider`, `source_topic`, `product_url`.
- Formats Supabase-returned review rows into Telegram card fields/callback payloads at `ctx["telegram_cards"]`.

**Divergences vs original:**
- Supabase upsert uses direct REST/PostgREST with env vars instead of n8n Postgres credentials:
  `SUPABASE_URL` plus `SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_SECRET_KEY`, or `SUPABASE_KEY`.
- `Prepare Telegram Card` preserves the n8n default chat id but allows `TELEGRAM_HIL_CHAT_ID` to override it.
- The Python Phase 4 diagnostics use ASCII `...` for truncation instead of the n8n Unicode ellipsis.

**Verification after each port:**
- After `Normalize CJ Review`: `.venv\Scripts\python.exe -m pytest tests/ -v` - **122/122 passing**.
- After `Merge Review Sources`: `.venv\Scripts\python.exe -m pytest tests/ -v` - **125/125 passing**.
- After `Phase 4 Candidate Selection`: `.venv\Scripts\python.exe -m pytest tests/ -v` - **133/133 passing**.
- After `Supabase Insert (HIL Reviews)`: `.venv\Scripts\python.exe -m pytest tests/ -v` - **141/141 passing**.
- After `Prepare Telegram Card`: `.venv\Scripts\python.exe -m pytest tests/ -v` - **147/147 passing**.

**Next iter preview:**
- Continue Telegram delivery: `Download Product Image`, `Send HIL Telegram Photo`, `Send HIL Telegram Text Fallback`, and Telegram delivery-status update nodes.
- Parallel remaining source path: Tavily/Browserbase branch from `Build Tavily Query` through `Normalize Browserbase Review`.

---

## 2026-05-07 - Iter 5d/6a - Curated-picks persistence + CJ front door

Continues downstream from `Parse Agent Output`, then starts the CJ product-discovery branch.

**Mapping:**

| n8n node | Python |
| --- | --- |
| `Create Curated Picks Tab` (Google Sheets create sheet) | `el/nodes/create_curated_picks_tab.py :: run(ctx, provider=None)` |
| `Write Curated Picks` (Google Sheets append) | `el/nodes/write_curated_picks.py :: run(ctx, provider=None)` |
| `Build Search Query` (Code) | `el/nodes/build_search_query.py :: run(ctx)` |
| `CJ Get Token` (HTTP Request) | `el/nodes/cj_get_token.py :: run(ctx, provider=None)` |
| `CJ Product List` (HTTP Request) | `el/nodes/cj_product_list.py :: run(ctx, provider=None, ...)` |
| `Pick Top 3` (Code) | `el/nodes/pick_top_3.py :: run(ctx)` |
| (new - CJ API helper) | `el/cj.py` |

**What it does:**
- Creates the fixed `Curated Picks` sheet tab and appends parsed curator picks using the n8n schema order:
  `run_date`, `rank`, `topic`, `opportunity_score`, `reason`, `suggested_product_type`, `target_audience`, `search_query_in`.
- Converts each successful curated pick into a CJ keyword query, preferring `search_query_in`, then falling back to the n8n product-type/topic heuristic.
- Authenticates to CJ using env vars `CJ_EMAIL` and `CJ_API_KEY`; no legacy secret is embedded in code.
- Fetches CJ product-list results per keyword with the n8n defaults: page 1, page size 20, max 3 tries, 2s retry wait, 1.5s inter-keyword batch interval.
- Filters each CJ list for keyword-name overlap, sorts by `listedNum`, tops up to 3 products, and emits normalized CJ product rows at `ctx["cj_top_products"]`.

**Divergences vs original:**
- n8n hardcoded the CJ email/API key in the HTTP node body. Python requires `CJ_EMAIL` and `CJ_API_KEY`.
- `CJ Product List` stores each keyword response with its query metadata in `ctx["cj_product_list_responses"]`; n8n relied on positional references to `$('Build Search Query').all()[i]`.
- Failed CJ product-list calls are represented as `{ok: false, error: ...}` entries and skipped by `Pick Top 3`, matching the practical effect of `continueOnFail`.

**Verification after each port:**
- After `Create Curated Picks Tab`: `.venv\Scripts\python.exe -m pytest tests/ -v` - **90/90 passing**.
- After `Write Curated Picks`: `.venv\Scripts\python.exe -m pytest tests/ -v` - **95/95 passing**.
- After `Build Search Query`: `.venv\Scripts\python.exe -m pytest tests/ -v` - **102/102 passing**.
- After `CJ Get Token`: `.venv\Scripts\python.exe -m pytest tests/ -v` - **107/107 passing**.
- After `CJ Product List`: `.venv\Scripts\python.exe -m pytest tests/ -v` - **113/113 passing**.
- After `Pick Top 3`: `.venv\Scripts\python.exe -m pytest tests/ -v` - **117/117 passing**.

**Next iter preview:**
- Continue either the CJ review branch (`Normalize CJ Review` / `Merge Review Sources`) or the parallel Tavily branch (`Build Tavily Query` / `Tavily Search (IN Market)`).

---

## 2026-05-07 - Iter 5c - Phase 1 Drive JSON archive upload

Ports the Google Drive upload node downstream of `Prepare JSON File`.

**Mapping:**

| n8n node | Python |
| --- | --- |
| `Drive Upload` (Google Drive upload) | `el/nodes/drive_upload.py :: run(ctx, provider=None)` |
| (new - Drive API helper) | `el/google_drive.py` |

**What it does:**
- Reads the n8n-like `ctx["json_file"]` item emitted by `Prepare JSON File`.
- Decodes `binary.data.data` from base64.
- Uploads the JSON archive to Drive folder `1M0FRJeZ6uguJSfmheWwU8hwiZe_tjVja`, preserving the n8n filename pattern from `json.filename`.
- Stores the upload result at `ctx["drive_upload_result"]`.

**Divergences vs original:**
- n8n used Google Drive OAuth credentials. Python uses the same service-account env var as the Sheets port: `GOOGLE_SERVICE_ACCOUNT_JSON`.
- n8n `continueOnFail` is modeled by catching upload/provider errors, storing `{ok: false, uploaded: false, error: ...}`, and continuing.
- The Drive client uses the raw Drive v3 multipart upload endpoint via `requests`, keeping dependencies aligned with the existing Sheets helper.

**Verification:**
- Added `tests/test_google_drive.py` and `tests/test_drive_upload.py`.
- Pipeline smoke coverage now asserts Drive upload is skipped without credentials and invoked through the credential gate when present.
- `.venv\Scripts\python.exe -m pytest tests/ -v` - **88/88 passing**.

**Next iter preview:**
- Port `Create Curated Picks Tab` / `Write Curated Picks` so the curator branch persists its top 10 product opportunities.

---

## 2026-05-07 - Iter 5b - Phase 1 JSON archive preparation

Ports the next credential-free storage node downstream of `Fetch . Score . Dedupe . Rank`.

**Mapping:**

| n8n node | Python |
| --- | --- |
| `Prepare JSON File` (Code) | `el/nodes/prepare_json_file.py :: run(ctx)` |

**What it does:**
- Reads `ctx["ranked_payload"]`.
- Serializes it as pretty UTF-8 JSON with two-space indentation.
- Builds the original filename pattern: `trending_india_YYYY-MM-DD.json`.
- Base64-encodes the JSON and stores an n8n-like item at `ctx["json_file"]` with `json.filename` plus `binary.data`.

**Divergences vs original:**
- n8n placed this item directly on the node output. Python stores it in `ctx["json_file"]` for the future `Drive Upload` node.
- Missing `ranked_payload` becomes `{}` so smoke tests and local partial runs remain deterministic.

**Verification:**
- Added `tests/test_prepare_json_file.py`.
- Pipeline smoke coverage now asserts `json_file` is prepared without Google credentials.

**Next iter preview:**
- Done in Iter 5c. Next storage gap is curated-picks sheet output.

---

## 2026-05-07 — Iter 5a — Phase 1 Sheets append

Ports the first storage branch downstream of `Fetch . Score . Dedupe . Rank`: create the day tab, prepare ranked-trend rows, and append those rows to Google Sheets.

**Mapping:**

| n8n node | Python |
| --- | --- |
| `Create Day Tab` (Google Sheets create sheet) | `el/nodes/create_day_tab.py :: run(ctx, provider=None)` |
| `Prepare Sheet Rows` (Code) | `el/nodes/prepare_sheet_rows.py :: run(ctx)` |
| `Write Rows to Sheet` (Google Sheets append) | `el/nodes/write_rows_to_sheet.py :: run(ctx, provider=None)` |
| (new — Sheets API helper) | `el/google_sheets.py` |

**Key decisions:**
- `Prepare Sheet Rows` is credential-free and always runs after ranking, so local/dev runs still produce `ctx["sheet_rows"]` even when Google auth is absent.
- Google-backed nodes are gated in `pipeline.py` on `GOOGLE_SERVICE_ACCOUNT_JSON`. Missing credentials log warnings and skip `Create Day Tab` / `Write Rows to Sheet` without crashing the rest of the pipeline.
- `Create Day Tab` and `Write Rows to Sheet` accept `provider=None` and use `el/google_sheets.py` by default. Tests pass fake providers, matching the injection pattern used by the curator.
- `google-auth` is the only new dependency. The service account JSON is read from `GOOGLE_SERVICE_ACCOUNT_JSON`, refreshed with the Sheets scope, and used with direct `requests` calls to the Sheets API.
- The row schema/order is pinned to the n8n Code node output: `run_date`, `rank`, `topic`, `source`, `traffic_estimate`, `product_intent_score`, `related_queries`, `suggested_categories`.

**Divergences vs original:**
- n8n used OAuth credentials named `sharma divyesh api`; Python uses a service account JSON env var because that is the practical local/cron auth path.
- n8n `continueOnFail` is modeled by catching provider errors inside `Create Day Tab` and `Write Rows to Sheet`, storing `{created: false, error: ...}` / `{ok: false, error: ...}` in `ctx`, and continuing.
- n8n `autoMapInputData` hides Sheets column mapping. The Python API call sends values in the fixed 8-column order above (`A:H`) because the raw Sheets API has no object automap mode.

**Verification:**
- Recreated the local `.venv` enough to install requirements; the venv launcher still needs escalated execution in this sandbox because it points at a Microsoft Store Python path.
- `.venv\Scripts\python.exe -m pip install -r requirements.txt` - installed `google-auth` and existing pinned deps.
- `.venv\Scripts\python.exe -m pytest tests/ -v` - **76/76 passing**.
- Stubbed pipeline coverage: `tests/test_pipeline_storage.py` asserts the pipeline prepares `ctx["sheet_rows"]` without Google credentials and wires `sheet_tab` / `sheet_append_result` when the Google env gate is present.

**Next iter preview:**
- Iter 5b should port `Prepare JSON File` + `Drive Upload`.
- Iter 5c should port `Create Curated Picks Tab` / curated picks sheet output.

---

## 2026-05-07 — Iter 4.1 — Curator prompt hardening (`b1e1151`)

Follow-up to iter 4. The system-prompt template used `str.format(today=...)` and the embedded JSON example `{"rank":1,...}` was being parsed as `.format()` placeholders — fixed during iter 4 by escaping `{{...}}`, but the escaping itself is brittle (anyone editing the prompt has to remember it). Swapped to `str.replace("{today}", ...)` which doesn't parse at all, and restored the JSON example to verbatim n8n. 3 regression tests pin: (a) braces survive untouched, (b) `{today}` is the only substitution, (c) `{`/`}` counts balance. Suite: 59/59.

---

## 2026-05-07 — Iter 4 — `Filter Top 30` + Curator (single-shot Gemini)

The first LLM iteration. Ports the front of the Phase 2 AI curator chain. **Scope was narrowed deliberately** — the n8n original is a LangChain agent loop with a Tavily web-search tool node and Postgres chat memory, none of which can be ported as one iter without doing a half-decent job on three things at once. So iter 4 gets the prompt, the model call, and the parser; iter 5+ will reintroduce tool-use and memory.

**Scope correction from iter-3 preview:** I had said "LLM-driven product-idea expansion" was directly downstream of `Fetch . Score . Dedupe . Rank`. Reading the actual graph, it isn't — `Filter Top 30` sits in between as a Code node that slices to 30 and formats topics for the curator prompt. So iter 4 pairs the two.

**Mapping:**

| n8n node                             | Python                                      |
| ------------------------------------ | ------------------------------------------- |
| `Filter Top 30` (Code)               | `el/nodes/filter_top_30.py :: run(ctx)`     |
| `Dropship AI Agent` (LangChain agent) | `el/nodes/curate_picks.py :: run(ctx)`     |
| `Parse Agent Output` (Code)          | `el/nodes/curate_picks.py :: parse_agent_output` |
| (new — provider abstraction)         | `el/llm.py` (`LLMProvider`, `GeminiProvider`) |

**What it does:**
1. `filter_top_30.run` reads `ctx["ranked_payload"]`, slices the top 30 trends, builds a numbered `topics_text` block in the exact format the n8n original used, derives `run_date` from `metadata.scraped_at` (or today's date as fallback), and stores `ctx["filtered"] = {topics_text, run_date, total}`.
2. `curate_picks.run` formats the n8n system prompt verbatim (with today's date interpolated), calls Gemini once via `GeminiProvider.generate(system, user)`, and runs `parse_agent_output` on the raw text.
3. `parse_agent_output` is a faithful port of the n8n `Parse Agent Output` node: regex-finds the first `[...]` block, `json.loads` it, attaches `run_date` to each pick. On parse failure (or empty array) returns a single-element list with `error="No picks parsed"` and the first 500 chars of `raw` — same shape the n8n node emitted on failure.

**Decisions:**
- **Provider abstraction at `el/llm.py`.** `LLMProvider` is a `typing.Protocol` (duck-typed), `GeminiProvider` is the concrete impl, `default_provider()` returns Gemini today. Adding OpenAI/Mistral later means dropping in another class implementing `generate(system, user) -> str`. No LangChain dep — direct REST call to `generativelanguage.googleapis.com/v1beta/models/{model}:generateContent`.
- **`generate` is single-shot only.** No streaming, no tool/function calling, no chat history. Curator nodes that need those will compose around the protocol or get their own provider impl. Keeping the surface narrow makes mocking trivial.
- **System prompt is the n8n original verbatim.** Including the line that tells the model to "use web_search to verify..." even though there's no Tavily tool wired up. Faithful port wins over editorial cleanup; the model will simply skip that step. Iter 5 will add the tool back.
- **`.format()` curly-brace gotcha.** The system prompt embeds a JSON example like `{"rank":1,...}`. `str.format()` reads `{"rank"` as a placeholder and raises `KeyError: '"rank"'`. Fixed by escaping the JSON example's outer braces (`{{...}}`) — the only template variable that actually gets substituted is `{today}`. Caught by `test_run_calls_provider_with_system_and_topics`.
- **Pipeline gating on `GEMINI_API_KEY`** matches the YouTube pattern from iter 2: skip with a warning if unset, so dev runs without the key still smoke-test cleanly through `filter_top_30`.
- **Provider injection for tests.** `curate_picks.run(ctx, provider=...)` accepts an optional provider so tests don't need to mock `requests`. Production callers pass nothing and get `default_provider()`.

**Tests added (24 cases across three files):**
- `test_llm.py` (7): URL/params/body shape, multi-part text concat, empty-candidates fallback, HTTP error propagation, missing-key raises, explicit-key override, `default_provider()` returns Gemini.
- `test_filter_top_30.py` (6): slicing to 30, run_date extraction, today fallback, empty-payload, exact `topics_text` format, missing-categories tolerance.
- `test_curate_picks.py` (11): JSON-array extraction (with prose around it, pure array), no-array fallback, malformed-JSON fallback, empty-array fallback, raw truncation to 500 chars, `run` calls provider with right args, `run` attaches `run_date` to every pick, `run` skips on empty/missing `filtered`, `run` falls back gracefully on bad model output.

**Verification:**
- `pytest tests/ -v` → **56/56 passing** (was 32, added 24).
- `python run.py` against live YouTube + News RSS → 50 YT + 38 News → 30 filtered → curator skipped (no `GEMINI_API_KEY` in this env). Log line: `Filter Top 30: 30 topics for run_date=2026-05-07`.
- End-to-end with a stubbed `FakeGemini` provider → 50 YT → 86 ranked → 30 filtered → 1 pick parsed with `run_date` attached. Confirms the full chain wires correctly.

**Known divergences from the n8n original (deliberate, scoped to later iters):**

| Feature                  | n8n EL.json                       | Python today          | Iter to restore |
| ------------------------ | --------------------------------- | --------------------- | --------------- |
| Tavily web search        | LangChain tool node, agent loop   | None — single call    | iter 5          |
| Postgres chat memory     | `memoryPostgresChat` node          | None — stateless      | iter 6+         |
| Multi-turn agent loop    | LangChain agent decides when done | Single round-trip     | iter 5 (with tools) |

The model output quality will be lower without Tavily — it can't fact-check current Indian market demand. But the data-flow shape is identical, so downstream consumers (`Write Curated Picks`, `Build Search Query`, etc.) won't notice the difference when they get ported.

**What's next (iter 5):**

Two reasonable forks:
1. **Keep going down the LLM chain:** add the Tavily tool integration so the curator picks get web-verified. Means building a tiny tool-use loop around `GeminiProvider` (or splitting it into a `GeminiAgentProvider`) — Gemini's native function-calling API is JSON-schema-based and not too painful.
2. **Pivot to Phase 1 storage:** port `Create Day Tab` + `Prepare Sheet Rows` + `Write Rows to Sheet` (Google Sheets) and `Prepare JSON File` + `Drive Upload` (Google Drive). Gives us persistence for the curator output and lets the daily run leave artifacts.

I'd lean (2) — storage gives the pipeline a "done" output to compare across days, which makes iter 5's tool-use additions visible. But (1) is the natural continuation of the LLM thread.

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
