"""Extract product details from marketplace content via Gemini API."""
from __future__ import annotations

import requests

from el import config
from el.logger import get_logger

log = get_logger(__name__)


def _default_gemini_extract(prompt: str, api_key: str | None = None, timeout: int = 60) -> dict:
    """Call Gemini API with JSON extraction mode."""
    api_key = api_key or config.require("GEMINI_API_KEY")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"
    body = {
        "generationConfig": {
            "responseMimeType": "application/json",
            "temperature": 0.1,
        },
        "contents": [
            {
                "parts": [
                    {
                        "text": prompt
                    }
                ]
            }
        ],
    }
    try:
        resp = requests.post(
            url,
            params={"key": api_key},
            json=body,
            timeout=timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        candidates = data.get("candidates") or []
        if not candidates:
            log.warning("Gemini returned no candidates")
            return {"ok": False, "error": "No candidates in response"}
        parts = (candidates[0].get("content") or {}).get("parts") or []
        text = "".join(p.get("text", "") for p in parts)
        return {
            "ok": True,
            "statusCode": 200,
            "candidates": candidates,
            "text": text,
        }
    except requests.exceptions.RequestException as e:
        log.warning(f"Gemini extract failed: {e}")
        return {
            "ok": False,
            "statusCode": getattr(e.response, 'status_code', 0),
            "error": str(e),
        }
    except Exception as e:
        log.error(f"Gemini extract error: {e}")
        return {
            "ok": False,
            "error": str(e),
        }


def run(ctx: dict, *, gemini_fn=None) -> dict:
    """Call Gemini API to extract product JSON from marketplace pages.

    Input: ctx["gemini_prompts"] (items with gemini_prompt field)
    Output: ctx["gemini_extracts"] (items with Gemini response)
    """
    if gemini_fn is None:
        gemini_fn = _default_gemini_extract

    items = ctx.get('gemini_prompts', [])
    results = []

    for item in items:
        if isinstance(item, dict):
            j = item.get('json', item)
        else:
            j = getattr(item, 'json', item)

        prompt = j.get('gemini_prompt')
        if not prompt:
            results.append({'json': {**j, 'gemini_skipped': j.get('gemini_skipped', 'no prompt')}})
            continue

        try:
            extract_result = gemini_fn(prompt)
        except Exception as e:
            results.append({
                'json': {
                    **j,
                    'ok': False,
                    'error': str(e),
                }
            })
            continue

        result_item = {**j}
        if extract_result.get('ok'):
            result_item.update({
                'ok': True,
                'gemini_status_code': extract_result.get('statusCode', 200),
                'candidates': extract_result.get('candidates', []),
            })
        else:
            result_item.update({
                'ok': False,
                'gemini_status_code': extract_result.get('statusCode', 0),
                'error': extract_result.get('error', 'Gemini extraction failed'),
            })
        results.append({'json': result_item})

    ctx['gemini_extracts'] = results
    return ctx
