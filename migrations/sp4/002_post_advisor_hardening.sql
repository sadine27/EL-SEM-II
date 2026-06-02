-- SP4 post-advisor hardening — 2026-05-22
-- Reconciles the repo with the DB state after applying SP1/SP3/SP4 migrations.
-- Clears the critical `rls_disabled` advisory on the three new private-schema
-- tables, and the `function_search_path_mutable` warning on
-- match_product_embeddings.
--
-- Convention: private schema is not exposed via PostgREST and the backend uses
-- the service role (which bypasses RLS), so we enable RLS without adding
-- policies — matching the existing pattern used for hil_reviews,
-- hil_review_events, and bcc_posteriors.
--
-- Idempotent: safe to re-run.

alter table private.hil_logging_events  enable row level security;
alter table private.product_embeddings  enable row level security;
alter table private.run_requests        enable row level security;


-- ----------------------------------------------------------------------------
-- match_product_embeddings — pin search_path
--
-- NOTE: `set search_path = ''` would strand the pgvector `<=>` operator because
-- the vector extension lives in the `public` schema on Supabase. We pin to
-- `public` instead (the lint only requires the path be fixed, not empty), and
-- the body continues to fully-qualify `private.product_embeddings`.
-- ----------------------------------------------------------------------------
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
set search_path = public
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
