"""Sentinel Engine — Forge-side product vetting gate.

Forge (``supplier_search``) finds candidate supplier products per trend and
writes them to ``ctx["supplier_matches"]``. Sentinel reads that output, runs each
candidate through a quality / profitability / delivery / risk gate, and writes the
vetted result to ``ctx["sentinel_matches"]`` — **without mutating** Forge's
original list.

Sentinel is a *preview* gate in v1: nothing downstream (HIL, Shopify,
``phase4_candidate_selection``) consumes ``sentinel_matches`` yet, so the node is
side-effect-free and needs no credentials.

Decision model (per candidate):
  * **Hard reject** — any one ⇒ ``reject``: missing title, missing product URL,
    explicit out-of-stock (``stock == 0``), projected margin below
    ``EL_SENTINEL_MIN_MARGIN_PCT``, shipping max above
    ``EL_SENTINEL_MAX_SHIPPING_DAYS``, and — *only* when
    ``EL_SENTINEL_BLOCK_IP_RISK=true`` — IP-risk terms.
  * **Soft warning** — never flips the decision on its own: missing image,
    unknown stock, unknown shipping, unknown rating, IP-risk terms (default).
  * **Soft score floor** — a candidate that clears every hard gate but scores
    below ``EL_SENTINEL_MIN_SCORE`` is rejected with reason ``low_sentinel_score``.

Margin model (deliberately *not* circular). ``landed_cost = cost + shipping``.
The sell price is a **market reference** price whenever one is known — a per-match
``price_ceiling``/``market_price``/``suggested_retail``, the trend's
``market_price``, or ``EL_SENTINEL_DEFAULT_MARKET_PRICE``. Only then can margin
actually fall, so an over-priced supplier measured against a fixed market price
fails the gate. Absent any reference we fall back to ``landed * TARGET_MARKUP``;
margin is then the constant ``1 − 1/markup`` and the gate is informational rather
than a reject driver (a markup multiple can never make its own margin look bad).

Each vetted match carries the original Forge fields plus: ``sentinel_score``,
``sentinel_decision`` (``pass``/``reject``), ``sentinel_warnings``,
``sentinel_rejection_reasons``, ``projected_sell_price``, ``projected_margin_pct``.
"""
from __future__ import annotations

import re
from typing import Any

from el import config
from el.logger import get_logger
from el.supabase import SupabaseRestProvider

# Sentinel telemetry table (created by migration, Item 3.5)
SENTINEL_LOG_TABLE = "sentinel_log"
SENTINEL_LOG_SCHEMA = "private"

log = get_logger(__name__)

# Term -> appears as a whole word in the product title/topic. Default behaviour is
# to *warn*, not block: the engine's flagship niche is sports-team fan merch
# ("RCB jersey"), so hard-blocking IP-risk by default would gut the headline use
# case. Set EL_SENTINEL_BLOCK_IP_RISK=true to turn these into hard rejects.
_IP_RISK_TERMS = ("team", "celebrity", "movie", "anime", "game", "character")

_DEFAULTS = {
    "EL_SENTINEL_ENABLED": "true",
    "EL_SENTINEL_MIN_SCORE": "0.62",
    "EL_SENTINEL_TARGET_MARKUP": "2.2",
    "EL_SENTINEL_MIN_MARGIN_PCT": "0.30",
    "EL_SENTINEL_MAX_SHIPPING_DAYS": "21",
    "EL_SENTINEL_TOP_MATCHES_PER_TREND": "3",
    "EL_SENTINEL_BLOCK_IP_RISK": "false",
    "EL_SENTINEL_DEFAULT_MARKET_PRICE": "",
}


# --------------------------------------------------------------------------- #
# config parsing (config.get returns raw strings only — no bool/float helpers) #
# --------------------------------------------------------------------------- #
def _truthy(raw: str | None) -> bool:
    return (raw or "").strip().lower() in {"1", "true", "yes", "on"}


def _bool_config(name: str) -> bool:
    return _truthy(config.get(name, _DEFAULTS.get(name)))


def _float_config(name: str, *, minimum: float | None = None) -> float | None:
    raw = config.get(name, _DEFAULTS.get(name))
    if raw is None or not str(raw).strip():
        return None
    try:
        val = float(str(raw).strip())
    except (TypeError, ValueError):
        return None
    if minimum is not None:
        val = max(minimum, val)
    return val


