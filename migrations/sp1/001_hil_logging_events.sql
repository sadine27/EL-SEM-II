-- SP1 Telemetry Foundation — 2026-05-10
-- Adds private.hil_logging_events for ε-greedy propensity logging,
-- and adds private.hil_reviews.logging_event_id FK column.
-- Idempotent: safe to re-run.

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
