"""Tests for el/nodes/upload_shopify_products.py."""
from __future__ import annotations

import pytest

from el.nodes import upload_shopify_products


class FakeShopify:
    def __init__(self, fail_names: set[str] | None = None):
        self.fail_names = fail_names or set()
        self.created: list[tuple[dict, str | None]] = []
        self.deleted: list[int] = []
        self.products_by_handle: dict[str, dict] = {}
        self.products_by_id: dict[int, dict] = {}
        self._next_id = 100

    def list_products(self, limit: int = 250) -> list[dict]:
        return list(self.products_by_id.values())[:limit]

    def find_product_by_handle(self, handle):
        return self.products_by_handle.get(handle)

    def create_product(self, payload, *, idempotency_key=None):
        title = payload["product"]["title"]
        if title in self.fail_names:
            raise RuntimeError(f"shopify boom: {title}")
        if idempotency_key:
            existing = self.find_product_by_handle(idempotency_key)
            if existing is not None:
                return existing
        self.created.append((payload, idempotency_key))
        self._next_id += 1
        product = {"id": self._next_id, "handle": idempotency_key, "title": title}
        if idempotency_key:
            self.products_by_handle[idempotency_key] = product
            self.products_by_id[self._next_id] = product
        return product

    def delete_product(self, product_id: int) -> None:
        self.deleted.append(product_id)
        product = self.products_by_id.pop(product_id, None)
        if product and product.get("handle"):
            self.products_by_handle.pop(product["handle"], None)


@pytest.fixture(autouse=True)
def _set_domain(monkeypatch):
    monkeypatch.setenv("SHOPIFY_STORE_DOMAIN", "shop.myshopify.com")


def test_all_picks_succeed_sets_store_url():
    ctx = {
        "request_id": "r-1",
        "niche": "yoga",
        "hil_review_rows": [
            {"product_name": "Mat", "price_text": "29.99", "image_url": "https://x/img.jpg", "approval_status": "approved"},
            {"product_name": "Block", "price_numeric": 12, "description": "Cork block", "approval_status": "approved"},
        ],
    }
    shop = FakeShopify()
    upload_shopify_products.run(ctx, provider=shop)
    res = ctx["shopify_product_results"]
    assert len(res) == 2
    assert all(r["ok"] for r in res)
    assert ctx["shopify_store_url"] == "https://shop.myshopify.com"
    # idempotency keys derived from slug(name) only — no run_id prefix
    keys = [k for _, k in shop.created]
    assert keys == ["mat", "block"]
    # payload shape
    p0 = shop.created[0][0]["product"]
    assert p0["title"] == "Mat"
    assert p0["variants"][0]["price"] == "29.99"
    assert p0["images"] == [{"src": "https://x/img.jpg"}]
    assert "el-curated" in p0["tags"]


def test_partial_failure_aggregates_and_still_sets_url():
    ctx = {
        "request_id": "r-2",
        "hil_review_rows": [{"product_name": "Good", "approval_status": "approved"}, {"product_name": "Bad", "approval_status": "approved"}],
    }
    shop = FakeShopify(fail_names={"Bad"})
    upload_shopify_products.run(ctx, provider=shop)
    res = ctx["shopify_product_results"]
    assert [r["ok"] for r in res] == [True, False]
    assert ctx["formatted_error"][0]["text"] == "upload_shopify_products: 1/2 failed"
    # at least one succeeded → store_url set
    assert ctx["shopify_store_url"] == "https://shop.myshopify.com"


def test_all_failures_no_store_url():
    ctx = {
        "request_id": "r-3",
        "hil_review_rows": [{"product_name": "BadOnly", "approval_status": "approved"}],
    }
    shop = FakeShopify(fail_names={"BadOnly"})
    upload_shopify_products.run(ctx, provider=shop)
    assert ctx["shopify_product_results"][0]["ok"] is False
    assert "shopify_store_url" not in ctx
    assert ctx["formatted_error"][0]["text"] == "upload_shopify_products: 1/1 failed"


def test_no_picks_no_op():
    ctx = {"hil_review_rows": [], "curated_picks": []}
    shop = FakeShopify()
    upload_shopify_products.run(ctx, provider=shop)
    assert ctx["shopify_product_results"] == []
    assert shop.created == []
    assert "formatted_error" not in ctx
    assert "shopify_store_url" not in ctx


def test_falls_back_to_curated_picks():
    ctx = {
        "request_id": "r-4",
        "curated_picks": [{"topic": "T1", "rank": 1}, {"topic": "T2", "rank": 2}],
    }
    shop = FakeShopify()
    upload_shopify_products.run(ctx, provider=shop)
    assert len(shop.created) == 2
    assert shop.created[0][0]["product"]["title"] == "T1"


def test_hil_rows_without_product_name_are_skipped():
    """HIL rows lacking product_name (e.g. YouTube-title topic rows) are never uploaded."""
    ctx = {
        "hil_review_rows": [
            {"product_name": "Real CJ Product", "price_text": "19.99", "approval_status": "approved"},
            {"source_topic": "YouTube Title | Official Video", "price_text": "9.99", "approval_status": "approved"},
        ],
    }
    shop = FakeShopify()
    upload_shopify_products.run(ctx, provider=shop)
    assert len(shop.created) == 1
    assert shop.created[0][0]["product"]["title"] == "Real CJ Product"


def test_pending_and_rejected_hil_rows_not_uploaded():
    """Only approved rows reach Shopify — pending/rejected/no-status are blocked."""
    ctx = {
        "hil_review_rows": [
            {"product_name": "Pending", "approval_status": "pending"},
            {"product_name": "Rejected", "approval_status": "rejected"},
            {"product_name": "No Status"},
            {"product_name": "Approved", "approval_status": "approved"},
        ],
    }
    shop = FakeShopify()
    upload_shopify_products.run(ctx, provider=shop)
    assert len(shop.created) == 1
    assert shop.created[0][0]["product"]["title"] == "Approved"


def test_clears_existing_products_before_upload():
    """Each run deletes old products first so stale picks never accumulate."""
    ctx = {
        "hil_review_rows": [{"product_name": "Mat", "price_text": "29.99", "approval_status": "approved"}],
    }
    shop = FakeShopify()
    upload_shopify_products.run(ctx, provider=shop)
    first_ids = set(shop.products_by_id.keys())
    assert len(first_ids) == 1
    assert shop.deleted == []

    upload_shopify_products.run(ctx, provider=shop)
    second_ids = set(shop.products_by_id.keys())
    assert len(second_ids) == 1
    # first run's product was cleared
    assert len(shop.deleted) == 1
    assert first_ids.isdisjoint(second_ids)


def test_second_run_clears_and_replaces_all_products():
    ctx = {
        "niche": "yoga",
        "hil_review_rows": [
            {"product_name": "Mat", "price_text": "29.99", "approval_status": "approved"},
            {"product_name": "Block", "price_numeric": 12, "approval_status": "approved"},
        ],
    }
    shop = FakeShopify()

    upload_shopify_products.run(ctx, provider=shop)
    first_ids = set(shop.products_by_id.keys())
    assert len(first_ids) == 2

    upload_shopify_products.run(ctx, provider=shop)
    second_ids = set(shop.products_by_id.keys())
    assert len(second_ids) == 2
    assert first_ids.isdisjoint(second_ids)  # replaced, not duplicated
    assert len(shop.deleted) == 2            # both first-run products cleared
    assert ctx["shopify_store_url"] == "https://shop.myshopify.com"
