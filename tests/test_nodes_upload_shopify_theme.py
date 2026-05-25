"""Tests for el/nodes/upload_shopify_theme.py."""
from __future__ import annotations

import json

from el.nodes import upload_shopify_theme


class FakeShopify:
    def __init__(
        self,
        *,
        main_id: int | None = 5,
        raise_on_asset: bool = False,
        assets: dict[str, str] | None = None,
    ):
        self.main_id = main_id
        self.raise_on_asset = raise_on_asset
        self.assets = assets or {}
        self.get_asset_calls: list[tuple[int, str]] = []
        self.asset_calls: list[tuple[int, str, str]] = []

    def get_main_theme_id(self):
        return self.main_id

    def get_theme_asset(self, theme_id, key):
        self.get_asset_calls.append((theme_id, key))
        if key in self.assets:
            return {"key": key, "value": self.assets[key]}
        return {}

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


def _uploads_by_key(shop: FakeShopify) -> dict[str, str]:
    return {key: value for _, key, value in shop.asset_calls}


def test_happy_path_uploads_only_guarded_assets():
    ctx = {"shopify_theme": THEME}
    shop = FakeShopify()
    upload_shopify_theme.run(ctx, provider=shop)
    assert ctx["shopify_theme_result"]["ok"] is True
    assert ctx["shopify_theme_result"]["theme_id"] == 5
    assert ctx["shopify_theme_result"]["asset_keys"] == [
        "assets/tokens.css",
        "templates/index.json",
    ]
    assert len(shop.asset_calls) == 2
    assert len(shop.get_asset_calls) == 2
    assert ctx["shopify_theme_backup"] == {}
    assert set(_uploads_by_key(shop)) == {"assets/tokens.css", "templates/index.json"}
    assert "snippets/el-story.liquid" not in _uploads_by_key(shop)


def test_explicit_theme_id_overrides_main_lookup():
    ctx = {"shopify_theme": THEME, "shopify_theme_id": 99}
    shop = FakeShopify(main_id=5)
    upload_shopify_theme.run(ctx, provider=shop)
    assert ctx["shopify_theme_result"]["theme_id"] == 99
    assert shop.asset_calls[0][0] == 99
    assert shop.asset_calls[1][0] == 99


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


def test_old_schema_maps_to_tokens_and_index_json():
    ctx = {"shopify_theme": THEME}
    shop = FakeShopify()
    upload_shopify_theme.run(ctx, provider=shop)
    uploads = _uploads_by_key(shop)
    tokens = uploads["assets/tokens.css"]
    index = json.loads(uploads["templates/index.json"])

    assert "--el-accent: #f59e0b;" in tokens
    assert "--el-font-heading: Inter;" in tokens
    assert index["sections"]["hero"]["type"] == "hero-shell"
    assert index["sections"]["hero"]["settings"]["headline"] == "Hi"
    assert index["sections"]["hero"]["settings"]["cta_label"] == "Go"
    assert index["sections"]["promo"]["settings"]["body"] == "story"


def test_section_whitelist_ignores_unknown_injected_sections():
    theme = {
        "version": 1,
        "brand": {"name": "Safe Shop"},
        "tokens": {"colors": {}, "fonts": {}, "style": {}},
        "homepage": {
            "sections": {
                "hero": {"headline": "Safe"},
                "evil": {"enabled": True, "type": "main-cart-items", "settings": {"liquid": "{{ bad }}"}},
            },
            "order": ["evil", "hero"],
        },
    }
    ctx = {"shopify_theme": theme}
    shop = FakeShopify()
    upload_shopify_theme.run(ctx, provider=shop)
    index = json.loads(_uploads_by_key(shop)["templates/index.json"])
    section_types = [section["type"] for section in index["sections"].values()]

    assert "evil" not in index["sections"]
    assert "main-cart-items" not in section_types
    assert all(t in {
        "hero-shell",
        "featured-collections-shell",
        "product-grid-shell",
        "promo-shell",
        "footer-shell",
    } for t in section_types)
    assert index["order"][0] == "hero"


