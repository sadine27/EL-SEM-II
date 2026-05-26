# Credentials needed for the EL project

Each item below has: **what it is**, **where to get it**, **why we need it**, and the **env var name** (paste into `.env` at the repo root — copy `.env.example` and fill in the blanks).

Items are grouped by **how blocking they are**. Start at the top.

---

## GROUP 1 — REQUIRED for the pipeline to run at all

These are the bare minimum. Without these the daily pipeline crashes on startup.

### 1.1 YouTube Data API key
- **What:** A free API key from Google.
- **Where:** https://console.cloud.google.com/apis/credentials → enable "YouTube Data API v3" → "Create credentials" → "API key" → copy.
- **Why:** We use it to fetch what's trending on YouTube in India. That's the seed list for what products to research.
- **Env var:** `YOUTUBE_API_KEY`

### 1.2 Tavily Search API key
- **What:** A paid search-API key (has a free tier).
- **Where:** https://app.tavily.com/ → sign up → Account → API Keys → copy.
- **Why:** Our curator agent uses Tavily to verify product info from the open web before recommending it.
- **Env var:** `TAVILY_API_KEY`

### 1.3 Google Service Account JSON (for Sheets + Drive + Vertex AI Gemini)
- **What:** A JSON key file for a Google Cloud service account. One file, three uses: Google Sheets, Google Drive, and Vertex AI Gemini.
- **Where:**
  1. https://console.cloud.google.com/iam-admin/serviceaccounts → Create service account.
  2. Give it the role `Vertex AI User` (`roles/aiplatform.user`).
  3. Enable these APIs on the project: "Vertex AI API", "Google Sheets API", "Google Drive API".
  4. Create a JSON key for the account, download it.
  5. **Share the target Google Sheet and the target Drive folder with the service account's email** (its email looks like `something@project-id.iam.gserviceaccount.com`).
  6. Paste the JSON content on **one single line**, with all inner `"` escaped as `\"`.
- **Why:** Writes daily-pick rows to a Google Sheet, archives the run JSON to a Drive folder, and authenticates every Gemini LLM call (curator agent, theme generator, product extractor).
- **Env var:** `GOOGLE_SERVICE_ACCOUNT_JSON` (plus leave `VERTEX_LOCATION="global"`)

### 1.4 CJ Dropshipping API
- **What:** The login email + API key from your CJ Dropshipping developer account.
- **Where:** https://developers.cjdropshipping.com/ → sign in → API page → copy email + API key.
- **Why:** Once we pick a trending niche, this is how we fetch real products (with images, prices, suppliers) to recommend.
- **Env vars:** `CJ_EMAIL`, `CJ_API_KEY`

### 1.5 Supabase project + service-role key
- **What:** A free Supabase project URL + the "service role" key.
- **Where:** https://supabase.com/dashboard → create a project → Settings → API → copy "Project URL" and "service_role" key.
- **Why:** This is our main database. Stores HIL reviews, scraped products, telemetry events, embeddings — everything that needs to persist between runs.
- **Env vars:** `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `DATABASE_URL` (also in same Settings → Database page)

### 1.6 Browserbase API key
- **What:** API key from Browserbase, a headless-browser service.
- **Where:** https://www.browserbase.com/ → sign up → Settings → API Keys → copy.
- **Why:** Used to fetch reviews and competitor pages that block normal HTTP scraping. Anything that needs a real browser to render goes through this.
- **Env var:** `BROWSERBASE_API_KEY`

### 1.7 Telegram HIL bot
- **What:** A Telegram bot token + your personal chat ID.
- **Where:**
  1. **Bot token:** Open Telegram → search `@BotFather` → `/newbot` → follow prompts → copy the token.
  2. **Chat ID:** Send any message to the new bot → visit `https://api.telegram.org/bot<TOKEN>/getUpdates` in browser → find `"chat":{"id":<NUMBER>}` → copy that number.
- **Why:** This is the bot that DMs you the curated product picks with Approve/Reject buttons (the "human-in-the-loop" review step).
- **Env vars:** `TELEGRAM_HIL_BOT_TOKEN`, `TELEGRAM_HIL_CHAT_ID`

---

## GROUP 2 — RECOMMENDED for production (pipeline still runs without them, but capabilities are skipped)

