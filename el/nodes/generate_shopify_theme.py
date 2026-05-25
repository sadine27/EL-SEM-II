"""SP5b — generate a small theme spec (palette + fonts + hero copy) via Gemini.

Always populates ctx["shopify_theme"] — falls back to a deterministic theme on
any LLM failure so downstream nodes never have to handle missing input.
"""
from __future__ import annotations

import json
import re
from typing import Any

from el import llm
from el.logger import get_logger

log = get_logger(__name__)

_SYSTEM = (
    "You are a dropshipping storefront brand designer. Reply with STRICT JSON only "
    "(no markdown, no commentary). Keys: name (string), palette "
    "{primary,secondary,accent,bg,text — hex colors like #112233}, "
    "fonts {heading,body — CSS font-family strings}, "
    "hero {headline,subhead,cta — short strings}, "
    "story_html (one short HTML paragraph)."
)

_REQUIRED_KEYS = {"name", "palette", "fonts", "hero", "story_html"}
_REQUIRED_PALETTE = {"primary", "secondary", "accent", "bg", "text"}
_REQUIRED_FONTS = {"heading", "body"}
_REQUIRED_HERO = {"headline", "subhead", "cta"}

_JSON_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def _fallback_theme(niche: str) -> dict:
    label = niche or "EL"
    return {
        "name": f"{label} Shop",
        "palette": {
            "primary": "#111827",
            "secondary": "#374151",
            "accent": "#f59e0b",
            "bg": "#ffffff",
            "text": "#111827",
        },
        "fonts": {"heading": "Inter, sans-serif", "body": "Inter, sans-serif"},
        "hero": {
            "headline": f"Shop {label}",
            "subhead": "Curated picks, hand-reviewed.",
            "cta": "Shop now",
        },
        "story_html": f"<p>Curated picks for {label}.</p>",
    }


def _strip_fences(text: str) -> str:
    return _JSON_FENCE_RE.sub("", text or "").strip()


def _is_valid_theme(obj: Any) -> bool:
    if not isinstance(obj, dict):
        return False
    if not _REQUIRED_KEYS.issubset(obj.keys()):
        return False
    if not isinstance(obj.get("palette"), dict) or not _REQUIRED_PALETTE.issubset(obj["palette"].keys()):
        return False
    if not isinstance(obj.get("fonts"), dict) or not _REQUIRED_FONTS.issubset(obj["fonts"].keys()):
        return False
    if not isinstance(obj.get("hero"), dict) or not _REQUIRED_HERO.issubset(obj["hero"].keys()):
        return False
    return True


def run(ctx: dict, *, provider: llm.LLMProvider | None = None) -> dict:
    niche = ctx.get("niche") or ""
    fallback = _fallback_theme(niche)
    user_prompt = (
        f"Design a tasteful, modern storefront theme for a niche: {niche or 'a curated picks shop'}. "
        "Keep colors high-contrast and the copy under 12 words per field."
    )

    source = "fallback"
    theme = fallback
    try:
        if provider is None:
            provider = llm.default_provider()
        raw = provider.generate(_SYSTEM, user_prompt)
        parsed = json.loads(_strip_fences(raw))
        if _is_valid_theme(parsed):
            theme = parsed
            source = "llm"
        else:
            log.warning("generate_shopify_theme: LLM returned invalid shape; using fallback")
    except Exception as exc:
        log.warning("generate_shopify_theme: LLM failed (%s); using fallback", exc)

    ctx["shopify_theme"] = theme
    ctx["shopify_theme_generation"] = {"ok": True, "source": source}
    return ctx
