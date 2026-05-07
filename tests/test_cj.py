"""Tests for el/cj.py."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import requests

from el import cj


def _fake_response(json_payload: dict, ok: bool = True, status_code: int = 200):
    resp = MagicMock(spec=requests.Response)
    resp.ok = ok
    resp.status_code = status_code
    resp.json.return_value = json_payload
    if not ok:
        resp.raise_for_status.side_effect = requests.HTTPError(f"{status_code} Error")
    else:
        resp.raise_for_status.return_value = None
    return resp


def test_cj_provider_get_access_token_request_shape():
    provider = cj.CJDropshippingProvider(email="user@example.com", api_key="APIKEY")
    with patch.object(cj.requests, "post") as mock_post:
        mock_post.return_value = _fake_response({"data": {"accessToken": "TOKEN"}})
        out = provider.get_access_token()
    assert out == {"data": {"accessToken": "TOKEN"}}
    url, = mock_post.call_args.args
    kwargs = mock_post.call_args.kwargs
    assert url == cj.CJ_TOKEN_URL
    assert kwargs["json"] == {"email": "user@example.com", "apiKey": "APIKEY"}
    assert kwargs["timeout"] == cj.DEFAULT_TIMEOUT


def test_cj_provider_list_products_request_shape():
    provider = cj.CJDropshippingProvider(email="user@example.com", api_key="APIKEY")
    with patch.object(cj.requests, "get") as mock_get:
        mock_get.return_value = _fake_response({"data": {"list": []}})
        out = provider.list_products("wireless earbuds", "TOKEN")
    assert out == {"data": {"list": []}}
    url, = mock_get.call_args.args
    kwargs = mock_get.call_args.kwargs
    assert url == cj.CJ_PRODUCT_LIST_URL
    assert kwargs["headers"] == {"CJ-Access-Token": "TOKEN"}
    assert kwargs["params"] == {
        "pageNum": 1,
        "pageSize": 20,
        "keyWord": "wireless earbuds",
    }
    assert kwargs["timeout"] == cj.DEFAULT_TIMEOUT


def test_cj_provider_propagates_http_error():
    provider = cj.CJDropshippingProvider(email="user@example.com", api_key="APIKEY")
    with patch.object(cj.requests, "post") as mock_post:
        mock_post.return_value = _fake_response({}, ok=False, status_code=401)
        with pytest.raises(requests.HTTPError):
            provider.get_access_token()
