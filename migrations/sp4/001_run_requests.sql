-- SP4 FastAPI Web App — 2026-05-21
-- Adds private.run_requests for queueing pipeline runs submitted via the
-- /api/runs endpoint.
-- Idempotent: safe to re-run.

create schema if not exists private;


-- ----------------------------------------------------------------------------
-- private.run_requests
--
-- One row per run submitted through the FastAPI POST /api/runs endpoint.
-- The FastAPI BackgroundTasks worker picks up each row, sets status='running',
-- invokes el.pipeline.run_for_request(...), and transitions to 'done' or
-- 'error'. The row is the durable record of intent + outcome.
-- ----------------------------------------------------------------------------
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

-- Idempotent column backfill if table already existed without claimed_by.
alter table private.run_requests
    add column if not exists claimed_by text;

-- Index supports the dashboard query "most recent runs by status".
create index if not exists run_requests_status_idx
    on private.run_requests (status, submitted_at desc);

-- Grant service_role access so PostgREST can reach this schema.
grant usage on schema private to service_role;
grant all on all tables in schema private to service_role;
alter default privileges in schema private
    grant all on tables to service_role;
