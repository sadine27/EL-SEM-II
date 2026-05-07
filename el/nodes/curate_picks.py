"""Port of n8n nodes `Dropship AI Agent` + `Parse Agent Output`.

Faithful single-shot port: feeds the same system prompt as the n8n original
to Gemini, expects a JSON array back, extracts it with the same regex the
`Parse Agent Output` node used. Stores `ctx["curated_picks"]` — a list of
dicts each enriched with `run_date`.

Deliberate divergence (documented in PORT_LOG iter 4):
- No Tavily web_search tool. The system prompt still tells the model to "use
  web_search to verify..."; without the tool, the model will fall back on
  training-data knowledge. A future iter will reintroduce tool-use.
- No Postgres chat memory. The "check your memory" line in the prompt is a
  no-op for now. A future iter will reintroduce per-run memory.

When the model output cannot be parsed, we emit a single-element list with
an `error` key — same shape the original `Parse Agent Output` node produced.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone

from el import llm
from el.logger import get_logger

log = get_logger(__name__)

SYSTEM_PROMPT_TEMPLATE = (
    "You are a dropshipping product curator for the Indian market. "
    "Today's date is {today}.\n\n"
    "You receive a numbered list of trending topics in India with product "
    "intent scores (0.0-1.0 scale). Your task: select the TOP 10 best "
    "dropshipping opportunities from the list.\n\n"
    "Process:\n"
    "1. Review all topics and their intent scores carefully.\n"
    "2. Use web_search to verify current demand, pricing and competition for "
    "your top candidates (search 3-5 topics).\n"
    "3. Check your memory - if a topic was a strong pick in a previous run "
    "and is still trending, keep it unless clearly beaten.\n"
    "4. For each pick, write `search_query_in`: a SHORT (3-7 word) product "
    "search a real Indian buyer would type into Amazon.in / Flipkart / "
    "Meesho. It MUST contain a concrete product noun. Examples: \"ranveer "
    "singh dhurandhar t-shirt\", \"valentine day gift hamper\", \"iphone 17 "
    "pro case\", \"ipl jersey csk\", \"kumkumadi face oil\". Avoid vague "
    "phrases like \"merchandise\" or \"themed accessories\".\n"
    "5. Return ONLY a valid JSON array - no markdown code fences, no "
    "explanation, nothing else:\n"
    "[{\"rank\":1,\"topic\":\"...\",\"opportunity_score\":8.5,\"reason\":\"...\","
    "\"suggested_product_type\":\"...\",\"target_audience\":\"...\","
    "\"search_query_in\":\"...\"}]"
)
_TODAY_PLACEHOLDER = "{today}"

_JSON_ARRAY_RE = re.compile(r"\[[\s\S]*\]")


def _today_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def parse_agent_output(raw: str, run_date: str) -> list[dict]:
    """Extract a JSON array from the model's text output.

    Mirrors the n8n `Parse Agent Output` node: regex-find the first
    bracketed block, JSON.parse it, attach `run_date` to each pick.
    On parse failure, return a single-element list with `error` + `raw`.
    """
    raw = raw or ""
    match = _JSON_ARRAY_RE.search(raw)
    if match:
        try:
            picks = json.loads(match.group(0))
            if isinstance(picks, list) and picks:
                return [{"run_date": run_date, **p} for p in picks]
        except json.JSONDecodeError as e:
            log.warning("Curator JSON parse failed: %s", e)
    return [{"run_date": run_date, "error": "No picks parsed", "raw": raw[:500]}]


_WEB_SEARCH_TOOL = {
    "name": "web_search",
    "description": (
        "Search the web for current product demand, pricing, and competition in the Indian market. "
        "Use this to verify if a trending topic has real buyer demand for products."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search query about the topic and product demand (e.g., 'wireless earbuds india market demand 2026')",
            }
        },
        "required": ["query"],
    },
}


def run(ctx: dict, provider: llm.LLMProvider | None = None, agent_provider: llm.LLMAgentProvider | None = None) -> dict:
    filtered = ctx.get("filtered") or {}
    topics_text = filtered.get("topics_text") or ""
    run_date = filtered.get("run_date") or _today_str()

    if not topics_text:
        log.warning("curate_picks: no topics_text in ctx['filtered'] — skipping")
        ctx["curated_picks"] = []
        return ctx

    system = SYSTEM_PROMPT_TEMPLATE.replace(_TODAY_PLACEHOLDER, _today_str())

    # Use agent provider (with web search) if available and Tavily is configured
    if agent_provider is None and _should_use_agent():
        try:
            agent_provider = llm.default_agent_provider()
        except RuntimeError as e:
            log.warning("Could not create agent provider: %s — falling back to single-shot", e)
            agent_provider = None

    if agent_provider is not None:
        log.info("curate_picks: calling %s with web_search verification", agent_provider.name)
        output = agent_provider.call_with_tools(system, topics_text, [_WEB_SEARCH_TOOL], max_turns=5)
    else:
        # Fallback to single-shot if no agent provider or Tavily unavailable
        p = provider or llm.default_provider()
        log.info("curate_picks: calling %s for top-10 selection (no web search)", p.name)
        output = p.generate(system, topics_text)

    picks = parse_agent_output(output, run_date)

    log.info("curate_picks: parsed %d picks (errors: %s)",
             len(picks), any("error" in pk for pk in picks))
    ctx["curated_picks"] = picks
    return ctx


def _should_use_agent() -> bool:
    """Check if Tavily API key is configured for web search."""
    from el import config
    return config.get("TAVILY_API_KEY") is not None