def test_asset_path_restrictions_are_hardcoded():
    ctx = {"shopify_theme": {
        "version": 1,
        "tokens": {},
        "homepage": {
            "asset_key": "layout/theme.liquid",
            "sections": {"hero": {"headline": "Hi"}},
            "order": ["hero"],
        },
    }}
    shop = FakeShopify()
    upload_shopify_theme.run(ctx, provider=shop)
    assert set(_uploads_by_key(shop)) == {"assets/tokens.css", "templates/index.json"}


def test_invalid_values_fall_back_safely():
    bad = {
        "version": 1,
        "brand": {"name": "<b>Bad</b>"},
        "tokens": {
            "colors": {"primary": '"><script>x</script>', "accent": "red; background:url(x)"},
            "fonts": {"heading": "Inter; color:red", "body": "Body\nFont"},
            "style": {"radius": "999px", "density": "wild"},
        },
        "homepage": {
            "sections": {
                "hero": {
                    "headline": "<script>x</script>Lift",
                    "cta_link": "javascript:alert(1)",
                    "image_style": "raw-liquid",
                },
                "product_grid": {"product_limit": 999, "collection_handle": "All Products!!"},
            },
            "order": ["hero", "product_grid"],
        },
    }
    ctx = {"shopify_theme": bad}
    shop = FakeShopify()
    upload_shopify_theme.run(ctx, provider=shop)
    uploads = _uploads_by_key(shop)
    tokens = uploads["assets/tokens.css"]
    index = json.loads(uploads["templates/index.json"])

    assert "--el-primary: #111827;" in tokens
    assert "--el-accent: #f59e0b;" in tokens
    assert "--el-font-heading: Inter, sans-serif;" in tokens
    assert "--el-density: comfortable;" in tokens
    assert index["sections"]["hero"]["settings"]["headline"] == "Lift"
    assert index["sections"]["hero"]["settings"]["cta_link"] == "/collections/all"
    assert index["sections"]["hero"]["settings"]["image_style"] == "product-focused"
    assert index["sections"]["product_grid"]["settings"]["product_limit"] == 24
    assert index["sections"]["product_grid"]["settings"]["collection_handle"] == "allproducts"


def test_backup_populated_on_first_overwrite():
    ctx = {"shopify_theme": THEME}
    shop = FakeShopify(assets={"assets/tokens.css": "old tokens"})

    upload_shopify_theme.run(ctx, provider=shop)

    assert ctx["shopify_theme_result"]["ok"] is True
    assert ctx["shopify_theme_backup"] == {"assets/tokens.css": "old tokens"}
    assert _uploads_by_key(shop)["assets/tokens.css"] != "old tokens"


def test_no_op_when_content_unchanged():
    rendered_tokens = upload_shopify_theme._render_tokens_css(THEME)
    rendered_index = upload_shopify_theme._render_index_json(THEME)
    ctx = {"shopify_theme": THEME}
    shop = FakeShopify(
        assets={
            "assets/tokens.css": rendered_tokens,
            "templates/index.json": rendered_index,
        }
    )

    upload_shopify_theme.run(ctx, provider=shop)

    assert ctx["shopify_theme_result"]["ok"] is True
    assert ctx["shopify_theme_backup"] == {
        "assets/tokens.css": rendered_tokens,
        "templates/index.json": rendered_index,
    }
    assert shop.asset_calls == []


def test_backup_empty_when_asset_is_new():
    ctx = {"shopify_theme": THEME}
    shop = FakeShopify()

    upload_shopify_theme.run(ctx, provider=shop)

    assert ctx["shopify_theme_result"]["ok"] is True
    assert ctx["shopify_theme_backup"] == {}
    assert len(shop.asset_calls) == 2
