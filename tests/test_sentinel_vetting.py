"""Tests for the Sentinel Engine vetting gate, preview helper, and CLI wiring."""
from __future__ import annotations

import copy
import json

from el import __main__ as cli
from el import pipeline
from el.nodes import sentinel_vetting
from el.suppliers import SupplierCandidate


# --------------------------------------------------------------------------- #
# fixtures / builders                                                         #
# --------------------------------------------------------------------------- #
def _match(**overrides) -> dict:
    """A strong Forge match dict (as supplier_search emits) — pass by default."""
    base = {
        "title": "RCB Jersey 2024 Official",
        "source_id": "cj",
        "supplier_product_id": "PID1",
        "product_url": "https://cjdropshipping.com/product/1",
        "image_url": "https://img.cj.com/1.jpg",
        "cost": 8.0,
        "currency": "USD",
        "shipping_cost": 2.0,
        "shipping_days_min": 7,
        "shipping_days_max": 12,
        "stock": 50,
        "rating": 4.6,
        "match_score": 0.82,
        "landed_cost": 10.0,
        "raw_payload": {},
    }
    base.update(overrides)
    return base


def _ctx(matches, *, query="RCB jersey", trend=None) -> dict:
    return {
        "supplier_matches": [
            {"trend": trend or {"topic": query, "rank": 1}, "query": query, "matches": matches}
        ]
    }


def _run(matches, **kw):
    """Vet a single-trend ctx and return that trend's output group."""
    ctx = _ctx(matches, **kw)
    sentinel_vetting.run(ctx)
    return ctx["sentinel_matches"][0]


def _only(group) -> dict:
    """The single vetted match (pass or reject) from a one-candidate group."""
    return (group["matches"] + group["rejected"])[0]


# --------------------------------------------------------------------------- #
# happy path                                                                  #
# --------------------------------------------------------------------------- #
def test_strong_product_passes():
    group = _run([_match()])
    assert group["summary"] == {"evaluated": 1, "passed": 1, "rejected": 0}
    match = group["matches"][0]
    assert match["sentinel_decision"] == "pass"
    assert match["sentinel_score"] >= 0.62
    assert match["sentinel_rejection_reasons"] == []
    # original Forge fields are preserved on the vetted match
    assert match["source_id"] == "cj"
    assert match["match_score"] == 0.82


# --------------------------------------------------------------------------- #
# hard rejects                                                                #
# --------------------------------------------------------------------------- #
def test_rejects_missing_title():
    group = _run([_match(title="")])
    assert _only(group)["sentinel_decision"] == "reject"
    assert "missing_title" in _only(group)["sentinel_rejection_reasons"]


def test_rejects_missing_url():
    group = _run([_match(product_url=None)])
    assert "missing_product_url" in _only(group)["sentinel_rejection_reasons"]


def test_rejects_explicit_out_of_stock():
    group = _run([_match(stock=0)])
    assert "out_of_stock" in _only(group)["sentinel_rejection_reasons"]


def test_rejects_low_margin_against_market_price():
    # landed 10, market price 11 -> margin ~9% < 30% default => reject.
    group = _run([_match(market_price=11.0)])
    match = _only(group)
    assert match["sentinel_decision"] == "reject"
    assert any(r.startswith("low_margin") for r in match["sentinel_rejection_reasons"])
    assert match["projected_sell_price"] == 11.0
    assert match["projected_margin_pct"] < 0.30


def test_rejects_slow_shipping():
    group = _run([_match(shipping_days_max=30)])
    match = _only(group)
    assert match["sentinel_decision"] == "reject"
    assert any(r.startswith("slow_shipping") for r in match["sentinel_rejection_reasons"])


# --------------------------------------------------------------------------- #
# the margin gate must NOT be circular (regression for the plan-review bug)    #
# --------------------------------------------------------------------------- #
def test_markup_only_margin_never_rejects():
    # No market price: sell = landed * markup, so margin == 1 - 1/markup (constant).
    # Even a wildly expensive supplier must NOT be rejected on margin alone.
    group = _run([_match(cost=999.0, shipping_cost=1.0, landed_cost=1000.0)])
    match = _only(group)
    assert not any(r.startswith("low_margin") for r in match["sentinel_rejection_reasons"])
    assert "margin_estimated_from_markup" in match["sentinel_warnings"]


# --------------------------------------------------------------------------- #
# soft warnings (do not flip the decision)                                    #
# --------------------------------------------------------------------------- #
def test_unknown_stock_and_shipping_warn_but_pass():
    group = _run([_match(stock=None, shipping_days_min=None, shipping_days_max=None)])
    match = group["matches"][0]
    assert match["sentinel_decision"] == "pass"
    assert "unknown_stock" in match["sentinel_warnings"]
    assert "unknown_shipping" in match["sentinel_warnings"]


def test_unknown_rating_warns_but_passes():
    group = _run([_match(rating=None)])
    match = group["matches"][0]
    assert match["sentinel_decision"] == "pass"
    assert "unknown_rating" in match["sentinel_warnings"]


# --------------------------------------------------------------------------- #
# IP-risk                                                                     #
# --------------------------------------------------------------------------- #
def test_ip_risk_warns_by_default():
    group = _run([_match(title="Team India Jersey 2024")])
    match = group["matches"][0]
    assert match["sentinel_decision"] == "pass"
    assert any(w.startswith("ip_risk:") for w in match["sentinel_warnings"])


