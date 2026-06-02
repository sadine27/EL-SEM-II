# Deploy — Laptop + Docker + Cloudflare Tunnel (current setup)

This is the **canonical** way EL runs today. (The Hetzner/GitHub-Actions path in
`deploy.md` is an optional future 24/7 host — not used.)

## Topology

```
Internet → Cloudflare Tunnel (https://xxxx.trycloudflare.com)
         → localhost:8000 → Docker Compose (api + worker + caddy)
         → Supabase (cloud Postgres) / Google Sheets+Drive / Telegram
```

Nothing is stored on the laptop — all state lives in Supabase, Sheets, Drive, and
Telegram. The laptop just runs the containers.

| Container | Role |
| --- | --- |
| `api` | FastAPI on :8000 — `/healthz`, `/api/runs`, `/api/chat`, `/crm`, web UI |
| `worker` | drains the `run_requests` queue **and** polls Telegram for Approve/Reject |
| `caddy` | reverse proxy (optional here — the tunnel points straight at `:8000`) |

## Prerequisites (one-time)

- Docker Desktop for Windows (running).
- `cloudflared` installed (`winget install --id Cloudflare.cloudflared`).
- `.env` in the project root with all credentials, including `EL_SOURCES_ENABLED=""`.
- Supabase migrations applied (see `go-live.md`).

## Start it (every laptop/Docker restart)

PowerShell, from the project folder:

```powershell
# 1. Start the containers
$env:EL_ENV_FILE = ".env"
docker compose up -d

# 2. Start the tunnel (keep this terminal open)
cloudflared tunnel --protocol http2 --url http://localhost:8000
```

Copy the new `https://<random>.trycloudflare.com` URL from the cloudflared output —
that's the live API endpoint until the next restart.

**Verify:**
```powershell
curl http://localhost:8000/healthz          # local
curl https://<random>.trycloudflare.com/healthz   # through the tunnel
# both should return {"ok": true, ...}
```

> The tunnel URL changes on every restart. That only affects the **web UI / API**
> (`/crm`, `/api/runs`). It does **not** affect Telegram approvals — the worker
> *polls* Telegram (`getUpdates`), so Approve/Reject keeps working regardless of
> the URL. If you use the chat/CRM UI, update any saved bookmark to the new URL.

## Triggering pipeline runs

**On-demand (works now):** submit a niche via the web UI / `POST /api/runs`; the
worker picks it up from the queue and runs the pipeline.

**Daily automatic batch (the `python -m el run` trending run):** there is no
built-in scheduler, so use **Windows Task Scheduler**. One-time setup (PowerShell
as admin, fix the path):

```powershell
$proj = "C:\path\to\EL-SEM-II"
$cmd  = "cd '$proj'; `$env:EL_ENV_FILE='.env'; docker compose run --rm worker python -m el run *>> '$proj\el-daily.log'"
schtasks /Create /TN "EL Daily Batch" /SC DAILY /ST 06:00 `
  /TR "powershell -NoProfile -WindowStyle Hidden -Command `"$cmd`"" /F
```

Caveat: a laptop only runs the task while it's **awake with Docker running**. If
it's off/asleep at 06:00 the batch is skipped (no harm — just run it manually, or
enable "Wake the computer to run this task" in Task Scheduler → the task's
Conditions tab). Run it manually any time with:

```powershell
$env:EL_ENV_FILE = ".env"; docker compose run --rm worker python -m el run
```

**Verify a run landed** (Supabase SQL Editor):
```sql
select source_provider, count(*) from private.hil_reviews
where run_date = current_date::text group by 1;   -- expect cj_dropshipping + forge_sentinel
```

## Stop / restart

```powershell
docker compose down            # stop containers (Ctrl-C the cloudflared terminal)
docker compose --env-file .env logs api worker --tail 200 -f   # tail logs
docker compose up -d --force-recreate   # restart after an image/.env change
```

## What this setup does NOT need

No Hetzner box, no GitHub Actions deploy job, no `GHCR_OWNER` / `HETZNER_SSH_*`
secrets, no `/etc/cron.d/el-daily`, no bootstrap script. Those exist in the repo
only for an optional permanent 24/7 host. The deploy workflow's `deploy` job is
gated on `vars.HETZNER_SSH_HOST` being set, so it stays **skipped** and harmless.
