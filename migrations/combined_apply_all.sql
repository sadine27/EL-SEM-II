-- =============================================================================
-- Combined migrations: SP1 → SP3 → SP4 → SP6 → SP9
-- Apply in one paste in the Supabase SQL Editor.
-- Every statement is idempotent — safe to re-run if partially applied.
--
-- Steps after running this script:
--   1. Go to Supabase Dashboard → Settings → API → Exposed schemas
--   2. Add "private" to the list (alongside "public")
--   3. Save — PostgREST will reload automatically
-- =============================================================================


-- ---------------------------------------------------------------------------
-- SP1 — Telemetry Foundation (migrations/sp1/001_hil_logging_events.sql)
-- ---------------------------------------------------------------------------

create extension if not exists "uuid-ossp";
create schema if not exists private;

create table if not exists private.hil_logging_events (
  id                bigserial primary key,
  event_id          uuid        not null,
  candidate_idx     int         not null,
  candidate_score   numeric     not null,
  candidate_rank    int         not null,
  candidate_payload jsonb       not null,
  in_greedy_slate   boolean     not null,
  was_shown         boolean     not null,
  branch            text        not null
                    check (branch in ('greedy','explore','degenerate')),
  propensity        numeric     not null
                    check (propensity > 0 and propensity <= 1),
  epsilon           numeric     not null
                    check (epsilon >= 0 and epsilon <= 1),
  pool_size         int         not null check (pool_size >= 0),
  slate_size        int         not null check (slate_size >= 0),
  review_id         bigint      references private.hil_reviews(id) on delete set null,
  batch_run_at      timestamptz not null default now(),
  created_at        timestamptz not null default now(),
  unique (event_id, candidate_idx)
);

create index if not exists hil_logging_events_event_id_idx
  on private.hil_logging_events(event_id);
create index if not exists hil_logging_events_review_id_idx
  on private.hil_logging_events(review_id) where review_id is not null;
create index if not exists hil_logging_events_batch_run_at_idx
  on private.hil_logging_events(batch_run_at desc);

alter table private.hil_reviews
  add column if not exists logging_event_id uuid;

create index if not exists hil_reviews_logging_event_id_idx
  on private.hil_reviews(logging_event_id);


-- ---------------------------------------------------------------------------
-- SP3 — Vision + pgvector (migrations/sp3/001_pgvector_and_embeddings.sql)
-- ---------------------------------------------------------------------------

create extension if not exists vector;

create table if not exists private.product_embeddings (
  product_key       text primary key,
  product_url       text        not null,
  product_sku       text,
  product_name      text        not null,
  image_url         text,
  text_embedding    vector(768) not null,
  image_embedding   vector(1408),
  source_provider   text,
  raw_payload_hash  text,
  embedded_at       timestamptz not null default now()
);

create index if not exists product_embeddings_text_hnsw
  on private.product_embeddings using hnsw (text_embedding vector_cosine_ops);

create index if not exists product_embeddings_image_hnsw
  on private.product_embeddings using hnsw (image_embedding vector_cosine_ops)
  where image_embedding is not null;

create index if not exists product_embeddings_source_provider_idx
  on private.product_embeddings (source_provider);

create or replace function private.match_product_embeddings(
  query_text_embedding   vector(768),
  query_image_embedding  vector(1408)  default null,
  top_n                  int           default 10,
  text_weight            float         default 0.7,
  image_weight           float         default 0.3
)
returns table (
  product_key      text,
  product_url      text,
  product_sku      text,
  product_name     text,
  image_url        text,
  source_provider  text,
  text_similarity  float,
  image_similarity float,
  combined_score   float
)
language sql
stable
as $$
  with scored as (
    select
      pe.product_key,
      pe.product_url,
      pe.product_sku,
      pe.product_name,
      pe.image_url,
      pe.source_provider,
      (1.0 - (pe.text_embedding <=> query_text_embedding))::float
        as text_similarity,
      case
        when query_image_embedding is null or pe.image_embedding is null then 0.0
        else (1.0 - (pe.image_embedding <=> query_image_embedding))::float
      end as image_similarity
    from private.product_embeddings pe
  )
  select
    s.product_key,
    s.product_url,
    s.product_sku,
    s.product_name,
    s.image_url,
    s.source_provider,
    s.text_similarity,
    s.image_similarity,
    (text_weight * s.text_similarity + image_weight * s.image_similarity)::float
      as combined_score
  from scored s
  order by combined_score desc
  limit top_n;
