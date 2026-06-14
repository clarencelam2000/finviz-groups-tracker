"""Tests for dashboard.worker_client.lookup_ticker (no real network)."""

from unittest.mock import MagicMock, patch

import requests

from dashboard.worker_client import lookup_ticker


def test_success_uppercases_and_returns_body():
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"symbol": "AAPL", "finviz_sector": "Technology"}
    mock_resp.raise_for_status.return_value = None
    with patch("dashboard.worker_client.requests.get", return_value=mock_resp) as m:
        result = lookup_ticker("aapl", "https://example.com/lookup")
        m.assert_called_once_with(
            "https://example.com/lookup", params={"t": "AAPL"}, timeout=10
        )
    assert result["finviz_sector"] == "Technology"


def test_timeout_returns_error():
    with patch(
        "dashboard.worker_client.requests.get",
        side_effect=requests.exceptions.Timeout,
    ):
        result = lookup_ticker("AAPL", "https://example.com/lookup")
    assert result == {"error": "timeout"}


def test_http_error_includes_status():
    mock_resp = MagicMock()
    mock_resp.status_code = 500
    err = requests.exceptions.HTTPError(response=mock_resp)
    with patch("dashboard.worker_client.requests.get", side_effect=err):
        result = lookup_ticker("AAPL", "https://example.com/lookup")
    assert result["error"] == "http_500"


def test_connection_error_returns_network_error():
    with patch(
        "dashboard.worker_client.requests.get",
        side_effect=requests.exceptions.ConnectionError,
    ):
        result = lookup_ticker("AAPL", "https://example.com/lookup")
    assert result == {"error": "network_error"}