def _int_config(name: str, *, minimum: int = 0) -> int:
    raw = config.get(name, _DEFAULTS.get(name))
    try:
        return max(minimum, int(str(raw).strip()))
    except (TypeError, ValueError):
        return max(minimum, int(_DEFAULTS[name]))


def _coerce_float(value) -> float | None:
    try:
        if value is None or (isinstance(value, str) and not value.strip()):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _load_config() -> dict:
    """Snapshot the env once per run so every match is vetted with the same rules."""
    return {
        "min_score": _float_config("EL_SENTINEL_MIN_SCORE", minimum=0.0) or 0.0,
        "markup": _float_config("EL_SENTINEL_TARGET_MARKUP", minimum=1.0) or 1.0,
        "min_margin": _float_config("EL_SENTINEL_MIN_MARGIN_PCT", minimum=0.0) or 0.0,
        "max_ship_days": _int_config("EL_SENTINEL_MAX_SHIPPING_DAYS", minimum=0),
        "top_per_trend": _int_config("EL_SENTINEL_TOP_MATCHES_PER_TREND", minimum=1),
        "block_ip_risk": _bool_config("EL_SENTINEL_BLOCK_IP_RISK"),
        "default_market_price": _float_config("EL_SENTINEL_DEFAULT_MARKET_PRICE", minimum=0.0),
    }


# --------------------------------------------------------------------------- #
# field helpers                                                               #
# --------------------------------------------------------------------------- #
def _landed_cost(match: dict) -> float | None:
    landed = _coerce_float(match.get("landed_cost"))
    if landed is not None:
        return landed
    cost = _coerce_float(match.get("cost"))
    if cost is None:
        return None
    return cost + (_coerce_float(match.get("shipping_cost")) or 0.0)


def _resolve_sell_price(match: dict, trend: dict, landed: float | None, cfg: dict) -> tuple[float | None, str]:
    """Return (sell_price, basis) where basis is 'market', 'markup', or 'unknown'.

    A real market reference makes the margin gate meaningful; the markup fallback
    is informational only (see module docstring).
    """
    for key in ("price_ceiling", "market_price", "suggested_retail"):
        val = _coerce_float(match.get(key))
        if val and val > 0:
            return val, "market"
    raw = match.get("raw_payload")
    if isinstance(raw, dict):
        for key in ("price_ceiling", "market_price", "suggested_retail"):
            val = _coerce_float(raw.get(key))
            if val and val > 0:
                return val, "market"
    if isinstance(trend, dict):
        for key in ("market_price", "price_ceiling"):
            val = _coerce_float(trend.get(key))
            if val and val > 0:
                return val, "market"
    if cfg["default_market_price"] and cfg["default_market_price"] > 0:
        return cfg["default_market_price"], "market"
    if landed is not None:
        return round(landed * cfg["markup"], 2), "markup"
    return None, "unknown"


def _ip_risk_term(*texts: str | None) -> str | None:
    tokens = set(re.findall(r"[a-z0-9]+", " ".join(t for t in texts if t).lower()))
    for term in _IP_RISK_TERMS:
        if term in tokens:
            return term
    return None


def _delivery_days(match: dict) -> int | None:
    days_max = match.get("shipping_days_max")
    days_min = match.get("shipping_days_min")
    days = days_max if days_max is not None else days_min
    try:
        return int(days) if days is not None else None
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------------- #
# scoring                                                                     #
# --------------------------------------------------------------------------- #
def _sentinel_score(match: dict, margin_pct: float | None, ip_flagged: bool) -> float:
    """Blend Forge relevance with margin / delivery / stock / image / rating health.

    Positive weights sum to 1.0; an IP-risk hit applies a small flat penalty. The
    result is the soft-quality floor compared against ``EL_SENTINEL_MIN_SCORE``.
    """
    relevance = _coerce_float(match.get("match_score"))
    relevance = max(0.0, min(1.0, relevance)) if relevance is not None else 0.5

    if margin_pct is None:
        margin_health = 0.5
    else:
        margin_health = max(0.0, min(1.0, margin_pct / 0.6))

    days = _delivery_days(match)
    delivery = 0.4 if days is None else 1.0 / (1.0 + max(0, days) / 10.0)

    stock = match.get("stock")
    if stock is None:
        stock_score = 0.5
    else:
        stock_score = 1.0 if _coerce_float(stock) and _coerce_float(stock) > 0 else 0.0

    image_score = 1.0 if match.get("image_url") else 0.0

    rating = _coerce_float(match.get("rating"))
    rating_score = 0.5 if rating is None else max(0.0, min(1.0, rating / 5.0))

    score = (
        relevance * 0.30
        + margin_health * 0.25
        + delivery * 0.15
        + stock_score * 0.10
        + image_score * 0.08
        + rating_score * 0.12
    )
    if ip_flagged:
        score -= 0.10
    return round(max(0.0, min(1.0, score)), 4)


