# SP6 — CRM Minimal — Design Spec

**Date:** 2026-05-26
**Author:** Divyesh Sharma (with Claude)
**Status:** Approved — implementing now.
**Predecessors:** SP5 (outbound) merged at `6eac26c`. SP1 + SP4 shipped.

---

## 1. What SP6 is

SP6 closes the `LEFT TO MAP — CRM` sticky on `Saas-PNG.png`. It adds the minimal
infrastructure to track **supplier reliability**, **product disputes**, and
**per-niche pipeline performance** — all in Supabase, all readable from a new
`/crm` dashboard extending the SP4 FastAPI app.

No external CRM tool is introduced. Decision rationale:

| Option | Verdict |
|---|---|
| (a) Supabase tables + views + `/crm` dashboard | ✅ **chosen** |
| (b) External: Notion / Airtable / HubSpot free | ✗ — new credential, new sync job, wrong abstraction layer |
| (c) Hybrid | ✗ — premature; revisit if free-tier row limits bite |

Keeping everything in Postgres means zero new credentials, zero new vendors, and
the dashboard query is a straightforward PostgREST `select_rows` call.

---

## 2. Schema

### `private.suppliers`

Tracks CJ Dropshipping suppliers encountered during pipeline runs.

| Column | Type | Notes |
|---|---|---|
| `supplier_id` | serial PK | |
| `name` | text NOT NULL | human-readable supplier name |
| `cj_ref` | text UNIQUE | CJ internal code; NULL if unknown |
| `reliability_score` | numeric(3,2) default 0.50 | running average, range [0,1] |
| `last_dispute_at` | timestamptz | nullable; updated on dispute open |
| `created_at` | timestamptz default now() | |
| `updated_at` | timestamptz default now() | |

Populated manually (or via a future dispute-workflow); not auto-filled by the pipeline.

### `private.disputes`

Tracks per-product issues opened against a supplier.

| Column | Type | Notes |
|---|---|---|
| `dispute_id` | serial PK | |
| `product_key` | text | lower(product_url); matches `private.product_embeddings.product_key` |
| `supplier_ref` | text | CJ supplier code |
| `opened_at` | timestamptz default now() | |
| `status` | text default 'open' | open / resolved / closed |
| `resolution` | text | nullable notes |
| `created_at` | timestamptz default now() | |
| `updated_at` | timestamptz default now() | |

### `private.niche_performance`

One row per niche (lower-cased). Upserted by the pipeline after each run.

| Column | Type | Notes |
|---|---|---|
| `niche` | text PK | lower-cased niche label |
| `run_count` | integer default 0 | total pipeline runs for this niche |
| `approval_count` | integer default 0 | HIL approvals |
| `rejection_count` | integer default 0 | HIL rejections |
| `approval_rate` | numeric(5,4) default 0 | approval_count / run_count; computed on upsert |
| `avg_bcc_score` | numeric(10,6) | running mean of opportunity_score of shown slate |
| `avg_human_position` | numeric(10,6) | nullable; future use |
| `last_run_at` | timestamptz | |
| `created_at` | timestamptz default now() | |
| `updated_at` | timestamptz default now() | |

---

## 3. Pipeline hook

**Node:** `el/nodes/record_niche_performance.py`

Runs at the **end of every pipeline run**, after Shopify + email nodes. Guards:
- Skip if `ctx["niche"]` is absent (non-web runs with no niche set).
- Skip if Supabase env vars are absent.
- Fail-soft: exception → log + `ok: False` in result, never crash the pipeline.

Reads from ctx:
- `ctx["niche"]` — niche label
- `ctx["hil_callback_results"]` — list of callback result dicts with `approval_status`
- `ctx["hil_slate"]` — the shown slate; each row has `opportunity_score` for avg_bcc_score

Writes:
- `ctx["crm_niche_performance_result"]` — `{ok, skipped, run_count, approval_count, rejection_count}`

---

## 4. Web dashboard

**Route:** `GET /crm` — HTMX shell page (public, like other shell pages).

**API routes** (bearer-auth required):
- `GET /api/crm/niche-performance` — returns list of `niche_performance` rows, ordered by `run_count desc`
- `GET /api/crm/suppliers` — returns list of `suppliers` rows
- `GET /api/crm/disputes` — returns list of `disputes` rows, ordered by `opened_at desc`

The `/crm` HTMX page auto-loads all three sections on `DOMContentLoaded` via
`hx-trigger="load"` fragments. No pagination needed at MVP scale.

---

## 5. Credentials

No new credentials. All CRM reads/writes use the existing `SUPABASE_URL` +
`SUPABASE_SERVICE_ROLE_KEY` provider.

---

## 6. Tests

- `tests/test_crm.py` — CRM data layer: list_niche_performance, list_suppliers,
  list_disputes, record_niche_run (fetch-update roundtrip), fail-soft on DB error.
- `tests/test_nodes_record_niche_performance.py` — node: happy path, skip-on-no-niche,
  skip-on-no-supabase-env, fail-soft exception.
- `tests/web/test_crm_routes.py` — route tests: auth guard, happy path JSON, 200 on
  GET /crm page.

---

## 7. Definition of done

1. Migration file `migrations/sp6/001_crm_tables.sql` committed.
2. `el/crm.py` data layer committed and tested.
3. `el/nodes/record_niche_performance.py` committed, wired in `el/pipeline.py`.
4. `el/web/routes/crm.py` + `el/web/templates/crm.html` committed, router registered.
5. All SP6 tests pass; full suite ≥ 639 tests green; coverage maintained.
6. `.env.example` unchanged (no new creds).
7. `PHASE3_ROADMAP.md` updated: SP6 → ✅.
