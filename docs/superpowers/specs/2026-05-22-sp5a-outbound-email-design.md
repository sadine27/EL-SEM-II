# SP5a — Outbound Email (Gmail SMTP digest + per-product) and Telegram `notify_business`

**Date:** 2026-05-22
**Status:** Design — approved by user, awaiting written-spec review
**Scope:** SP5a only. SP5b (Shopify auto-store) is a separate spec.

## Goal

Close the loop after HIL approval: send the business owner an end-of-run email digest with a narrative summary + XLSX attachment of curated picks, send one per-product detail email per approved pick, and ping the operator on Telegram with the run summary and chat link.

## Non-goals (SP5a)

- Shopify store / theme / product upload — that is SP5b.
- HTML email templating engine — inline string-built MIME is fine for SP5a's volume (~25 msg/day).
- SMTP connection pooling — single connection per send is fine at this volume.
- Customer-facing email (these go to the business owner / operator only).

## Architecture

### Components

**`el/email.py`** (new):

- `SmtpProvider` (Protocol): `send(msg: EmailMessage) -> str` (returns message-id).
- `GmailSmtpProvider` (concrete): wraps `smtplib.SMTP_SSL("smtp.gmail.com", 465)`, app-password auth, one connection per `send`.
- `build_digest_message(to, subject, narrative, picks, xlsx_bytes) -> EmailMessage` — pure builder, MIME multipart (text + html + optional xlsx attachment).
- `build_product_detail_message(to, subject, pick) -> EmailMessage` — pure builder, HTML body with image/price/why-it-fits/source link.
- `_summarize_with_gemini(picks, niche) -> str` — ~80-word narrative via existing `el/llm.py`; on any exception returns deterministic fallback `f"Top {n} picks for {niche}, ${low}–${high}."`.

**`el/nodes/email_digest.py`** (new): `run(ctx, *, provider=None) -> ctx`
- Fetch XLSX via existing `el/google_drive.py` Drive client (export `ctx["sheet_id"]` as XLSX). On failure: digest sends without attachment, logs warning in result body, does NOT trip `formatted_error`.
- Build digest, send via provider, write `ctx["email_digest_result"]`.

**`el/nodes/email_product_detail.py`** (new): `run(ctx, *, provider=None) -> ctx`
- Iterate `ctx["curated_picks"]`; one email per pick; aggregate results in `ctx["email_product_detail_results"]`.
- Per-pick failures do not abort the loop. If any failed, set `formatted_error` once with a count.

**`el/nodes/notify_business.py`** (new): `run(ctx, *, provider=None) -> ctx`
- Reuses existing `TelegramBotProvider` from `el/telegram.py`.
- Sends short message: `f"Run {request_id} done — {n} picks for {niche}. Chat: {CHAT_BASE_URL}/{request_id}"`.
- Writes `ctx["notify_business_result"]`.

### Pipeline wiring

In `el/pipeline.py`, append at the tail after HIL settle:

```
... (existing nodes) ...
→ email_digest
→ email_product_detail
→ notify_business
→ telegram_alert  (fires if any ctx["formatted_error"] was set)
```

The existing `telegram_alert` trigger condition (`ctx.get("formatted_error")`) is unchanged — the three new nodes plug into it for free.

## Data flow

**Inputs at tail of pipeline:**
- `ctx["request_id"]`, `ctx["niche"]`, `ctx["budget_usd"]`, `ctx["dislikes"]`
- `ctx["curated_picks"]`: list of `{name, price, image_url, source_url, why_it_fits, reviewer_notes}` post-HIL.
- `ctx["sheet_id"]`: Google Sheet id from existing `build_sheet` node.
- `ctx["business_email"]`: from `run_requests` row (SP4). Falls back to `GMAIL_SMTP_USER` if null.

**New `ctx` keys written:**
- `ctx["email_digest_result"]` = `{"ok": bool, "message_id": str?, "to": str, "error": str?}`
- `ctx["email_product_detail_results"]` = `[{"ok": bool, "message_id": str?, "pick_name": str, "error": str?}, ...]`
- `ctx["notify_business_result"]` = `{"ok": bool, "error": str?}`
- `ctx["formatted_error"]` (may be set by any of the three — first one wins)

**No upstream keys mutated.**

## Error handling

| Failure | Behavior |
|---|---|
| Gemini summary call raises | caught in `_summarize_with_gemini`; deterministic fallback string used; digest still sends; no `formatted_error` |
| Drive XLSX export raises | digest sends without attachment; result body notes "xlsx_missing"; no `formatted_error` |
| SMTP auth fails on digest | digest result `ok=False`; `formatted_error="email_digest: <msg>"`; pipeline continues |
| One per-product email fails | recorded in results list; loop continues; if any failed, `formatted_error="email_product_detail: N/M sends failed"` set once |
| `notify_business` fails | `formatted_error="notify_business: <msg>"`; `telegram_alert` still attempts (different chat id path) |
| `telegram_alert` fails | logged but swallowed (existing behavior) |

## Testing

All tests use fakes — no live SMTP, Telegram, Gemini, or Drive calls.

- **`tests/test_email.py`** — pure builders. Assert multipart structure, xlsx attachment present/absent, HTML body has required fields.
- **`tests/test_nodes_email_digest.py`** — fake `SmtpProvider`, fake Drive client. Cover: happy path, SMTP failure, XLSX missing, Gemini fallback.
- **`tests/test_nodes_email_product_detail.py`** — fake provider. Cover: N sends for N picks, partial failure aggregation, `formatted_error` set only on any failure.
- **`tests/test_nodes_notify_business.py`** — fake `TelegramProvider`. Assert message contains `request_id`, niche, chat URL.

## Secrets & config

New `.env` keys (loaded via existing `el.config.config`):

```
GMAIL_SMTP_USER=ops@example.com
GMAIL_SMTP_APP_PASSWORD=xxxx xxxx xxxx xxxx   # Gmail app password, NOT account password
GMAIL_SMTP_FROM_NAME=EL Bot
BUSINESS_NOTIFY_TELEGRAM_CHAT_ID=8243518279   # may equal TELEGRAM_ALERT_CHAT_ID
CHAT_BASE_URL=https://el.local/chat
```

- `.env.example` updated with placeholder values; real `.env` is gitignored.
- All three new nodes read via `config.get(...)` so tests inject fakes without env vars.

## Files touched

**New:**
- `el/email.py`
- `el/nodes/email_digest.py`
- `el/nodes/email_product_detail.py`
- `el/nodes/notify_business.py`
- `tests/test_email.py`
- `tests/test_nodes_email_digest.py`
- `tests/test_nodes_email_product_detail.py`
- `tests/test_nodes_notify_business.py`

**Modified:**
- `el/pipeline.py` — append three nodes at tail.
- `.env.example` — add 5 new keys.
- `el/config.py` — register 5 new keys if registry pattern is used (otherwise no change).

## Out of scope (deferred to SP5b)

- `el/shopify.py`, `generate_shopify_theme`, `upload_shopify_theme`, `upload_shopify_products`
- Updating `notify_business` to include Shopify storefront URL (SP5b will modify the message template).
