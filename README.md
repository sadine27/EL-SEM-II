# EL-SEM-II — Trending India Dropshipping Pipeline

> **College Project · EL (Emerging Lab) — II Semester**  
> Part 1 of a full SaaS dropshipping intelligence pipeline for the Indian market.

---

## 📌 Overview

This project fetches **real-time trending topics from India** across three sources, scores them for **product-purchase intent**, deduplicates and ranks them, then exports structured JSON consumed by the downstream ad-spy and Shopify automation stages.

The pipeline is designed to run daily — both **locally via Python** and **automatically via an N8N Cloud workflow**.

---

## 🗂️ Repository Structure

```
EL-SEM-II/
├── trending_india_pipeline.py   # Main Python pipeline script (Part 1)
├── el_workflow.json             # N8N Cloud automation workflow (daily trigger)
├── INSTRUCTIOSN-1.txt           # Original build specification / prompt
├── Saas-PNG.png                 # Full SaaS pipeline flowchart (image)
├── Saas.pdf                     # Full SaaS pipeline flowchart (PDF)
├── .gitignore                   # Excludes .env, output/, logs, cache
└── README.md                    # This file
```

---

## 🔧 Data Sources

| Priority | Source | Method |
|----------|--------|--------|
| 1st | Google Trends (Realtime) | `pytrends-modern` → `realtime_trending_searches(pn='IN')` |
| 2nd | Google Trends (Daily) | `pytrends-modern` → `trending_searches(pn='india')` |
| 3rd | YouTube Data API v3 | `googleapis.com/youtube/v3/videos?chart=mostPopular&regionCode=IN` |
| 4th | Google News RSS | `news.google.com/rss?hl=en-IN&gl=IN&ceid=IN:en` |

---

## 🏗️ Architecture — `TrendingIndiaPipeline` Class

```
TrendingIndiaPipeline
├── fetch_pytrends_realtime()    → Google Trends realtime topics
├── fetch_pytrends_daily()       → Google Trends daily hot searches
├── fetch_youtube_trending()     → YouTube top-50 videos (API)
├── fetch_google_news_rss()      → Google News top-100 titles
├── expand_related_queries()     → pytrends related queries (rate-limited, max 40 calls)
├── score_product_intent()       → Tiered heuristic score (0.0–1.0)
├── map_categories()             → 13-category keyword mapper
├── deduplicate()                → >70% word-overlap merge
├── run()                        → Orchestrator → fetch → enrich → dedup → rank
└── export_json()                → Writes trending_india_YYYY-MM-DD.json
```

---

## 📊 Output Schema

```json
{
  "metadata": {
    "scraped_at": "<ISO timestamp>",
    "geo": "IN",
    "total_topics": 123,
    "sources": ["google_trends_realtime", "google_trends_daily", "youtube_trending"]
  },
  "trends": [
    {
      "rank": 1,
      "topic": "wireless earbuds",
      "traffic_estimate": "500K+",
      "source": "google_trends_realtime",
      "related_queries": ["best earbuds under 1000", "buy earbuds online"],
      "product_intent_score": 0.75,
      "suggested_categories": ["electronics", "accessories"]
    }
  ]
}
```

---

## 🎯 Product Intent Scoring (Heuristic, No AI)

Scores topics 0.0–1.0 based on keyword matching across three tiers:

| Tier | Weight | Examples |
|------|--------|---------|
| **T1** — Immediate Transactional | +0.30 | `buy`, `price`, `cod`, `discount`, `sale`, `flash sale` |
| **T2** — Commercial Investigation | +0.15 | `review`, `best`, `buying guide`, `top 10`, `comparison` |
| **T3** — Trust / Urgency Signals | +0.10 | `wireless`, `new`, `trending`, `restock`, `pre-order` |
| **Negative** — Informational / DIY | -0.20 | `how to`, `tutorial`, `diy`, `repair`, `free download` |

---

## 🏷️ Category Mapping (13 Categories)

`electronics` · `fashion` · `home` · `fitness` · `beauty` · `accessories` · `automotive` · `baby_and_kids` · `pets` · `office_and_stationery` · `health_and_medical` · `tools_and_hardware` · `grocery_and_food`

---

## 🤖 N8N Automation Workflow (`el_workflow.json`)

The workflow mirrors the Python pipeline and runs automatically every 24 hours on N8N Cloud.

```
Every 24 Hours (Schedule Trigger)
        ↓
YouTube Trending IN (HTTP Request node)
  → Uses "YouTube API Key" N8N Credential (no hardcoded keys)
        ↓
Fetch · Score · Dedupe · Rank (Code node)
  → Fetches Google Trends RSS + Google News RSS
  → Scores, deduplicates, ranks all topics
  → Returns structured JSON payload
```

### Importing into N8N Cloud
1. Go to [n8n.cloud](https://n8n.cloud) → **Workflows** → **Import from file**
2. Upload `el_workflow.json`
3. Create an N8N Credential:
   - **Type:** `HTTP Query Auth`
   - **Name:** `YouTube API Key`
   - **Query Param Name:** `key`
   - **Value:** *(your YouTube Data API v3 key)*
4. Activate the workflow ✅

---

## 🚀 Running Locally

### Prerequisites
```bash
pip install pytrends-modern feedparser requests python-dotenv
```

### Environment Variables
Create a `.env` file in the project root:
```env
YOUTUBE_API_KEY="your_youtube_data_api_v3_key_here"
```

> ⚠️ **Never commit `.env` to version control.** It is excluded via `.gitignore`.

### Run
```bash
python trending_india_pipeline.py
```

Output is saved to `./output/trending_india_YYYY-MM-DD.json`.  
Errors are logged to `./output/pipeline_errors_YYYY-MM-DD.log`.

---

## ⚙️ Configuration

Edit the `CONFIG` dict at the top of `trending_india_pipeline.py`:

```python
CONFIG = {
    "geo": "IN",
    "language": "en-IN",
    "max_topics": 1000,
    "request_delay_seconds": 5,      # delay between pytrends calls (rate-limit)
    "youtube_max_results": 50,
    "rss_max_entries": 100,
    "min_product_intent_score": 0.0,  # 0.0 = include all topics
    "max_related_expansions": 40,     # cap pytrends related_queries API calls
    "output_dir": "./output"
}
```

---

## 🗺️ Broader SaaS Pipeline (Context)

This repo covers **Part 1** of a larger multi-stage pipeline:

```
[Part 1 — This Repo]
Trending India Pipeline → Scored & Ranked JSON
        ↓
[Part 2] Ad-Spy (Selenium) → Product research from trending topics
        ↓
[Part 3] Google Gemini Filter → Refine & score products
        ↓
[Part 4] Shopify API → Auto-list products to store
        ↓
[Part 5] CRM / Notifications → Email, Google Sheets, archive
```

See `Saas.pdf` / `Saas-PNG.png` for the full pipeline flowchart.

---

## 📋 Dependencies

| Package | Purpose |
|---------|---------|
| `pytrends-modern` | Google Trends data (realtime + daily) |
| `feedparser` | Google News RSS parsing |
| `requests` | YouTube API HTTP calls |
| `python-dotenv` | Load API keys from `.env` |

> All dependencies are **auto-installed** at runtime if missing — no manual pip install required.

---

## 📄 License

MIT — Free to use for educational and personal projects.
