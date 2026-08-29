import json
import urllib.error
from io import BytesIO
from unittest.mock import patch

from app.core.update_check import fetch_latest_release_tag, is_update_available


def _fake_response(payload: dict) -> BytesIO:
    body = BytesIO(json.dumps(payload).encode("utf-8"))
    body.__enter__ = lambda self=body: self
    body.__exit__ = lambda self, *a: None
    return body


def test_is_update_available_true_when_tag_differs():
    assert is_update_available("v1.01", "v1.02") is True


def test_is_update_available_false_when_tag_matches():
    assert is_update_available("v1.01", "v1.01") is False


def test_is_update_available_false_when_tag_is_none():
    assert is_update_available("v1.01", None) is False


def test_fetch_latest_release_tag_returns_tag_name_on_success():
    with patch(
        "app.core.update_check.urllib.request.urlopen",
        return_value=_fake_response({"tag_name": "v1.02"}),
    ):
        assert fetch_latest_release_tag() == "v1.02"


def test_fetch_latest_release_tag_returns_none_on_network_error():
    with patch(
        "app.core.update_check.urllib.request.urlopen",
        side_effect=urllib.error.URLError("offline"),
    ):
        assert fetch_latest_release_tag() is None


def test_fetch_latest_release_tag_returns_none_on_missing_tag_name():
    with patch(
        "app.core.update_check.urllib.request.urlopen",
        return_value=_fake_response({}),
    ):
        assert fetch_latest_release_tag() is None
