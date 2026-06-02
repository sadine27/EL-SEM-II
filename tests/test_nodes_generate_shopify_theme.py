"""Tests for el/nodes/generate_shopify_theme.py."""
from __future__ import annotations

import json

from el.nodes import generate_shopify_theme


VALID_THEME = {
    "name": "Yoga Shop",
    "palette": {"primary": "#000", "secondary": "#111", "accent": "#f59e0b", "bg": "#fff", "text": "#222"},
    "fonts": {"heading": "Inter", "body": "Inter"},
    "hero": {"headline": "h", "subhead": "s", "cta": "c"},
    "story_html": "<p>x</p>",
}


class FakeLLM:
    def __init__(self, *, reply: str | None = None, raise_exc: bool = False):
        self.reply = reply
        self.raise_exc = raise_exc

    def generate(self, system, user):
        if self.raise_exc:
            raise RuntimeError("vertex down")
        return self.reply or ""


def test_llm_happy_path_sets_theme_from_llm():
    ctx = {"niche": "yoga mats"}
    llm = FakeLLM(reply=json.dumps(VALID_THEME))
    generate_shopify_theme.run(ctx, provider=llm)
    assert ctx["shopify_theme"]["name"] == "Yoga Shop"
    assert ctx["shopify_theme_generation"]["source"] == "llm"


def test_llm_strips_markdown_fences():
    ctx = {"niche": "yoga mats"}
    fenced = "```json\n" + json.dumps(VALID_THEME) + "\n```"
    generate_shopify_theme.run(ctx, provider=FakeLLM(reply=fenced))
    assert ctx["shopify_theme_generation"]["source"] == "llm"
    assert ctx["shopify_theme"]["name"] == "Yoga Shop"


def test_llm_raise_falls_back():
    ctx = {"niche": "yoga"}
    generate_shopify_theme.run(ctx, provider=FakeLLM(raise_exc=True))
    assert ctx["shopify_theme_generation"]["source"] == "fallback"
    assert ctx["shopify_theme"]["name"] == "yoga Shop"
    assert ctx["shopify_theme"]["palette"]["primary"].startswith("#")


def test_llm_non_json_falls_back():
    ctx = {"niche": "earbuds"}
    generate_shopify_theme.run(ctx, provider=FakeLLM(reply="not json at all"))
    assert ctx["shopify_theme_generation"]["source"] == "fallback"
    assert "earbuds" in ctx["shopify_theme"]["name"]


def test_llm_invalid_shape_falls_back():
    ctx = {"niche": "candles"}
    generate_shopify_theme.run(ctx, provider=FakeLLM(reply=json.dumps({"name": "X"})))
    assert ctx["shopify_theme_generation"]["source"] == "fallback"


def test_no_niche_uses_default_label():
    ctx = {}
    generate_shopify_theme.run(ctx, provider=FakeLLM(raise_exc=True))
    assert ctx["shopify_theme"]["name"] == "EL Shop"
