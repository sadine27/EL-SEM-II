# Go-Live Runbook

The exact sequence to take EL from "build-complete" to a verified first
production run. Assumes the deploy-target has Python 3.12 and the repo checked
out. Every command is copy-paste; every step has a check so you know it worked
before moving on.

> Prerequisite already done: DB migrations applied + `private` schema exposed
> (see "Supabase" below if unsure).

---

## 0. One-time config fixes in `.env`

Before the first run, make these edits to your `.env` (root of the repo):

| Setting | Change to | Why |
| --- | --- | --- |
| `EL_SOURCES_ENABLED` | `""` (empty) | **Important.** `"youtube"` disables every Fenix source. Empty = all defaults (youtube, pytrends, reddit, newsapi, amazon_in_movers, rss_india, google_news_india). The keyless ones just work. |
| `SHOPIFY_ADMIN_API_TOKEN` | *(your token)* | Only if you want products auto-published to Shopify. Without it the Shopify stage will likely fail (fail-soft, won't stop the run). |

Kill switches (leave default unless you want to disable a stage):

- `EL_FORGE_PIPELINE_ENABLED="true"` — Forge+Sentinel feed the HIL queue.
- `EL_HIL_LOGGING_ENABLED="true"` — ε-greedy logging.
- `EL_EMBEDDINGS_ENABLED="true"` — pgvector embeddings (~$0.02/day).

Telegram approval FX (presentation polish — on by default):

- `EL_HIL_FX_ENABLED="true"` — punchy confirmation toast, a quick
  "recording → done" card animation, and a celebratory ding on Approve/Reject.
  Set `"false"` for the plain text-only behaviour.
- `EL_HIL_FX_ALERT="false"` — set `"true"` to confirm with a modal popup
  instead of the top toast (more visible on a projector; needs a tap to dismiss).
- `EL_HIL_FX_DING="true"` — send a big animated emoji after each decision
  (this is what makes Telegram play the notification "ding"). Set `"false"`
  to keep the chat uncluttered.
- `EL_HIL_FX_BUFFER_MS="400"` — how long the "⏳ recording…" frame lingers
  before the final card (milliseconds). `0` disables the buffer frame.

---

## 1. Install dependencies

```bash
cd /path/to/EL-SEM-II
python -m venv .venv && . .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

**Check:** no errors, and:

```bash
python -c "import urllib3, cffi; from google.auth.crypt import _cryptography_rsa; print('deps OK', urllib3.__version__)"
```

Expect `deps OK 1.26.x` (must be `<2` — that's the pytrends fix).

---

## 2. Preflight — verify every credential

```bash
python scripts/verify_env.py
```

This live-probes all 10 services and prints an `[OK]/[FAIL]/[WARN]` table.

**Check:** `0 failure(s)` at the bottom. Resolve every `[FAIL]` before continuing.
`[WARN]` lines are fine (Eprolo/NewsAPI optional, Shopify token optional).

Common fails and fixes:

| Fail | Fix |
| --- | --- |
| Vertex `403 / aiplatform` | SA needs `roles/aiplatform.user`; enable Vertex AI API on the project. |
| Google SA mint fails | Share the target Sheet + Drive folder with the SA `client_email`. |
| Supabase write blocked (RLS/42501) | You're using an anon/publishable key — use the `sb_secret_…`/service-role key. |
| Supabase read 404 on `private.*` later | Expose the `private` schema (Settings → API → Exposed schemas). |

---

## 3. Cheap dry runs (no writes, sanity-check the engine)

These hit only read APIs and print to your terminal — nothing is sent to
Telegram/Supabase/Shopify. Run them first to confirm the pipeline produces
sane data:

```bash
python -m el trends  --top 10               # Fenix: are trends discovered + ranked?
python -m el forge   --query "RCB jersey"   # Forge: do suppliers come back?
python -m el sentinel --query "RCB jersey"  # Sentinel: pass/reject + scores
```

**Check:**
- `trends` lists topics with intent scores, and `sources:` shows **more than just
  youtube** (confirms the Step-0 `EL_SOURCES_ENABLED=""` fix worked).
- `forge` returns at least one supplier match (needs CJ creds).
- `sentinel` shows a pass/reject breakdown with `score` and `margin`.

---

## 4. The first live run

This is the real thing — it writes to Supabase and **sends Telegram approval
cards to you**.

```bash
python -m el run
```

It runs to completion and exits `0`. On any unhandled error it sends a Telegram
dev-alert and exits non-zero (that's the error handler working).

**Check (logs):** look for, near the end:
`EL pipeline run end (ctx keys: [...])` and no `Forge/Sentinel sourcing failed`.

---

## 5. Verify the run landed

**A. Supabase — rows written today, by provider.** Run in the SQL Editor:

```sql
select source_provider, approval_status, count(*)
from private.hil_reviews
where run_date = current_date::text
group by 1, 2
order by 1, 2;
```

Expect rows for `cj_dropshipping` **and** `forge_sentinel` (the Sentinel
integration). If you only see `cj_dropshipping`, Sentinel produced no passing
picks this run — check the run logs for the `sentinel_vetting` summary line.

**B. Telemetry logging fired:**

```sql
select count(*) as logged_events
from private.hil_logging_events
where batch_run_at::date = current_date;
```

Expect ≥ 1.

**C. Telegram:** you should have received approval card(s) in the HIL chat with
Approve/Reject buttons. Tapping them drives the rest of the flow.

---

## 6. Tick the validation boxes

Each SP log has an unchecked `[ ] one end-to-end production batch…`. After a
clean run + the checks above, mark them done in:
`docs/SP1_LOG.md`, `SP2_LOG.md`, `SP3_LOG.md`, `SP4_LOG.md`.

---

## 7. Rollback / safety

Everything is reversible via `.env` — no redeploy needed:

| To disable | Set |
| --- | --- |
| Sentinel in the daily run | `EL_FORGE_PIPELINE_ENABLED="false"` |
| ε-greedy logging | `EL_HIL_LOGGING_ENABLED="false"` |
| Embeddings spend | `EL_EMBEDDINGS_ENABLED="false"` |
| Telegram approval FX (toast/animation/ding) | `EL_HIL_FX_ENABLED="false"` |
| Just the ding (keep the animation) | `EL_HIL_FX_DING="false"` |
| Shopify auto-store | clear `SHOPIFY_*` creds |

The whole pipeline is fail-soft at IO boundaries: a missing/broken optional
service skips its stage rather than crashing the run.

---

## Supabase migration (if not already applied)

1. SQL Editor → paste `migrations/combined_apply_all.sql` → Run (idempotent).
2. Settings → API/Data API → Exposed schemas → add `private` → Save.
3. Verify 7 tables in `private`:
   `select table_name from information_schema.tables where table_schema='private' order by 1;`
