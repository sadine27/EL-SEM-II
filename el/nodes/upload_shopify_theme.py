"""SP5b — apply theme settings to the configured Shopify dev store.

Renders a single Liquid snippet (`snippets/el-story.liquid`) with the theme
fields pre-substituted, and PUTs it onto the main theme. Operators reference
it from their theme with `{% render 'el-story' %}`.
"""
from __future__ import annotations

import html

from el import shopify
from el.logger import get_logger

log = get_logger(__name__)

SNIPPET_KEY = "snippets/el-story.liquid"


def _safe(value: str) -> str:
    return html.escape(str(value or ""), quote=True)


def _render_snippet(theme: dict) -> str:
    palette = theme.get("palette") or {}
    fonts = theme.get("fonts") or {}
    hero = theme.get("hero") or {}
    story_html = theme.get("story_html") or ""
    return (
        f'<section class="el-story" '
        f'style="background:{_safe(palette.get("bg","#ffffff"))};'
        f'color:{_safe(palette.get("text","#111827"))};'
        f'padding:48px 24px;text-align:center">'
        f'<h2 style="font-family:{_safe(fonts.get("heading","sans-serif"))};'
        f'color:{_safe(palette.get("primary","#111827"))};margin:0 0 12px">'
        f"{_safe(hero.get('headline',''))}</h2>"
        f'<p style="font-family:{_safe(fonts.get("body","sans-serif"))};'
        f'color:{_safe(palette.get("secondary","#374151"))};margin:0 0 24px">'
        f"{_safe(hero.get('subhead',''))}</p>"
        f'<a href="/collections/all" '
        f'style="background:{_safe(palette.get("accent","#f59e0b"))};'
        f'color:#fff;padding:12px 20px;display:inline-block;text-decoration:none;border-radius:6px">'
        f"{_safe(hero.get('cta','Shop now'))}</a>"
        f'<div style="margin-top:24px;font-family:{_safe(fonts.get("body","sans-serif"))}">'
        f"{story_html}</div>"
        f"</section>"
    )


def run(ctx: dict, *, provider: shopify.ShopifyAdminProvider | None = None) -> dict:
    theme = ctx.get("shopify_theme") or {}
    if not theme:
        ctx["shopify_theme_result"] = {"ok": False, "error": "no shopify_theme in ctx"}
        log.warning("upload_shopify_theme: no theme — skipping")
        return ctx

    try:
        if provider is None:
            provider = shopify.default_provider()
        theme_id = ctx.get("shopify_theme_id") or provider.get_main_theme_id()
        if not theme_id:
            raise shopify.ShopifyError("no main theme found")
        snippet = _render_snippet(theme)
        provider.update_theme_asset(int(theme_id), SNIPPET_KEY, snippet)
        ctx["shopify_theme_result"] = {
            "ok": True,
            "theme_id": int(theme_id),
            "asset_keys": [SNIPPET_KEY],
        }
        log.info("upload_shopify_theme: applied to theme %s", theme_id)
    except Exception as exc:
        ctx["shopify_theme_result"] = {"ok": False, "error": str(exc)}
        ctx.setdefault("formatted_error", []).append(
            {"text": f"upload_shopify_theme failed: {exc}"}
        )
        log.exception("upload_shopify_theme: failed")
    return ctx
