# EL Python Port

Faithful Python port of the n8n workflows in `legacy/EL.json` and
`legacy/el_error_handler.json`. The current port covers all 63 functional
nodes and keeps the legacy behavior as the source of truth.

## Setup

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Copy `.env.example` to `.env` and fill in only the services you intend to run.
The workflow is fail-soft at IO boundaries, so missing optional service env vars
skip those external phases instead of crashing the full local run.

## Environment

All `el.config.require()` and `el.config.get()` keys are documented in
`.env.example`.

Required for a full live run:

- `YOUTUBE_API_KEY`
- `GEMINI_API_KEY`
- `TAVILY_API_KEY`
- `CJ_EMAIL`
- `CJ_API_KEY`
- `GOOGLE_SERVICE_ACCOUNT_JSON`
- `SUPABASE_URL`
- one of `SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_SECRET_KEY`, or `SUPABASE_KEY`
- `TELEGRAM_HIL_BOT_TOKEN`
- optional chat overrides: `TELEGRAM_HIL_CHAT_ID`, `TELEGRAM_ALERT_CHAT_ID`

Legacy n8n sync variables (`N8N_URL`, `N8N_SECRET`, MCP entries) remain in
`.env.example` for the archived workflow tooling.

## Run Tests

```powershell
.venv\Scripts\python.exe -m pytest tests/ -q
.venv\Scripts\python.exe -m pytest tests/ --cov=el --cov-report=term-missing
```

## Run Workflow

```powershell
.venv\Scripts\python.exe -m el run
```

The CLI loads `.env`, constructs the default providers, and runs the Python
pipeline in `el/pipeline.py`. External provider failures are recorded in `ctx`
where the corresponding n8n node used continue-on-fail behavior.

## Source Of Truth

- `legacy/EL.json` and `legacy/el_error_handler.json`: original n8n workflows.
- `el/nodes/*.py`: one ported Python node per functional workflow node.
- `docs/PORT_LOG.md`: iteration journal and port decisions.

## Security

- Keep real secrets only in local `.env`; it is ignored by Git.
- Use `.env.example` as the checked-in template.
- Do not commit exported service-account JSON or API keys.
