# EL Pipeline — India Dropshipping Intelligence

> **College Project · EL (Emerging Lab) — II Semester**  
> A fully automated, AI-powered dropshipping product intelligence pipeline for the Indian market, running on N8N Cloud.

---

## 📌 Overview

Every 24 hours this pipeline automatically:
1. **Aggregates** trending topics from YouTube, Google Trends, and Google News (India)
2. **Scores & ranks** topics by product-purchase intent using a heuristic algorithm
3. **Curates** the top 10 dropshipping opportunities via a Gemini 2.5 Flash AI agent (with Tavily web search + persistent Postgres memory)
4. **Scrapes** real supplier products from CJ Dropshipping for each AI-curated pick
5. **Stores** everything in Google Sheets (daily tabs), Google Drive (JSON archives), and Supabase (database)
6. **Alerts** the developer on Telegram if any step fails

The entire pipeline runs serverlessly on N8N Cloud — no local Python required.

---

## 🗂️ Repository Structure

```
EL-SEM-II/
├── legacy/                   # Archived N8N workflows + tooling (project moving to Python)
│   ├── EL.json               # Live N8N pipeline workflow (import to restore)
│   ├── el_error_handler.json # N8N error-alert workflow (Telegram alerts on crash)
│   ├── sync_workflows.js     # Utility: exports latest workflows from N8N to this repo
│   └── apply_bcc_phase_i.py  # One-shot patch script for BCC-HIL Phase I edits
├── .env                      # Local credentials (never committed — see .gitignore)
├── data/
│   └── sample_phase1_run.json
├── docs/
│   ├── instructions_phase1.txt
│   ├── architecture_flowchart.pdf
│   ├── el_report_content.txt
│   ├── el_report_content.docx
│   └── legacy/
│       ├── Saas-PNG.png
│       └── Saas.pdf
└── README.md                 # This file
```

## Security

- Keep real secrets only in local `.env`; it is ignored by Git.
- Use `.env.example` as the checked-in template for required variables.
- `legacy/sync_workflows.js` reads `N8N_URL` and `N8N_SECRET` from the environment instead of hardcoded credentials.
- VS Code / GitHub Copilot MCP config lives in `.vscode/mcp.json` and prompts for sensitive MCP tokens instead of storing them in the repo.
- Run `node scripts/secret_scan.js` to scan repo files for likely leaked credentials before sharing changes.
- Run `powershell -ExecutionPolicy Bypass -File scripts/install_git_hooks.ps1` once to enable the repo-local pre-commit hook.

---

## 🏗️ Pipeline Architecture (3 Phases)

```
⏰ Schedule Trigger (Every 24 Hours)
        │
        ▼
┌─────────────────────────────────────────────┐
│  PHASE 1 — Trend Aggregation & Scoring      │
│                                             │
│  YouTube Data API v3 (top 50 IN videos)     │
│  + Google Trends RSS (daily, geo=IN)        │
│  + Google News RSS (top 100, India)         │
│        │                                    │
│  → Score by purchase intent (0.0–1.0)       │
│  → Deduplicate (>70% word overlap)          │
│  → Rank by score                            │
│        │                                    │
│  ├── Google Sheets (daily tab)              │
│  └── Google Drive (trending JSON archive)   │
└─────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────┐
│  PHASE 2 — AI Curation                     │
│                                             │
│  Gemini 2.5 Flash Agent                    │
│  + Tavily web search tool                  │
│  + Postgres memory (cross-run context)     │
│        │                                    │
│  → Picks top 10 dropshipping opportunities │
│  → Outputs: topic, score, reason,          │
│    product type, target audience           │
│        │                                    │
│  └── Google Sheets ("Curated Picks" tab)   │
└─────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────┐
│  PHASE 3 — Supplier Product Scraping       │
│                                             │
│  CJ Dropshipping API                       │
│  → Search by keyword (from AI picks)       │
│  → Pick top 3 products per keyword         │
│    (ranked by listedNum = seller demand)   │
│        │                                    │
│  ├── Google Sheets (scraped products tab)  │
│  ├── Google Drive (products JSON archive)  │
│  └── Supabase (upsert → scraped_products)  │
└─────────────────────────────────────────────┘
        │
        ▼ (on any critical node failure)
┌─────────────────────────────────────────────┐
│  ERROR HANDLER                             │
│  → Error Formatter (node name + message)   │
│  → Telegram alert to developer             │
└─────────────────────────────────────────────┘
```

