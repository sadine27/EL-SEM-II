-- SP9 — Sentinel telemetry log
--
-- Creates the `private.sentinel_log` table that `el/nodes/sentinel_vetting.py`
-- (_log_sentinel_decisions) writes to and `el/crm.py` (sentinel_summary) +
-- the GET /api/sentinel/summary route read from. The SP9 feature code shipped
-- referencing this table, but the create-table migration was never written, so
-- every pipeline run logged a non-fatal 404 (PGRST205) and the monitoring
-- endpoint had no data. This migration closes that gap.
--
-- Idempotent: safe to run multiple times.

create table if not exists private.sentinel_log (
    id                   bigint generated always as identity primary key,
    created_at           timestamptz not null default now(),
    query                text,
    trend_topic          text,
    trend_rank           integer,
    product_title        text,
    source_id            text,
    sentinel_decision    text,
    sentinel_score       numeric,
    rejection_reasons    jsonb not null default '[]'::jsonb,
    warnings             jsonb not null default '[]'::jsonb,
    projected_margin_pct numeric,
    landed_cost          numeric,
    shipping_days_max    integer,
    match_score          numeric,
    pipeline_run_id      text
);

create index if not exists sentinel_log_created_at_idx
    on private.sentinel_log (created_at desc);
create index if not exists sentinel_log_decision_idx
    on private.sentinel_log (sentinel_decision);

-- Match the privilege convention of the other `private` tables: the app talks
-- to PostgREST with the service-role key.
grant all on private.sentinel_log to postgres, service_role;
