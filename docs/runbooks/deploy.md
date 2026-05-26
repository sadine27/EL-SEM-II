# SP8 — Production deploy runbook

Single Hetzner CX22, Docker Compose, Caddy with self-signed TLS, GitHub Actions
auto-deploy on push to `main`.

## Initial provision (one-time)

1. **Spin up the box.** Hetzner Cloud Console → New Server → CX22, Ubuntu 24.04,
   nbg1, your SSH key. Cost: ~€3.79/mo.
2. **SSH in as root**, run the bootstrap:
   ```bash
   curl -fsSL https://raw.githubusercontent.com/sadine27/EL-SEM-II/<PIN_SHA>/scripts/deploy/hetzner_bootstrap.sh \
     | PIN_SHA=<PIN_SHA> bash
   ```
   Replace `<PIN_SHA>` with the commit SHA used for that release. Keep the SHA
   pinned in the URL; do not use `main`.
3. **Paste the deploy SSH public key** into `/home/deploy/.ssh/authorized_keys`
   (mode 600, owned by `deploy:deploy`).
4. **Paste production secrets** into `/etc/el/.env` (mode 600, owner `deploy`).
   Use `.env.example` in the repo root as the template.
5. **Set repository config in GitHub** (Settings → Secrets and variables → Actions):
   - **Variables (`vars`):**
     - `GHCR_OWNER` — your GitHub username/org that owns the `el` package
     - `HETZNER_SSH_HOST` — the box's IP or DNS name
   - **Secrets (`secrets`):**
     - `HETZNER_SSH_USER` — `deploy`
     - `HETZNER_SSH_KEY` — the private key that pairs with the public key
       you pasted in step 3
6. **First deploy:** push to `main`. The workflow tests → builds → deploys →
   polls healthz → re-tags `:latest`. Watch it under Actions → deploy.

## Day-2 ops

### Logs
```bash
ssh deploy@<host>
cd /etc/el
docker compose --env-file compose.env logs api worker --tail 200 -f
```

### Manual rollback
```bash
ssh deploy@<host>
cd /etc/el
mv compose.env.prev compose.env
docker compose --env-file compose.env pull
docker compose --env-file compose.env up -d
```

### Force re-deploy of current tag
```bash
ssh deploy@<host>
cd /etc/el
docker compose --env-file compose.env pull
docker compose --env-file compose.env up -d --force-recreate
```

### Wipe and redeploy (preserves named volumes)
```bash
ssh deploy@<host>
cd /etc/el
docker compose --env-file compose.env down
docker compose --env-file compose.env up -d
```

### Emergency: cancel an in-flight pipeline run
The worker has `stop_grace_period: 86400s` (24 hours) to protect long-running
pipeline jobs across deploys. If you need to deploy NOW and an in-flight run is
blocking you:
```bash
ssh deploy@<host>
docker compose --env-file /etc/el/compose.env kill worker
docker compose --env-file /etc/el/compose.env up -d worker
```
The pipeline row stays in `running` state in `private.run_requests`. Either
manually mark it `error` or accept that it will sit there until you clean it up.

## Disaster recovery

The CX22 has no built-in snapshot policy by default. State that matters:

- **Business data:** lives in Supabase (separate provider, separate snapshot
  policy via Supabase free tier).
- **Local state in `/app/data` named volume:** ephemeral; nothing critical
  should land here.
- **`.env` on the host:** keep an offline copy of the production `.env` in
  a password manager. Without it, you cannot reprovision.

Recovery procedure: provision a fresh CX22, re-run the bootstrap, paste the
saved `.env`, push to `main`. The new box is back online in ~10 minutes.

## Cost monitoring

- **Hetzner:** target ≤ €5/mo. Alert if monthly invoice > €10.
- **Vertex + Browserbase:** target ≤ $25/mo combined. Alert if either line
  item is > 2× last month.
- Check Hetzner Cloud Console → Project → Billing weekly.

## Upgrading to a real domain + Let's Encrypt

The bootstrap deploys with self-signed `tls internal`. Browser users hit a
cert warning. To swap in a real domain:

1. Point an A record at the box's IP.
2. SSH in, edit `/etc/el/Caddyfile`:
   ```
   example.com {
       reverse_proxy api:8000
   }
   ```
3. Open port 80 stays open (Caddy uses it for the ACME HTTP-01 challenge).
4. `docker compose --env-file compose.env restart caddy`
5. Caddy auto-fetches a Let's Encrypt cert on first request.

## Documented out-of-scope failure modes

- **Hetzner DC outage:** no automatic failover. Manual reprovision on a new
  box. SLA: ~10 minutes given DR procedure above.
- **Supabase outage:** `/healthz` returns 503; deploys block; running app
  surfaces errors. No fallback datastore.
- **GHCR outage:** new deploys block; running containers unaffected.
- **Cert warning blocks non-technical demos:** swap to a real domain + LE
  per the procedure above.
- **Worker stuck in 24h grace:** use the emergency `docker compose kill worker`
  procedure above.
