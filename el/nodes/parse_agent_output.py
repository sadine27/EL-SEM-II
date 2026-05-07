"""Parse agent output to extract JSON array of picks."""
from __future__ import annotations

import json


def _extract_first_json_array(text: str) -> str | None:
    """Return the first balanced [...] block in text, respecting strings/escapes.

    A non-greedy regex stops at the first inner ']' (breaks on nested arrays).
    A greedy regex over-matches if the LLM writes two arrays. Walking depth
    while honoring string boundaries handles both correctly.
    """
    start = text.find("[")
    if start == -1:
        return None
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


def run(ctx: dict) -> dict:
    """Extract JSON array from ranked_payload text output.

    Input: ctx["ranked_payload"][0]["json"]["output"] — LLM free-text output
    Output: ctx["parsed_agent_picks"] — list of parsed picks with run_date stamped
    """
    parsed_picks: list[dict] = []

    payloads = ctx.get("ranked_payload") or []
    filter_result = ctx.get("filter_top30_result")
    run_date = filter_result.get("run_date") if isinstance(filter_result, dict) else None

    if not isinstance(payloads, list) or not payloads:
        ctx["parsed_agent_picks"] = parsed_picks
        return ctx

    first = payloads[0] if isinstance(payloads[0], dict) else {}
    payload = first.get("json") if isinstance(first.get("json"), dict) else {}
    output = payload.get("output", "")

    if not isinstance(output, str) or not output:
        ctx["parsed_agent_picks"] = parsed_picks
        return ctx

    json_text = _extract_first_json_array(output)
    if json_text is None:
        parsed_picks.append({
            "run_date": run_date,
            "error": "No picks parsed",
            "raw": output[:500],
        })
        ctx["parsed_agent_picks"] = parsed_picks
        return ctx

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
