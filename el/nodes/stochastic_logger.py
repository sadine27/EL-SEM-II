"""SP1 telemetry node — slate-level ε-greedy sampler + propensity logging.

Pure helpers (compute_marginal_propensity, sample_slate) are stateless and
seedable for testing. The run(ctx) entry point is added in Task 4.

Spec: docs/superpowers/specs/2026-05-10-sp1-telemetry-foundation-design.md
"""
from __future__ import annotations

import random
import uuid
from typing import Literal

from el import config, supabase
from el.logger import get_logger

log = get_logger(__name__)

Branch = Literal["greedy", "explore", "degenerate"]


def compute_marginal_propensity(
    *, in_greedy: bool, slate_size: int, pool_size: int, epsilon: float
) -> float:
    """Marginal P(item shown) under slate-level ε-greedy mixture.

    Mixture: with prob (1-ε) S = G; with prob ε S = uniform K-subset of E.
    For item i:
        P(i in S) = (1 - ε) · 𝟙[i ∈ G] + ε · K / N

    Edge cases:
      pool_size == 0  → 0.0  (item is not in any pool, so not loggable)
      pool_size <= slate_size  → 1.0  (degenerate: everyone shown)
    """
    if pool_size <= 0:
        return 0.0
    if pool_size <= slate_size:
        return 1.0
    explore_term = epsilon * slate_size / pool_size
    if in_greedy:
        return (1.0 - epsilon) + explore_term
    return explore_term


def sample_slate(
    eligible: list[dict],
    greedy: list[dict],
    *,
    epsilon: float,
    rng: random.Random,
) -> tuple[list[dict], Branch]:
    """Sample a slate via the ε-greedy mixture.

    Returns (slate, branch). slate is a list of items drawn from `eligible`;
    branch ∈ {'greedy', 'explore', 'degenerate'}.

    - Empty pool → ([], 'degenerate').
    - pool_size <= slate_size (== len(greedy) by phase4 contract) → return all
      eligible items, branch='degenerate'. ε is ignored in this case.
    - Otherwise: with prob 1-ε return greedy unchanged ('greedy');
      with prob ε return a uniform random K-subset of eligible ('explore').
    """
    pool_size = len(eligible)
    if pool_size == 0:
        return [], "degenerate"
    slate_size = len(greedy)
    if pool_size <= slate_size:
        return list(eligible), "degenerate"
    if rng.random() < epsilon:
        slate = rng.sample(eligible, slate_size)
        return slate, "explore"
    return list(greedy), "greedy"


def _env_bool(name: str, default: bool) -> bool:
    raw = config.get(name)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_float(name: str, default: float) -> float:
    raw = config.get(name)
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except ValueError:
        log.warning("Invalid float for %s: %r — falling back to %s", name, raw, default)
        return default


def _env_int_or_none(name: str) -> int | None:
    raw = config.get(name)
    if raw is None or raw == "":
        return None
    try:
        return int(raw)
    except ValueError:
        log.warning("Invalid int for %s: %r — using non-deterministic RNG", name, raw)
        return None


def _build_rng() -> random.Random:
    seed = _env_int_or_none("EL_HIL_LOGGING_RNG_SEED")
    return random.Random(seed) if seed is not None else random.Random()


def _passthrough(ctx: dict) -> dict:
    ctx["hil_slate"] = list(ctx.get("phase4_candidates") or [])
    ctx["logging_event_id"] = ""
    ctx["hil_slate_branch"] = "passthrough"
    return ctx


def _candidate_key(payload: dict) -> tuple[str, str]:
    return (
        str(payload.get("product_url") or "").strip().lower(),
        str(payload.get("product_sku") or "").strip().lower(),
    )


