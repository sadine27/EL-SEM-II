# Human-in-Loop Review Contract

This document defines the normalized payload that every supplier branch must emit before a product can enter the Telegram human review queue.

## Purpose

The EL workflow currently emits storage-oriented product rows. The human-in-loop feature needs a review-oriented contract that is:

- consistent across CJ and Browserbase-based marketplace extraction
- compact enough for Telegram review cards
- durable enough to persist in Supabase
- explicit about fallback and null behavior

## Canonical Review Item

Each candidate sent to human review must produce one JSON object with the following shape:

```json
{
  "review_schema_version": "hil_v1",
  "workflow_name": "EL",
  "workflow_run_id": "string",
  "run_date": "2026-04-27",
  "source_provider": "cj_dropshipping",
  "source_topic": "wireless earbuds",
  "source_pick_rank": 1,
  "opportunity_score": 8.7,
  "product_name": "Wireless Bluetooth Earbuds",
  "product_url": "https://example.com/product",
  "product_sku": "ABC123",
  "price_text": "Rs 999",
  "price_numeric": 999,
  "currency": "INR",
  "product_rating": 4.3,
  "reviews_count": 1284,
  "image_url": "https://example.com/image.jpg",
  "image_urls": [
    "https://example.com/image.jpg"
  ],
  "description": "Compact summary for operator review.",
  "supplier_name": "Example Supplier",
  "marketplace": "amazon.in",
  "availability_status": "in_stock",
  "approval_status": "pending",
  "approval_channel": "telegram",
  "raw_payload": {},
  "scraped_at": "2026-04-27T08:30:00.000Z"
}
```

## Field Definitions

| Field | Type | Required | Description |
|---|---|---:|---|
| `review_schema_version` | string | yes | Contract version. Start with `hil_v1`. |
| `workflow_name` | string | yes | Workflow identifier. Use `EL`. |
| `workflow_run_id` | string | yes | Execution identifier or deterministic run key for traceability. |
| `run_date` | string | yes | Logical run date in `YYYY-MM-DD`. |
| `source_provider` | string | yes | Source branch that produced the candidate. Initial values: `cj_dropshipping`, `browserbase_marketplace`, `forge_sentinel`. |
| `source_topic` | string | yes | The original curated trend topic tied to the product. |
| `source_pick_rank` | number/null | no | Rank from the upstream curated pick list. |
| `opportunity_score` | number/null | no | Upstream AI opportunity score if available. |
| `product_name` | string | yes | Human-readable product title for Telegram review. |
| `product_url` | string | yes | Product page URL used by the operator. |
| `product_sku` | string/null | no | Supplier SKU or identifier. |
| `price_text` | string/null | no | Source-native price string, preserved for operator display. |
| `price_numeric` | number/null | no | Parsed numeric price for ranking/filtering. |
| `currency` | string/null | no | ISO-like currency label, for example `INR` or `USD`. |
| `product_rating` | number/null | no | Top-level rating normalized to `0..5` when available. |
| `reviews_count` | number/null | no | Review or rating count when available. |
| `image_url` | string/null | no | Primary image URL used for Telegram photo delivery. |
| `image_urls` | array | yes | Ordered image URL list. May be empty. |
| `description` | string/null | no | Short operator-facing summary. |
| `supplier_name` | string/null | no | Supplier or seller name when available. |
| `marketplace` | string/null | no | Marketplace or host, for example `amazon.in`, `flipkart.com`, `cjdropshipping`. |
| `availability_status` | string/null | no | Normalized stock state. Initial values: `in_stock`, `out_of_stock`, `unknown`. |
| `approval_status` | string | yes | Initial review state. Always `pending` at handoff. |
| `approval_channel` | string | yes | Initial channel. Use `telegram`. |
| `raw_payload` | object/string | yes | Original source payload or compressed derivative for audit/debugging. |
| `scraped_at` | string | yes | ISO timestamp for when the candidate row was produced. |

## Normalization Rules

| Concern | Rule |
|---|---|
| Provider naming | Use stable lowercase identifiers with underscores. |
| Rating scale | Normalize to a 0-5 numeric scale. Unknown stays `null`. |
| Price | Keep both `price_text` and `price_numeric`. Never overwrite one with the other. |
| Image selection | `image_url` must be the first usable value from `image_urls`, or `null` if none exist. |
| Missing optional data | Use `null`, not placeholder strings like `N/A`, except where the upstream branch strictly requires raw text preservation. |
| Text limits | `product_name` should be concise enough for Telegram captions. `description` should stay under 300 characters. |
| Raw payload | Preserve enough source detail for debugging extraction issues without changing the normalized top-level contract. |

## Source Mapping

| Canonical field | CJ branch | Browserbase marketplace branch |
|---|---|---|
| `source_provider` | `cj_dropshipping` | `browserbase_marketplace` |
| `product_name` | `productNameEn` or `productName` | extracted product title |
| `product_url` | CJ product URL from `pid` | page URL from Tavily/Browserbase result |
| `product_sku` | `productSku` | usually `null` unless extracted |
| `price_text` | `sellPrice` | extracted displayed price |
| `price_numeric` | parsed lower-bound numeric price | extracted INR numeric value |
| `product_rating` | `null` unless CJ source exposes one later | extracted rating |
| `reviews_count` | `null` unless source exposes one later | extracted review count |
| `image_urls` | split `productImage` field | extracted image URL array |
| `image_url` | first item of `image_urls` | first item of `image_urls` |
| `supplier_name` | `supplierName` | extracted seller/supplier if available |
| `marketplace` | `cjdropshipping` | extracted domain or marketplace label |

## Phase Boundary

Phase 1 is complete when:

1. this contract is accepted as the review payload target
2. later workflow phases update CJ and Browserbase outputs to match it
3. Supabase and Telegram phases consume this contract without adding new ad hoc fields
