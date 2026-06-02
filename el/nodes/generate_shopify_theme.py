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
    "You are a conversion-focused e-commerce brand designer with deep expertise in "
    "color psychology. Reply with STRICT JSON only — no markdown, no commentary, no "
    "trailing commas. Keys: name (string), palette "
    "{primary,secondary,accent,bg,text — hex colors like #112233}, "
    "fonts {heading,body — CSS font-family strings}, "
    "hero {headline,subhead,cta — short strings under 10 words each}, "
    "story_html (one short HTML paragraph under 30 words). "
    "PALETTE RULES based on color psychology: "
    "(1) bg must NOT be pure white (#ffffff) — use warm cream, soft amber, or muted "
    "tones that feel inviting and premium; "
    "(2) accent must be bold and high-contrast — warm reds, corals, ambers, or deep "
    "teals drive click-through and urgency; "
    "(3) primary/text must have strong contrast against bg for readability (AA standard); "
    "(4) warm tones (amber, terracotta, coral) trigger desire and purchase intent; "
    "(5) deep navy or charcoal primary creates trust and authority. "
    "Apply these principles to the specific niche audience."
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
            "primary": "#1a1a2e",
            "secondary": "#16213e",
            "accent": "#e94560",    # coral-red — urgency and attention
            "bg": "#fdf6ec",        # warm cream — inviting, premium
            "text": "#1a1a2e",
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
        f"Design a high-converting storefront theme for trending products in: "
        f"{niche or 'a curated picks shop'}. "
        "Apply color psychology to maximise purchase intent and emotional appeal. "
        "The palette must use a warm, inviting bg (not pure white), a bold accent "
        "for CTAs, and clear readable text. Keep hero copy direct, under 10 words "
        "per field, and make it feel aspirational."
    )

    source = "fallback"
    theme = fallback
    try:
        if provider is None:
            provider = llm.default_provider()
        for attempt in range(2):
            try:
                raw = provider.generate(_SYSTEM, user_prompt)
                parsed = json.loads(_strip_fences(raw))
                if _is_valid_theme(parsed):
                    theme = parsed
                    source = "llm"
                    break
                log.warning(
                    "generate_shopify_theme: attempt %d returned invalid shape; retrying",
                    attempt + 1,
                )
            except json.JSONDecodeError as exc:
                log.warning(
                    "generate_shopify_theme: attempt %d JSON parse failed (%s); retrying",
                    attempt + 1, exc,
                )
    except Exception as exc:
        log.warning("generate_shopify_theme: LLM failed (%s); using fallback", exc)

    ctx["shopify_theme"] = theme
    ctx["shopify_theme_generation"] = {"ok": True, "source": source}
    return ctx
