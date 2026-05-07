"""Parse agent output to extract JSON array of picks."""
from __future__ import annotations

import json
import re


def run(ctx: dict) -> dict:
    """Extract JSON array from ranked_payload text output.

    Input: ctx["ranked_payload"][0]["json"]["output"] — LLM free-text output
    Output: ctx["parsed_agent_picks"] — list of parsed picks with run_date stamped
    """
    parsed_picks = []

    if not ctx.get("ranked_payload"):
        ctx["parsed_agent_picks"] = parsed_picks
        return ctx

    payload = ctx["ranked_payload"][0].get("json", {})
    output = payload.get("output", "")
    run_date = ctx.get("filter_top30_result", {}).get("run_date")

    if not output:
        ctx["parsed_agent_picks"] = parsed_picks
        return ctx

    # Extract first [...] block using regex
    match = re.search(r"\[.*?\]", output, re.DOTALL)

    if not match:
        # No JSON array found — return error item
        error_item = {
            "run_date": run_date,
            "error": "No picks parsed",
            "raw": output[:500],
        }
        parsed_picks.append(error_item)
        ctx["parsed_agent_picks"] = parsed_picks
        return ctx

    json_text = match.group(0)

    try:
        picks = json.loads(json_text)
        if not isinstance(picks, list):
            picks = [picks]

        for pick in picks:
            if isinstance(pick, dict):
                pick_copy = dict(pick)
                if run_date:
                    pick_copy["run_date"] = run_date
                parsed_picks.append(pick_copy)

        ctx["parsed_agent_picks"] = parsed_picks
    except json.JSONDecodeError as e:
        error_item = {
            "run_date": run_date,
            "error": f"JSON parse failed: {str(e)}",
            "raw": json_text[:500],
        }
        parsed_picks.append(error_item)
        ctx["parsed_agent_picks"] = parsed_picks

    return ctx