def _build_logging_rows(
    *,
    event_id: str,
    eligible_pool: list[dict],
    slate_keys: set[tuple[str, str]],
    branch: Branch,
    epsilon: float,
    pool_size: int,
    slate_size: int,
) -> list[dict]:
    rows: list[dict] = []
    for entry in eligible_pool:
        payload = entry["candidate_payload"]
        in_greedy = bool(entry["in_greedy_slate"])
        propensity = compute_marginal_propensity(
            in_greedy=in_greedy,
            slate_size=slate_size,
            pool_size=pool_size,
            epsilon=epsilon,
        )
        if propensity <= 0:
            continue
        was_shown = _candidate_key(payload) in slate_keys
        rows.append({
            "event_id": event_id,
            "candidate_idx": int(entry["candidate_rank"]) - 1,
            "candidate_score": float(entry["candidate_score"]),
            "candidate_rank": int(entry["candidate_rank"]),
            "candidate_payload": payload,
            "in_greedy_slate": in_greedy,
            "was_shown": was_shown,
            "branch": branch,
            "propensity": propensity,
            "epsilon": epsilon,
            "pool_size": pool_size,
            "slate_size": slate_size,
        })
    return rows


def run(
    ctx: dict,
    *,
    provider: "supabase.SupabaseRestProvider | None" = None,
) -> dict:
    """Sample slate via ε-greedy mixture, log propensities, set hil_slate.

    On any failure: passthrough to phase4_candidates. Pipeline never crashes.
    """
    if not _env_bool("EL_HIL_LOGGING_ENABLED", default=True):
        log.info("stochastic_logger: EL_HIL_LOGGING_ENABLED=false → passthrough")
        return _passthrough(ctx)

    eligible_pool = ctx.get("eligible_pool") or []
    phase4_candidates = ctx.get("phase4_candidates") or []

    if not eligible_pool:
        log.info("stochastic_logger: empty eligible_pool → passthrough")
        return _passthrough(ctx)

    epsilon = _env_float("EL_HIL_EPSILON", default=0.1)
    epsilon = max(0.0, min(1.0, epsilon))

    rng = _build_rng()
    eligible_payloads = [e["candidate_payload"] for e in eligible_pool]
    greedy_payloads = [e["candidate_payload"] for e in eligible_pool if e["in_greedy_slate"]]

    try:
        slate, branch = sample_slate(
            eligible_payloads, greedy_payloads, epsilon=epsilon, rng=rng
        )
    except Exception:
        log.exception("stochastic_logger: sampler crashed → passthrough")
        return _passthrough(ctx)

    slate_keys = {_candidate_key(p) for p in slate}
    if branch == "greedy":
        hil_slate = list(phase4_candidates)
    else:
        hil_slate = list(slate)

    event_id_db = str(uuid.uuid4())

    pool_size = len(eligible_pool)
    slate_size = len(greedy_payloads)

    rows = _build_logging_rows(
        event_id=event_id_db,
        eligible_pool=eligible_pool,
        slate_keys=slate_keys,
        branch=branch,
        epsilon=epsilon,
        pool_size=pool_size,
        slate_size=slate_size,
    )

    if not rows:
        log.info("stochastic_logger: no rows to log (all propensities zero) → passthrough")
        return _passthrough(ctx)

    active_provider = provider or supabase.SupabaseRestProvider()
    try:
        active_provider.insert_rows(
            schema=supabase.HIL_REVIEWS_SCHEMA,
            table=supabase.HIL_LOGGING_EVENTS_TABLE,
            rows=rows,
        )
    except Exception:
        log.exception("stochastic_logger: Supabase insert failed → passthrough")
        return _passthrough(ctx)

    ctx["hil_slate"] = hil_slate
    ctx["logging_event_id"] = event_id_db
    ctx["hil_slate_branch"] = branch
    log.info(
        "stochastic_logger: branch=%s pool=%d slate=%d ε=%.3f rows_logged=%d event_id=%s",
        branch, pool_size, slate_size, epsilon, len(rows), event_id_db,
    )
    return ctx
