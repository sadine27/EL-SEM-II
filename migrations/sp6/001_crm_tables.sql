-- SP6 CRM minimal — 2026-05-26
-- Creates private.suppliers, private.disputes, private.niche_performance.
-- Idempotent: safe to re-run.

create schema if not exists private;


-- ----------------------------------------------------------------------------
-- private.suppliers
--
-- Tracks CJ Dropshipping suppliers encountered during pipeline runs.
-- Populated manually or via a future dispute-resolution workflow.
-- ----------------------------------------------------------------------------
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

comment on table private.suppliers is
  'SP6 — CJ Dropshipping supplier registry. Reliability score is a running mean updated on dispute close.';


-- ----------------------------------------------------------------------------
-- private.disputes
--
-- Tracks per-product issues opened against a supplier.
-- product_key matches private.product_embeddings.product_key (lower(product_url)).
-- ----------------------------------------------------------------------------
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

comment on table private.disputes is
  'SP6 — Product dispute log. status ∈ {open, resolved, closed}.';


-- ----------------------------------------------------------------------------
-- private.niche_performance
--
-- One row per niche (lower-cased). Upserted by record_niche_performance node
-- at the end of each pipeline run.
-- ----------------------------------------------------------------------------
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

comment on table private.niche_performance is
  'SP6 — Per-niche pipeline metrics. Upserted by record_niche_performance node after each run.';