# --------------------------------------------------------------------------- #
# per-match vetting                                                           #
# --------------------------------------------------------------------------- #
def _vet_match(match: dict, trend: dict, cfg: dict) -> dict:
    warnings: list[str] = []
    reasons: list[str] = []

    title = (match.get("title") or "").strip()
    product_url = (match.get("product_url") or "").strip()
    landed = _landed_cost(match)
    sell_price, basis = _resolve_sell_price(match, trend, landed, cfg)

    margin_pct: float | None = None
    if sell_price is not None and sell_price > 0 and landed is not None:
        margin_pct = round((sell_price - landed) / sell_price, 4)

    ip_term = _ip_risk_term(title, (trend or {}).get("topic"))

    # ---- hard gates --------------------------------------------------------
    if not title:
        reasons.append("missing_title")
    if not product_url:
        reasons.append("missing_product_url")
    if match.get("stock") == 0:
        reasons.append("out_of_stock")
    if margin_pct is not None and margin_pct < cfg["min_margin"]:
        reasons.append(f"low_margin:{margin_pct:.2f}<{cfg['min_margin']:.2f}")
    days_max = match.get("shipping_days_max")
    if days_max is not None:
        try:
            if int(days_max) > cfg["max_ship_days"]:
                reasons.append(f"slow_shipping:{int(days_max)}>{cfg['max_ship_days']}")
        except (TypeError, ValueError):
            pass
    if ip_term and cfg["block_ip_risk"]:
        reasons.append(f"ip_risk:{ip_term}")

    # ---- soft warnings -----------------------------------------------------
    if not match.get("image_url"):
        warnings.append("missing_image")
    if match.get("stock") is None:
        warnings.append("unknown_stock")
    if match.get("shipping_days_min") is None and match.get("shipping_days_max") is None:
        warnings.append("unknown_shipping")
    if _coerce_float(match.get("rating")) is None:
        warnings.append("unknown_rating")
    if landed is None:
        warnings.append("unknown_cost")
    if basis == "markup":
        warnings.append("margin_estimated_from_markup")
    if ip_term and not cfg["block_ip_risk"]:
        warnings.append(f"ip_risk:{ip_term}")

    score = _sentinel_score(match, margin_pct, bool(ip_term))

    # ---- soft score floor (only when no hard reason already fired) ---------
    if not reasons and score < cfg["min_score"]:
        reasons.append(f"low_sentinel_score:{score:.2f}<{cfg['min_score']:.2f}")

    vetted = dict(match)  # copy: never mutate Forge's original payload
    vetted.update(
        sentinel_score=score,
        sentinel_decision="reject" if reasons else "pass",
        sentinel_warnings=warnings,
        sentinel_rejection_reasons=reasons,
        projected_sell_price=sell_price,
        projected_margin_pct=margin_pct,
    )
    return vetted


def _passthrough(match: dict) -> dict:
    vetted = dict(match)
    vetted.update(
        sentinel_score=None,
        sentinel_decision="skipped",
        sentinel_warnings=[],
        sentinel_rejection_reasons=[],
        projected_sell_price=None,
        projected_margin_pct=None,
    )
    return vetted


