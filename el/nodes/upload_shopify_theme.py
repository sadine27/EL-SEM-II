"""SP5b — apply guarded homepage theme settings to the Shopify dev store.

The AI never writes Liquid or chooses asset paths. This node maps structured
theme JSON into two approved assets owned by the Python renderer:
`assets/tokens.css` and `templates/index.json`.
"""
from __future__ import annotations

import html
import json
import re
from pathlib import Path

from el import shopify
from el.logger import get_logger

log = get_logger(__name__)

TOKENS_CSS_KEY = "assets/tokens.css"
INDEX_JSON_KEY = "templates/index.json"
ALLOWED_ASSET_KEYS = {TOKENS_CSS_KEY, INDEX_JSON_KEY}

SECTION_TYPE_BY_ID = {
    "hero": "hero-shell",
    "featured_collections": "featured-collections-shell",
    "product_grid": "product-grid-shell",
    "promo": "promo-shell",
    "footer": "footer-shell",
}
DEFAULT_SECTION_ORDER = [
    "hero",
    "featured_collections",
    "product_grid",
    "promo",
    "footer",
]

THEME_SHELL_SECTIONS_DIR = Path(__file__).resolve().parents[1] / "assets" / "theme_shells" / "sections"
TRUSTED_SHELL_ASSET_KEYS = {
    f"sections/{section_type}.liquid": THEME_SHELL_SECTIONS_DIR / f"{section_type}.liquid"
    for section_type in SECTION_TYPE_BY_ID.values()
}

_HEX_RE = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
_UNSAFE_FONT_RE = re.compile(r"[{}<>;\r\n]")
_SCRIPT_STYLE_RE = re.compile(r"<(script|style)\b[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")
_HANDLE_RE = re.compile(r"[^a-z0-9_-]+")
_SAFE_LINK_PREFIXES = ("/", "/collections/", "/products/", "/pages/")

DEFAULT_TOKENS = {
    "colors": {
        "bg": "#ffffff",
        "surface": "#f6f7f4",
        "text": "#111827",
        "muted": "#6b7280",
        "primary": "#111827",
        "secondary": "#374151",
        "accent": "#f59e0b",
    },
    "fonts": {
        "heading": "Inter, sans-serif",
        "body": "Inter, sans-serif",
    },
    "style": {
        "radius": "6px",
        "density": "comfortable",
    },
}


def _safe(value: str) -> str:
    return html.escape(str(value or ""), quote=True)


def _text(value, fallback: str = "", *, max_len: int = 160) -> str:
    s = html.unescape(str(value or fallback)).strip()
    s = _SCRIPT_STYLE_RE.sub("", s)
    s = _TAG_RE.sub("", s)
    s = re.sub(r"\s+", " ", s).strip()
    return (s or fallback)[:max_len]


def _hex(value, fallback: str) -> str:
    s = str(value or "").strip()
    return s if _HEX_RE.match(s) else fallback


def _font(value, fallback: str = "Inter, sans-serif") -> str:
    s = str(value or "").strip()
    if not s or _UNSAFE_FONT_RE.search(s):
        return fallback
    return s[:80]


def _link(value, fallback: str = "/collections/all") -> str:
    s = str(value or "").strip()
    if s == "/" or any(s.startswith(prefix) for prefix in _SAFE_LINK_PREFIXES[1:]):
        return s[:120]
    return fallback


def _handle(value, fallback: str = "all") -> str:
    s = str(value or fallback).strip().lower()
    s = _HANDLE_RE.sub("", s)
    return s or fallback


def _int_range(value, fallback: int, min_value: int, max_value: int) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        return fallback
    return min(max(n, min_value), max_value)


def _choice(value, allowed: set[str], fallback: str) -> str:
    s = str(value or "").strip()
    return s if s in allowed else fallback