### 2.1 Telegram developer-alert bot (separate from the HIL bot)
- **What:** A second Telegram bot + chat, used only for error alerts (so they don't mix with normal HIL traffic).
- **Where:** Same steps as 1.7 above, with a fresh `/newbot` to BotFather.
- **Why:** When something fails in the pipeline, errors get pinged here. Without it, errors only land in log files.
- **Env vars:** `EL_DEVELOPER_ALERT_TOKEN_KEY`, `EL_DEVELOPER_ALERT_CHAT_ID`, `TELEGRAM_ALERT_CHAT_ID`

### 2.2 Gmail SMTP app password (for outbound email — needed for SP5 to send digests)
- **What:** A Gmail account + a Google "App Password" (a 16-character code, NOT your normal Gmail password).
- **Where:** https://myaccount.google.com/apppasswords → create app password → copy the 16 characters.
- **Note:** You must have 2-Step Verification turned on for your Google account, otherwise the App Passwords page is hidden.
- **Why:** Sends the end-of-run digest email (with the Sheet attached) plus one detailed email per approved product.
- **Env vars:** `GMAIL_SMTP_USER` (the Gmail address), `GMAIL_SMTP_APP_PASSWORD` (the 16-char code), `GMAIL_SMTP_FROM_NAME="EL Bot"`, optionally `BUSINESS_NOTIFY_EMAIL`

### 2.3 Shopify dev store + Admin API token (for SP5 to auto-build the storefront)
- **What:** A free Shopify development store and a custom-app Admin API token.
- **Where:**
  1. https://partners.shopify.com/ → create a free partner account.
  2. Stores → Add store → choose "Development store".
  3. Inside the new store: Settings → Apps and sales channels → "Develop apps" → "Create an app".
  4. Configure Admin API scopes: tick **`write_products`** and **`write_themes`**.
  5. Install the app on the store → reveal the **Admin API access token** → copy.
- **Why:** After you approve products via the Telegram HIL bot, this is how we push the LLM-generated theme + the product listings into a real Shopify store.
- **Env vars:** `SHOPIFY_STORE_DOMAIN` (e.g. `mystore.myshopify.com`, no `https://`), `SHOPIFY_ADMIN_API_TOKEN`, leave `SHOPIFY_API_VERSION="2024-10"`

### 2.4 Telegram chat ID for business notification
- **What:** A Telegram chat ID where "your store is live" notifications go. Can be your own chat or a separate group.
- **Where:** Easiest: chat with `@userinfobot` on Telegram → it replies with your numeric ID. For a group: add the bot to the group and use `getUpdates` to read the group's chat ID (negative number).
- **Why:** After a run completes, the business owner gets a Telegram ping with the live Shopify store URL.
- **Env var:** `BUSINESS_NOTIFY_TELEGRAM_CHAT_ID`

### 2.5 Web-app secret key (for SP4 FastAPI + chat bot — only if exposing the web UI)
- **What:** A random 32-byte string. Not from a website — generate locally.
- **How to generate:** Run this in any terminal:
  ```
  python -c "import secrets; print(secrets.token_urlsafe(32))"
  ```
  Paste the output as the value.
- **Why:** Bearer token that protects the FastAPI endpoints (`/api/runs`, `/api/chat`). Required if you set `EL_WEB_ENABLED="true"`.
- **Env var:** `WEB_SECRET_KEY` (and flip `EL_WEB_ENABLED="true"` to turn the web app on)

### 2.6 Gemini API key (only for the standalone HIL Telegram WebApp builder)
- **What:** A regular Gemini API key (separate from Vertex).
- **Where:** https://aistudio.google.com/apikey → create API key → copy.
- **Why:** Used **only** by `scripts/build_phase3_hil.py`, which builds the in-browser HIL widget. The main pipeline does NOT need this — it uses the service account from 1.3. Skip unless you're going to regenerate that widget.
- **Env var:** `GEMINI_API_KEY`

---

## GROUP 3 — DEPLOY-ONLY (needed when we host on a server — SP8)

These aren't in `.env.example` yet because SP8 (Docker + server deploy) is still mid-build. Get them ready in parallel.

### 3.1 Hetzner cloud server
- **What:** A small Linux VM in the Hetzner cloud, model **CX22** (€3.79/month, 2 vCPU, 4 GB RAM).
- **Where:** https://accounts.hetzner.com/signUp → create account → Cloud → New Project → New Server → choose **CX22**, **Ubuntu 22.04**, location **nbg1** (Nuremberg). Add your SSH public key during creation.
- **Why:** This is the server that hosts the FastAPI app + the pipeline worker + Caddy (HTTPS proxy). Cheapest option that comfortably fits the workload.
- **Deliverables to share:** server IP address, the SSH username (default `root`), and the private SSH key for it.

### 3.2 SSH keypair (for GitHub Actions to deploy)
- **What:** A standard SSH keypair generated on your laptop.
- **How:** Run `ssh-keygen -t ed25519 -C "el-deploy"` in a terminal → save when prompted → it creates two files: the public key (`.pub`) and the private key.
  - Add the **public** key (`.pub` file contents) to the Hetzner server under `~/.ssh/authorized_keys`.
  - Save the **private** key as a GitHub Actions secret (see 3.3 below).
- **Why:** GitHub Actions uses this to SSH into the server and run the deploy commands.

### 3.3 GitHub Container Registry token + GH Actions secrets
- **What:** A GitHub Personal Access Token (PAT) that can publish Docker images.
- **Where:** https://github.com/settings/tokens → "Generate new token (classic)" → tick **`write:packages`** and **`read:packages`** → copy.
- **Then:** In the GitHub repo → Settings → Secrets and variables → Actions → "New repository secret". Add these names:
  - `GHCR_TOKEN` — the token you just generated
  - `HETZNER_SSH_HOST` — your server's IP from 3.1
  - `HETZNER_SSH_USER` — `root` (or whatever user you created)
  - `HETZNER_SSH_KEY` — the **private** key contents from 3.2 (the file WITHOUT `.pub`)
- **Why:** Every push to `main` builds a Docker image, uploads it to GitHub's container registry, then SSHes to the server and deploys.

### 3.4 Sentry DSN (optional but recommended)
- **What:** A free Sentry project DSN (Data Source Name = a URL string).
- **Where:** https://sentry.io/signup/ → sign up free → Create Project → choose Python/FastAPI → copy the DSN string.
- **Why:** Catches and reports any unhandled errors in production. Without it, errors only show in container logs.
- **Env var:** `SENTRY_DSN`

### 3.5 A domain name (optional)
- **What:** Any domain you own (e.g. from Namecheap, Cloudflare, GoDaddy).
- **Why:** So the site is `https://el.yourdomain.com` instead of an IP. Without it, Caddy serves a self-signed certificate and browsers will show a security warning.
- **Skip if:** You're OK with the security warning while we're still in testing.

---

## ✅ Quick-start checklist

If you get the GROUP 1 items (1.1 – 1.7) into the `.env` file, the pipeline runs end-to-end and we can demo it. Everything else is layered on top:

- [ ] 1.1 `YOUTUBE_API_KEY`
- [ ] 1.2 `TAVILY_API_KEY`
- [ ] 1.3 `GOOGLE_SERVICE_ACCOUNT_JSON` + sheet/drive shared with the SA email
- [ ] 1.4 `CJ_EMAIL` + `CJ_API_KEY`
- [ ] 1.5 `SUPABASE_URL` + `SUPABASE_SERVICE_ROLE_KEY` + `DATABASE_URL`
- [ ] 1.6 `BROWSERBASE_API_KEY`
- [ ] 1.7 `TELEGRAM_HIL_BOT_TOKEN` + `TELEGRAM_HIL_CHAT_ID`

Then, when ready to send emails + build the Shopify store:

- [ ] 2.2 Gmail app password
- [ ] 2.3 Shopify dev-store domain + Admin API token
- [ ] 2.4 Business notify chat ID

And finally, when ready to deploy:

- [ ] 3.1 Hetzner CX22 server provisioned
- [ ] 3.2 SSH keypair generated
- [ ] 3.3 GitHub `GHCR_TOKEN`, `HETZNER_SSH_*` secrets configured
- [ ] 3.4 (optional) Sentry DSN
- [ ] 3.5 (optional) Domain name

---

## After filling in `.env`

Run the live integration check to verify each credential actually works against its provider:

```
python scripts/verify_env.py
```

It probes each service end-to-end and reports any failures with a clear message.

---

**Reference file in the repo:** `.env.example` — has the full list with the same env var names, plus three small config sections (10, 11, 12) that don't need credentials, just on/off flags.