def test_ip_risk_blocks_when_configured(monkeypatch):
    monkeypatch.setenv("EL_SENTINEL_BLOCK_IP_RISK", "true")
    group = _run([_match(title="Team India Jersey 2024")])
    match = _only(group)
    assert match["sentinel_decision"] == "reject"
    assert any(r.startswith("ip_risk:") for r in match["sentinel_rejection_reasons"])


# --------------------------------------------------------------------------- #
# soft score floor                                                            #
# --------------------------------------------------------------------------- #
def test_low_sentinel_score_rejects_even_without_hard_gate():
    # Clears every hard gate but is weak: no relevance, no image, no rating/stock info.
    weak = _match(
        match_score=0.0, image_url=None, rating=None,
        stock=None, shipping_days_min=None, shipping_days_max=None,
    )
    group = _run([weak])
    match = _only(group)
    assert match["sentinel_decision"] == "reject"
    assert any(r.startswith("low_sentinel_score") for r in match["sentinel_rejection_reasons"])


# --------------------------------------------------------------------------- #
# truncation, transparency, immutability, disabled                           #
# --------------------------------------------------------------------------- #
def test_top_matches_per_trend_truncates_passes(monkeypatch):
    monkeypatch.setenv("EL_SENTINEL_TOP_MATCHES_PER_TREND", "2")
    matches = [_match(match_score=s, product_url=f"https://cj/p/{i}")
               for i, s in enumerate([0.9, 0.8, 0.7, 0.6, 0.5])]
    group = _run(matches)
    assert len(group["matches"]) == 2
    assert group["summary"]["passed"] == 5  # all passed; only the top 2 are surfaced
    scores = [m["sentinel_score"] for m in group["matches"]]
    assert scores == sorted(scores, reverse=True)


def test_rejected_matches_are_returned_for_transparency():
    group = _run([_match(), _match(title="", product_url=None)])
    assert group["summary"] == {"evaluated": 2, "passed": 1, "rejected": 1}
    assert len(group["rejected"]) == 1
    assert group["rejected"][0]["sentinel_decision"] == "reject"


def test_does_not_mutate_supplier_matches():
    ctx = _ctx([_match()])
    snapshot = copy.deepcopy(ctx["supplier_matches"])
    sentinel_vetting.run(ctx)
    # Forge's original list is untouched — no sentinel_* keys leaked in.
    assert ctx["supplier_matches"] == snapshot
    assert "sentinel_score" not in ctx["supplier_matches"][0]["matches"][0]


def test_disabled_passes_through(monkeypatch):
    monkeypatch.setenv("EL_SENTINEL_ENABLED", "false")
    group = _run([_match(title="", product_url=None)])  # would normally be rejected
    match = group["matches"][0]
    assert match["sentinel_decision"] == "skipped"
    assert match["sentinel_rejection_reasons"] == []


def test_empty_supplier_matches_is_safe():
    ctx = {"supplier_matches": []}
    sentinel_vetting.run(ctx)
    assert ctx["sentinel_matches"] == []


# --------------------------------------------------------------------------- #
# preview helper + CLI                                                        #
# --------------------------------------------------------------------------- #
class FakeSupplierSource:
    SOURCE_ID = "fake"

    def search_products(self, query, ctx):
        return [
            SupplierCandidate(
                title=f"{query} Jersey",
                source_id="cj",
                supplier_product_id="PID1",
                product_url="https://cjdropshipping.com/product/1",
                image_url="https://img.cj.com/1.jpg",
                cost=8.0,
                shipping_cost=2.0,
                shipping_days_min=7,
                shipping_days_max=12,
                stock=40,
                rating=4.5,
            )
        ]


def test_preview_sentinel_query_runs_forge_then_sentinel(monkeypatch):
    monkeypatch.setattr(
        pipeline.supplier_search, "_load_enabled_sources", lambda: [FakeSupplierSource()],
    )
    monkeypatch.setattr(
        pipeline, "collect_and_rank",
        lambda *_, **__: (_ for _ in ()).throw(AssertionError("should not call Fenix")),
    )

    out = pipeline.preview_sentinel(query="RCB jersey", top=5)

    assert out["metadata"]["mode"] == "query"
    assert out["supplier_matches"][0]["query"] == "RCB jersey"  # raw Forge output present
    group = out["sentinel_matches"][0]
    assert group["query"] == "RCB jersey"
    assert group["matches"][0]["sentinel_decision"] == "pass"


def test_preview_sentinel_from_fenix_uses_ranked_payload(monkeypatch):
    monkeypatch.setattr(
        pipeline, "collect_and_rank",
        lambda initial_ctx=None: {
            "metadata": {"mode": "fenix", "total_topics": 1},
            "trends": [{"rank": 1, "topic": "wireless earbuds"}],
        },
    )
    monkeypatch.setattr(
        pipeline.supplier_search, "_load_enabled_sources", lambda: [FakeSupplierSource()],
    )

    out = pipeline.preview_sentinel(from_fenix=True, top=1)

    assert out["metadata"]["mode"] == "fenix"
    assert out["sentinel_matches"][0]["query"] == "wireless earbuds"


def test_cli_sentinel_query_json(monkeypatch, capsys):
    monkeypatch.setattr(
        cli.pipeline, "preview_sentinel",
        lambda **kwargs: {
            "metadata": {"mode": "query"},
            "supplier_matches": [{"query": kwargs["query"], "matches": []}],
            "sentinel_matches": [{
                "query": kwargs["query"],
                "matches": [],
                "rejected": [],
                "summary": {"evaluated": 0, "passed": 0, "rejected": 0},
            }],
        },
    )

    assert cli.main(["sentinel", "--query", "test product", "--top", "5", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["sentinel_matches"][0]["query"] == "test product"
