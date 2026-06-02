# Forge Engine Handoff

Forge Engine is the next pipeline layer after Fenix. Fenix answers: "What is
trending?" Forge answers: "Where can we source it, at what price, with usable
images, stock, shipping, and margins?"

## Git workflow for the teammate

Do this before any code changes:

```powershell
git status --short --branch
git checkout main
git pull --ff-only origin main
git checkout -b codex/forge-engine-suppliers
```

If `git status` shows local changes you did not make, stop and ask before
editing those files.

Make all Forge Engine changes only on `codex/forge-engine-suppliers`. When done:

```powershell
pytest
git status --short
git add <changed-files>
git commit -m "Add Forge supplier search engine"
git push -u origin codex/forge-engine-suppliers
```

Then open a pull request into `main`, request review/merge, and do not merge it
yourself unless the owner approves. After the PR is merged:

```powershell
git checkout main
git pull --ff-only origin main
```

## Codex task prompt

Give this to Codex in the new branch:

> Build Forge Engine, a supplier-search layer that takes ranked Fenix trend
> products and searches dropshipping/wholesale supplier APIs. Keep the first
> implementation small, tested, fail-soft, and compatible with the current
> pipeline style.

## Architecture target

Add a supplier-source protocol similar to `el/sources`:

- `el/suppliers/__init__.py`
  - `SupplierCandidate` dataclass with fields:
    - `title`
    - `source_id`
    - `supplier_product_id`
    - `product_url`
    - `image_url`
    - `cost`
    - `currency`
    - `shipping_cost`
    - `shipping_days_min`
    - `shipping_days_max`
    - `stock`
    - `moq`
    - `rating`
    - `raw_payload`
  - `SupplierSource` protocol with `search_products(query: str, ctx: dict)`.
- `el/suppliers/cj_source.py`
  - Wrap the existing CJ client first; do not rewrite CJ from scratch.
- `el/suppliers/eprolo_source.py`
  - Add next because EPROLO advertises free API access by request.
- Optional after MVP:
  - `printify_source.py` and `printful_source.py` for print-on-demand merch.
  - `bigbuy_source.py`, `doba_source.py`, `wholesale2b_source.py` as gated
    sources if accounts/API access are available.
- `el/nodes/supplier_search.py`
  - Input: top ranked Fenix products from `ctx["ranked"]` or equivalent current
    trend output.
  - For each trend, query all enabled supplier sources.
  - Normalize results to `SupplierCandidate`.
  - Deduplicate by normalized title/product URL.
  - Score matches by title similarity, availability, landed cost, delivery time,
    image presence, and source reliability.
  - Output: `ctx["supplier_matches"]`.

## Source priority

Start with sources that are realistic for this project:

1. `cj`
   - Already present in the repo.
   - Use existing env vars: `CJ_EMAIL`, `CJ_API_KEY`.
   - Must fail soft if creds are missing.
2. `eprolo`
   - EPROLO says its platform is free and API access can be requested after
     signup by messaging the account support rep.
   - Add env placeholders only if real credentials/docs are obtained:
     `EPROLO_API_KEY`, `EPROLO_API_BASE_URL`.
3. `printify`
   - Best for merch/fan products from Fenix, not generic gadgets.
   - Printify supports personal access tokens and catalog APIs.
   - Env: `PRINTIFY_API_TOKEN`.
4. `printful`
   - Also POD/merch-focused.
   - Useful for `sports_and_merch`, apparel, mugs, posters, phone cases.
   - Env: `PRINTFUL_API_TOKEN`.
5. `bigbuy`, `doba`, `wholesale2b`
   - Good API candidates, but verify account/plan/API access before coding them.
   - Keep them behind feature flags and tests with fake HTTP responses.

Avoid building AliExpress first. Its API access/approval is harder and will slow
the project down.

## Config

Add a new env block to `.env.example`:

```dotenv
# Forge Engine supplier search
EL_SUPPLIER_SOURCES_ENABLED="cj,eprolo"
EL_SUPPLIER_SEARCH_TOP_TRENDS="10"
EL_SUPPLIER_SEARCH_MAX_RESULTS_PER_SOURCE="20"
EPROLO_API_KEY=""
EPROLO_API_BASE_URL=""
PRINTIFY_API_TOKEN=""
PRINTFUL_API_TOKEN=""
```

Do not make any supplier credential required. Forge must run offline in tests and
skip missing credentials in production.

## CLI

Add a preview command:

```powershell
python -m el forge --query "RCB jersey" --top 5 --json
```

Also support:

```powershell
python -m el forge --from-fenix --top 10 --json
```

The command should not upload anything to Shopify. It only previews supplier
matches.

## Tests required

Add focused tests before asking for PR review:

- `tests/test_supplier_protocol.py`
- `tests/test_supplier_search.py`
- `tests/test_suppliers_cj.py`
- `tests/test_suppliers_eprolo.py`

Each source test should cover:

- missing credentials returns `[]`
- non-200 HTTP returns `[]`
- malformed JSON returns `[]`
- one happy-path response maps into `SupplierCandidate`
- score/rank prefers available, lower landed-cost, faster-shipping matches

Run:

```powershell
pytest tests/test_supplier_search.py tests/test_suppliers_cj.py tests/test_suppliers_eprolo.py
pytest
```

## Done criteria

The PR is ready when:

- `python -m el trends --top 5` still works.
- `python -m el forge --query "test product" --json` works without supplier
  credentials and returns an empty result instead of crashing.
- Unit tests pass.
- The PR description explains which supplier APIs are real-live tested and which
  are fake-tested only.
- No secrets are committed.

## Current API research notes

- CJ Dropshipping has official API docs at `https://developers.cjdropshipping.com/`.
- EPROLO advertises free dropshipping/API access, but the API document is sent
  by support after signup/request.
- Printify has official API docs with personal access tokens, catalog endpoints,
  and rate limits. It is strong for POD merch.
- Printful has official catalog/product/order APIs. It is also POD-focused.
- BigBuy, Doba, and Wholesale2B all advertise API integrations, but account plan
  and access requirements must be verified before implementation.
