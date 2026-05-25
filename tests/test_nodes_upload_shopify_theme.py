"""Tests for el/nodes/upload_shopify_theme.py."""
from __future__ import annotations

from el.nodes import upload_shopify_theme


class FakeShopify:
    def __init__(self, *, main_id: int | None = 5, raise_on_asset: bool = False):
        self.main_id = main_id
        self.raise_on_asset = raise_on_asset
        self.asset_calls: list[tuple[int, str, str]] = []

    def get_main_theme_id(self):
        return self.main_id

    def update_theme_asset(self, theme_id, key, value):
        self.asset_calls.append((theme_id, key, value))
        if self.raise_on_asset:
            raise RuntimeError("PUT failed")
        return {"key": key, "value": value}


THEME = {
    "name": "X",
    "palette": {"primary": "#000", "secondary": "#111", "accent": "#f59e0b", "bg": "#fff", "text": "#222"},
    "fonts": {"heading": "Inter", "body": "Inter"},
    "hero": {"headline": "Hi", "subhead": "Sub", "cta": "Go"},
    "story_html": "<p>story</p>",
}


def test_happy_path_uploads_snippet():
    ctx = {"shopify_theme": THEME}
    shop = FakeShopify()
    upload_shopify_theme.run(ctx, provider=shop)
    assert ctx["shopify_theme_result"]["ok"] is True
    assert ctx["shopify_theme_result"]["theme_id"] == 5
    assert ctx["shopify_theme_result"]["asset_keys"] == ["snippets/el-story.liquid"]
    assert len(shop.asset_calls) == 1
    theme_id, key, value = shop.asset_calls[0]
    assert key == "snippets/el-story.liquid"
    assert "#f59e0b" in value
    assert "Hi" in value
    assert "<p>story</p>" in value


def test_explicit_theme_id_overrides_main_lookup():
    ctx = {"shopify_theme": THEME, "shopify_theme_id": 99}
    shop = FakeShopify(main_id=5)
    upload_shopify_theme.run(ctx, provider=shop)
    assert ctx["shopify_theme_result"]["theme_id"] == 99
    assert shop.asset_calls[0][0] == 99


def test_missing_theme_sets_result_not_ok():
    ctx = {}
    upload_shopify_theme.run(ctx, provider=FakeShopify())
    assert ctx["shopify_theme_result"]["ok"] is False
    assert "no shopify_theme" in ctx["shopify_theme_result"]["error"]


def test_asset_failure_sets_formatted_error():
    ctx = {"shopify_theme": THEME}
    upload_shopify_theme.run(ctx, provider=FakeShopify(raise_on_asset=True))
    assert ctx["shopify_theme_result"]["ok"] is False
    assert ctx["formatted_error"][0]["text"].startswith("upload_shopify_theme failed")


def test_no_main_theme_fails_gracefully():
    ctx = {"shopify_theme": THEME}
    upload_shopify_theme.run(ctx, provider=FakeShopify(main_id=None))
    assert ctx["shopify_theme_result"]["ok"] is False
    assert "no main theme" in ctx["shopify_theme_result"]["error"]


def test_html_escapes_dangerous_palette_values():
    bad = {**THEME, "palette": {**THEME["palette"], "primary": '"><script>x</script>'}}
    ctx = {"shopify_theme": bad}
    shop = FakeShopify()
    upload_shopify_theme.run(ctx, provider=shop)
    snippet = shop.asset_calls[0][2]
    assert "<script>" not in snippet
    assert "&lt;script&gt;" in snippet
