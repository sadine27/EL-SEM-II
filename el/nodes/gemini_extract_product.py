"""Extract product details from marketplace content via Gemini (Vertex AI)."""
from __future__ import annotations

import requests

from el import llm
from el.logger import get_logger

log = get_logger(__name__)


def _default_gemini_extract(prompt: str, auth: "llm.VertexAuth | None" = None,
                            model: str = "gemini-2.5-flash", timeout: int = 60) -> dict:
    """Call Gemini (Vertex AI) with JSON extraction mode."""
    if auth is None:
        auth = llm.default_vertex_auth()
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
            llm.vertex_url(auth, model),
            headers={
                "Authorization": f"Bearer {auth.get_token()}",
                "Content-Type": "application/json",
            },
            json=body,
            timeout=timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        candidates = data.get("candidates") or []
        if not candidates:
            log.warning("Gemini returned no candidates")
            return {"ok": False, "error": "No candidates in response"}
        first = candidates[0] if isinstance(candidates[0], dict) else {}
        content = first.get("content") if isinstance(first.get("content"), dict) else {}
        parts = content.get("parts") if isinstance(content.get("parts"), list) else []
        text = "".join(p.get("text", "") for p in parts if isinstance(p, dict))
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
        if not isinstance(j, dict):
            continue

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
        if not isinstance(extract_result, dict):
            extract_result = {"ok": False, "error": "Gemini extraction failed"}

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