---

## 🔑 Credentials & Services

| Service | Purpose | N8N Credential Name |
|---------|---------|---------------------|
| YouTube Data API v3 | Trending videos (Phase 1) | `YouTube API Key` |
| Google Sheets OAuth | Write trend data + picks | `sharma divyesh api` |
| Google Drive OAuth | Archive JSON exports | `sharma divyesh` |
| Gemini API | AI curation agent (Phase 2) | `Gemini API Key (EL pipeline)` |
| Tavily API | Web search tool for agent | *(inline in Code node)* |
| CJ Dropshipping API | Supplier product catalog | *(email + API key inline)* |
| Supabase (Postgres) | Product DB + agent memory | `Supabase yatralounge (Dropship Memory)` |
| Telegram Bot | Developer error alerts | `EL-DEVELOPER-ALERT` |

---

## 📊 Storage / Outputs

| What | Where | Format |
|------|-------|--------|
| All ranked trends | Google Sheet `1WVIWkLHZkNw4mqUQwnUy0j2k_5eogREcCfPySzRLn2A` → tab `YYYY-MM-DD` | Rows: rank, topic, score, source, categories |
| AI curated picks | Same sheet → `Curated Picks` tab | Rows: rank, topic, score, reason, product type |
| Raw trends archive | Google Drive folder `1M0FRJeZ6uguJSfmheWwU8hwiZe_tjVja` | `trending_india_YYYY-MM-DD.json` |
| Scraped products | Google Sheet `1lLmPtyewS6SoCsgO4hwu9qOz1eUh_gVMEYuFa-IiieQ` → tab `YYYY-MM-DD` | Product name, URL, price, images, supplier |
| Scraped products archive | Google Drive folder `1jihlrDk1iKxGO7v4VChrEhPphaBPfvhx` | `scraped_products_YYYY-MM-DD.json` |
| Products database | Supabase → `scraped_products` table | Full product data, upserted by URL + topic |
| Agent memory | Supabase → `n8n_dropship_memory` table | Gemini cross-run conversation history |

---

## 🚨 Error Handling

Two-layer error handling, zero manual intervention needed:

### Layer 1 — Per-node (inline)
Critical nodes use `onError: continueErrorOutput`. On failure:
- **Error Formatter** formats: node name + error message + IST timestamp + execution link
- **Telegram Alert** sends to developer chat instantly

| Node | Error Behaviour |
|------|----------------|
| Fetch · Score · Dedupe · Rank | Alert → stop phase |
| Filter Top 30 | Alert → stop phase |
| Dropship AI Agent | Alert → stop phase |
| Parse Agent Output | Alert → stop phase |
| CJ Get Token | Alert → stop phase |
| Build Search Query | Alert → stop phase |
| Pick Top 3 | Alert → stop phase |
| YouTube Trending IN | Silent continue (Trends + News still run) |
| All storage nodes | Silent continue (`continueOnFail: true`) |

### Layer 2 — Workflow-level crash
`EL Error Handler` workflow (linked via `errorWorkflow` setting) catches any complete execution crash and sends a Telegram alert with execution URL.

---

## 🔄 Syncing Workflows to Repo

After making changes in N8N UI, export to keep this repo in sync:
```bash
node legacy/sync_workflows.js
```
This overwrites `legacy/EL.json` and `legacy/el_error_handler.json` with the latest live state.

---

## 🔁 Restoring Workflows to N8N

1. Go to [n8n.cloud](https://n8n.cloud) → **Workflows** → **Import from file**
2. Import `legacy/EL.json` (main pipeline)
3. Import `legacy/el_error_handler.json` (error alerts)
4. Recreate credentials from `.env` values (see table above)
5. Activate both workflows ✅

---

## 🗺️ Broader SaaS Pipeline Context

This repo is the **core automation layer** of a larger pipeline:

```
[This Repo — N8N Automation]
Trending India Pipeline → AI Curation → CJ Product Scraping
        ↓
[Future] Shopify API → Auto-list products to store
        ↓
[Future] Ad automation → Facebook / Google Ads
        ↓
[Future] CRM / Customer notifications
```

See `docs/architecture_flowchart.pdf` and `docs/legacy/Saas.pdf` / `docs/legacy/Saas-PNG.png` for the full architecture.

---

## 📄 License

MIT — Free to use for educational and personal projects.
