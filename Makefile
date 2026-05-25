.PHONY: shopify-smoke

PYTHON ?= python

shopify-smoke:
	$(PYTHON) scripts/shopify_smoke.py