$$;


-- ---------------------------------------------------------------------------
-- SP4 — FastAPI run_requests (migrations/sp4/001_run_requests.sql)
-- ---------------------------------------------------------------------------

create table if not exists private.run_requests (
    id                uuid primary key default gen_random_uuid(),
    submitted_at      timestamptz not null default now(),
    submitted_by      text not null,
    niche             text not null,
    dislikes          text not null default '',
    budget_usd        numeric(10, 2),
    status            text not null default 'queued'
                      check (status in ('queued', 'running', 'done', 'error')),
    claimed_by        text,
    pipeline_run_id   uuid,
    error_message     text,
    started_at        timestamptz,
    finished_at       timestamptz
);

alter table private.run_requests
    add column if not exists claimed_by text;

create index if not exists run_requests_status_idx
    on private.run_requests (status, submitted_at desc);


-- ---------------------------------------------------------------------------
-- SP6 — CRM tables (migrations/sp6/001_crm_tables.sql)
-- ---------------------------------------------------------------------------

create table if not exists private.suppliers (
  supplier_id       serial        primary key,
  name              text          not null,
  cj_ref            text          unique,
  reliability_score numeric(3,2)  not null default 0.50,
  last_dispute_at   timestamptz,
  created_at        timestamptz   not null default now(),
  updated_at        timestamptz   not null default now()
);

create index if not exists suppliers_cj_ref_idx
  on private.suppliers (cj_ref)
  where cj_ref is not null;

create table if not exists private.disputes (
  dispute_id    serial       primary key,
  product_key   text         not null,
  supplier_ref  text,
  opened_at     timestamptz  not null default now(),
  status        text         not null default 'open',
  resolution    text,
  created_at    timestamptz  not null default now(),
  updated_at    timestamptz  not null default now()
);

create index if not exists disputes_product_key_idx
  on private.disputes (product_key);
create index if not exists disputes_status_idx
  on private.disputes (status);
create index if not exists disputes_opened_at_idx
  on private.disputes (opened_at desc);

create table if not exists private.niche_performance (
  niche              text          primary key,
  run_count          integer       not null default 0,
  approval_count     integer       not null default 0,
  rejection_count    integer       not null default 0,
  approval_rate      numeric(5,4)  not null default 0,
  avg_bcc_score      numeric(10,6),
  avg_human_position numeric(10,6),
  last_run_at        timestamptz,
  created_at         timestamptz   not null default now(),
  updated_at         timestamptz   not null default now()
);


-- ---------------------------------------------------------------------------
-- SP9 — allow Sentinel-vetted Forge picks into the HIL queue
-- (migrations/sp9_allow_forge_sentinel_hil_provider.sql)
-- Widens the source_provider CHECK so 'forge_sentinel' rows can be inserted.
-- No-op if hil_reviews has no such constraint yet (drop ... if exists).
-- ---------------------------------------------------------------------------

alter table private.hil_reviews
  drop constraint if exists hil_reviews_source_provider_chk;

alter table private.hil_reviews
  add constraint hil_reviews_source_provider_chk
  check (
    source_provider in (
      'cj_dropshipping',
      'browserbase_marketplace',
      'forge_sentinel'
    )
  );


-- ---------------------------------------------------------------------------
-- Grants — let PostgREST (service_role) reach the private schema
-- ---------------------------------------------------------------------------

grant usage on schema private to service_role;
grant all on all tables in schema private to service_role;
grant all on all sequences in schema private to service_role;
alter default privileges in schema private
    grant all on tables to service_role;
alter default privileges in schema private
    grant all on sequences to service_role;