def _normalize_theme(theme: dict) -> dict:
    if isinstance(theme.get("tokens"), dict) and isinstance(theme.get("homepage"), dict):
        return theme

    palette = theme.get("palette") or {}
    fonts = theme.get("fonts") or {}
    hero = theme.get("hero") or {}
    name = theme.get("name") or "EL Shop"
    story = _text(theme.get("story_html"), f"Curated picks from {name}.", max_len=240)
    return {
        "version": 1,
        "brand": {"name": name, "tagline": hero.get("subhead") or ""},
        "tokens": {
            "colors": {
                "bg": palette.get("bg"),
                "surface": palette.get("bg"),
                "text": palette.get("text"),
                "muted": palette.get("secondary"),
                "primary": palette.get("primary"),
                "secondary": palette.get("secondary"),
                "accent": palette.get("accent"),
            },
            "fonts": {
                "heading": fonts.get("heading"),
                "body": fonts.get("body"),
            },
            "style": {},
        },
        "homepage": {
            "sections": {
                "hero": {
                    "enabled": True,
                    "headline": hero.get("headline"),
                    "subhead": hero.get("subhead"),
                    "cta_label": hero.get("cta"),
                    "cta_link": "/collections/all",
                    "image_style": "product-focused",
                },
                "featured_collections": {"enabled": True},
                "product_grid": {"enabled": True},
                "promo": {
                    "enabled": True,
                    "eyebrow": "Why these picks",
                    "heading": "Curated for you",
                    "body": story,
                    "cta_label": hero.get("cta") or "Shop now",
                    "cta_link": "/collections/all",
                },
                "footer": {"enabled": True},
            },
            "order": DEFAULT_SECTION_ORDER,
        },
    }


def _render_tokens_css(theme: dict) -> str:
    normalized = _normalize_theme(theme)
    tokens = normalized.get("tokens") or {}
    colors = tokens.get("colors") or {}
    fonts = tokens.get("fonts") or {}
    style = tokens.get("style") or {}
    defaults = DEFAULT_TOKENS
    values = {
        "--el-bg": _hex(colors.get("bg"), defaults["colors"]["bg"]),
        "--el-surface": _hex(colors.get("surface"), defaults["colors"]["surface"]),
        "--el-text": _hex(colors.get("text"), defaults["colors"]["text"]),
        "--el-muted": _hex(colors.get("muted"), defaults["colors"]["muted"]),
        "--el-primary": _hex(colors.get("primary"), defaults["colors"]["primary"]),
        "--el-secondary": _hex(colors.get("secondary"), defaults["colors"]["secondary"]),
        "--el-accent": _hex(colors.get("accent"), defaults["colors"]["accent"]),
        "--el-font-heading": _font(fonts.get("heading"), defaults["fonts"]["heading"]),
        "--el-font-body": _font(fonts.get("body"), defaults["fonts"]["body"]),
        "--el-radius": _choice(str(style.get("radius") or ""), {"0px", "4px", "6px", "8px", "12px"}, defaults["style"]["radius"]),
        "--el-density": _choice(style.get("density"), {"compact", "comfortable", "spacious"}, defaults["style"]["density"]),
    }
    lines = [":root {"]
    lines.extend(f"  {name}: {value};" for name, value in values.items())
    lines.append("}")
    return "\n".join(lines) + "\n"


def _collections_settings(raw: dict) -> dict:
    collections = raw.get("collections") if isinstance(raw.get("collections"), list) else []
    out = {}
    for i in range(3):
        item = collections[i] if i < len(collections) and isinstance(collections[i], dict) else {}
        n = i + 1
        out[f"collection_{n}_title"] = _text(item.get("title"), f"Collection {n}", max_len=60)
        out[f"collection_{n}_handle"] = _handle(item.get("handle"), "all")
    return out


def _section_settings(section_id: str, normalized: dict) -> dict:
    brand = normalized.get("brand") or {}
    sections = (normalized.get("homepage") or {}).get("sections") or {}
    raw = sections.get(section_id) if isinstance(sections.get(section_id), dict) else {}
    brand_name = _text(brand.get("name"), "EL Shop", max_len=80)
    if section_id == "hero":
        return {
            "brand_name": brand_name,
            "headline": _text(raw.get("headline"), f"Shop {brand_name}", max_len=90),
            "subhead": _text(raw.get("subhead"), "Curated picks, hand-reviewed.", max_len=140),
            "cta_label": _text(raw.get("cta_label"), "Shop now", max_len=40),
            "cta_link": _link(raw.get("cta_link")),
            "image_style": _choice(raw.get("image_style"), {"product-focused", "lifestyle", "minimal"}, "product-focused"),
        }
    if section_id == "featured_collections":
        return {
            "heading": _text(raw.get("heading"), "Shop by routine", max_len=80),
            "subhead": _text(raw.get("subhead"), "Simple collections for how you shop.", max_len=140),
            **_collections_settings(raw),
        }
    if section_id == "product_grid":
        return {
            "heading": _text(raw.get("heading"), "Current picks", max_len=80),
            "subhead": _text(raw.get("subhead"), "Curated products ready to browse.", max_len=140),
            "collection_handle": _handle(raw.get("collection_handle"), "all"),
            "product_limit": _int_range(raw.get("product_limit"), 8, 1, 24),
        }
    if section_id == "promo":
        return {
            "eyebrow": _text(raw.get("eyebrow"), "Why these picks", max_len=40),
            "heading": _text(raw.get("heading"), "Curated for daily use", max_len=80),
            "body": _text(raw.get("body"), "Each item is selected for practical everyday value.", max_len=240),
            "cta_label": _text(raw.get("cta_label"), "Browse all", max_len=40),
            "cta_link": _link(raw.get("cta_link")),
        }
    return {
        "heading": _text(raw.get("heading"), brand_name, max_len=80),
        "body": _text(raw.get("body"), "Focused products for everyday use.", max_len=180),
        "link_1_label": _text(raw.get("link_1_label"), "Catalog", max_len=40),
        "link_1_url": _link(raw.get("link_1_url")),
        "link_2_label": _text(raw.get("link_2_label"), "Contact", max_len=40),
        "link_2_url": _link(raw.get("link_2_url"), "/pages/contact"),
    }


