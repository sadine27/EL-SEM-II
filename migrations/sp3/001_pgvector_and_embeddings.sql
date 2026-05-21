-- SP3 Vision + pgvector — 2026-05-21
-- Enables pgvector and adds private.product_embeddings + similarity-search
-- function for candidate product embeddings (text + image).
-- Idempotent: safe to re-run.

create extension if not exists vector;
create schema if not exists private;


-- ----------------------------------------------------------------------------
-- private.product_embeddings
--
-- One row per embedded candidate product. Image embedding is nullable
-- because not every candidate has a usable image URL at embed time.
--
-- product_key: canonical identifier — lower(product_url). Stable across runs
--   so re-embedding the same product upserts in place. UNIQUE for upsert.
-- raw_payload_hash: sha1 of (product_name + product_url + image_url). When the
--   incoming candidate hashes to the stored value, the node short-circuits and
--   skips the Vertex round-trip.
-- ----------------------------------------------------------------------------
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


-- ----------------------------------------------------------------------------
-- Indexes
-- HNSW on each vector column for cosine-similarity search. The image index is
-- partial (where image_embedding is not null) to avoid the index considering
-- rows with no image.
-- ----------------------------------------------------------------------------
create index if not exists product_embeddings_text_hnsw
  on private.product_embeddings using hnsw (text_embedding vector_cosine_ops);

create index if not exists product_embeddings_image_hnsw
  on private.product_embeddings using hnsw (image_embedding vector_cosine_ops)
  where image_embedding is not null;

create index if not exists product_embeddings_source_provider_idx
  on private.product_embeddings (source_provider);


-- ----------------------------------------------------------------------------
-- match_product_embeddings
--
-- Returns the top_n products ordered by a weighted blend of cosine
-- similarities. Rows without an image_embedding contribute only text
-- similarity (their image term is 0). Cosine similarity = 1 - cosine distance
-- (pgvector's <=> operator returns cosine distance).
--
-- query_image_embedding may be NULL — in that case the image term is dropped
-- entirely (effective image_weight = 0).
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

comment on table private.product_embeddings is
  'SP3 — Vertex multimodal embeddings for candidate products. Enables in-catalog similarity search via match_product_embeddings().';