# --------------------------------------------------------------------------- #
# Sentinel telemetry logging (Item 3.5)                                       #
# --------------------------------------------------------------------------- #
def _log_sentinel_decisions(
    groups: list[dict],
    sentinel_matches: list[dict],
    db: SupabaseRestProvider | None = None,
) -> None:
    """Log every vetting pass/reject to private.sentinel_log for SP7 tuning.

    When both *db* and *SUPABASE_URL* env are unavailable the function is a
    silent no-op — tests don't need Supabase credentials.
    """
    if db is None:
        try:
            from el import config as _cfg
            if not _cfg.get("SUPABASE_URL"):
                return  # no Supabase available — skip silently (e.g. unit tests)
            db = SupabaseRestProvider()
        except Exception:
            return  # graceful skip when env isn't set
    provider = db
    log_rows: list[dict[str, Any]] = []

    for group in groups:
        trend = group.get("trend") or {}
        query = (group.get("query") or "").strip()
        trend_topic = (trend.get("topic") or query) if isinstance(trend, dict) else query
        trend_rank = int(trend.get("rank") or 0) if isinstance(trend, dict) else None

        for match in group.get("matches") or []:
            vetted = _vet_match(match, trend, _load_config())
            decision = vetted.get("sentinel_decision", "skipped")
            if decision == "skipped":
                continue
            log_rows.append({
                "query": query,
                "trend_topic": trend_topic,
                "trend_rank": trend_rank,
                "product_title": (match.get("title") or "").strip(),
                "source_id": (match.get("source_id") or "").strip(),
                "sentinel_decision": decision,
                "sentinel_score": vetted.get("sentinel_score"),
                "rejection_reasons": vetted.get("sentinel_rejection_reasons") or [],
                "warnings": vetted.get("sentinel_warnings") or [],
                "projected_margin_pct": vetted.get("projected_margin_pct"),
                "landed_cost": match.get("landed_cost") or match.get("cost"),
                "shipping_days_max": match.get("shipping_days_max"),
                "match_score": match.get("match_score"),
                "pipeline_run_id": None,  # caller can patch if available
            })

    if log_rows:
        try:
            provider.insert_rows(
                schema=SENTINEL_LOG_SCHEMA,
                table=SENTINEL_LOG_TABLE,
                rows=log_rows,
            )
            log.info("sentinel_telemetry: logged %d decisions", len(log_rows))
        except Exception:
            log.exception("sentinel_telemetry: failed to log decisions (non-fatal)")


def run(
    ctx: dict,
    *,
    db: SupabaseRestProvider | None = None,
) -> dict:
    """Vet ``ctx["supplier_matches"]`` into ``ctx["sentinel_matches"]``.


    Output mirrors Forge's grouped shape so the CLI printer and any future
    consumer can reuse the same iteration. Each group gains a ``rejected`` list
    (untruncated, for transparency) and a ``summary`` of counts; ``matches`` holds
    the passing candidates sorted by ``sentinel_score`` and capped at
    ``EL_SENTINEL_TOP_MATCHES_PER_TREND``.
    """
    groups = ctx.get("supplier_matches") or []

    if not _bool_config("EL_SENTINEL_ENABLED"):
        log.info("sentinel_vetting: disabled (EL_SENTINEL_ENABLED) — passing Forge matches through")
        ctx["sentinel_matches"] = [
            {
                "trend": group.get("trend"),
                "query": group.get("query"),
                "matches": [_passthrough(m) for m in group.get("matches", [])],
                "rejected": [],
                "summary": {"evaluated": len(group.get("matches", [])), "passed": 0, "rejected": 0, "skipped": len(group.get("matches", []))},
            }
            for group in groups
        ]
        return ctx

    cfg = _load_config()
    sentinel_matches: list[dict] = []
    total_eval = total_pass = total_reject = 0

    for group in groups:
        trend = group.get("trend") or {}
        vetted = [_vet_match(m, trend, cfg) for m in group.get("matches", [])]
        passed = [m for m in vetted if m["sentinel_decision"] == "pass"]
        rejected = [m for m in vetted if m["sentinel_decision"] == "reject"]
        passed.sort(key=lambda m: m["sentinel_score"] or 0.0, reverse=True)

        total_eval += len(vetted)
        total_pass += len(passed)
        total_reject += len(rejected)

        sentinel_matches.append({
            "trend": group.get("trend"),
            "query": group.get("query"),
            "matches": passed[: cfg["top_per_trend"]],
            "rejected": rejected,
            "summary": {"evaluated": len(vetted), "passed": len(passed), "rejected": len(rejected)},
        })

    ctx["sentinel_matches"] = sentinel_matches
    log.info(
        "sentinel_vetting: %d trend(s), %d evaluated → %d pass / %d reject",
        len(sentinel_matches), total_eval, total_pass, total_reject,
    )

    # Telemetry — log every decision to sentinel_log for SP7 (non-fatal on failure)
    _log_sentinel_decisions(groups, sentinel_matches, db=db)

    return ctx