def _safe_section_order(normalized: dict, sections: dict) -> list[str]:
    homepage = normalized.get("homepage") or {}
    requested = homepage.get("order") if isinstance(homepage.get("order"), list) else []
    order = [sid for sid in requested if sid in SECTION_TYPE_BY_ID and sid in sections]
    order.extend(sid for sid in DEFAULT_SECTION_ORDER if sid in sections and sid not in order)
    return order or [sid for sid in DEFAULT_SECTION_ORDER if sid in sections]


def _render_index_json(theme: dict) -> str:
    normalized = _normalize_theme(theme)
    raw_sections = (normalized.get("homepage") or {}).get("sections") or {}
    sections = {}
    for section_id in DEFAULT_SECTION_ORDER:
        raw = raw_sections.get(section_id)
        if isinstance(raw, dict) and raw.get("enabled") is False:
            continue
        sections[section_id] = {
            "type": SECTION_TYPE_BY_ID[section_id],
            "settings": _section_settings(section_id, normalized),
        }
    if not sections:
        sections = {
            section_id: {
                "type": SECTION_TYPE_BY_ID[section_id],
                "settings": _section_settings(section_id, normalized),
            }
            for section_id in DEFAULT_SECTION_ORDER
        }
    payload = {"sections": sections, "order": _safe_section_order(normalized, sections)}
    return json.dumps(payload, indent=2) + "\n"


def _trusted_shell_uploads() -> dict[str, str]:
    return {key: path.read_text(encoding="utf-8") for key, path in TRUSTED_SHELL_ASSET_KEYS.items()}


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
        shell_uploads = _trusted_shell_uploads()
        for key, value in shell_uploads.items():
            if key not in TRUSTED_SHELL_ASSET_KEYS:
                raise shopify.ShopifyError(f"disallowed theme shell asset key: {key}")
            current = provider.get_theme_asset(int(theme_id), key)
            if isinstance(current, dict) and current.get("value") is not None:
                continue
            provider.update_theme_asset(int(theme_id), key, value)
        uploads = {
            TOKENS_CSS_KEY: _render_tokens_css(theme),
            INDEX_JSON_KEY: _render_index_json(theme),
        }
        backup = {}
        ctx["shopify_theme_backup"] = backup
        for key, value in uploads.items():
            if key not in ALLOWED_ASSET_KEYS:
                raise shopify.ShopifyError(f"disallowed theme asset key: {key}")
            current = provider.get_theme_asset(int(theme_id), key)
            prior_value = current.get("value") if isinstance(current, dict) else None
            if prior_value is not None:
                backup[key] = prior_value
            if value == prior_value:
                log.info("upload_shopify_theme: no-op, asset unchanged")
                continue
            provider.update_theme_asset(int(theme_id), key, value)
        ctx["shopify_theme_result"] = {
            "ok": True,
            "theme_id": int(theme_id),
            "asset_keys": list(uploads.keys()),
        }
        log.info("upload_shopify_theme: applied to theme %s", theme_id)
    except Exception as exc:
        ctx["shopify_theme_result"] = {"ok": False, "error": str(exc)}
        ctx.setdefault("formatted_error", []).append(
            {"text": f"upload_shopify_theme failed: {exc}"}
        )
        log.exception("upload_shopify_theme: failed")
    return ctx
