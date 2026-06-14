"""Thin HTTP client for the finviz-ticker-lookup Cloudflare Worker.

Kept free of any Streamlit import so it is unit-testable in isolation. The Worker
always returns HTTP 200 with an ``error`` field on failure, so the only thing this
wrapper has to handle is transport-level failure (timeout, connection, non-200).
"""

import requests


def lookup_ticker(symbol: str, lookup_url: str, timeout: int = 10) -> dict:
    """Call the Worker /lookup endpoint for ``symbol``.

    ``lookup_url`` is the full endpoint (e.g. ``https://.../lookup``). Returns the
    parsed JSON body on success, or ``{"error": "..."}`` on a transport failure so
    callers branch on the body uniformly.
    """
    try:
        resp = requests.get(lookup_url, params={"t": symbol.upper()}, timeout=timeout)
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.Timeout:
        return {"error": "timeout"}
    except requests.exceptions.HTTPError as exc:
        status = getattr(getattr(exc, "response", None), "status_code", "error")
        return {"error": f"http_{status}"}
    except requests.exceptions.RequestException:
        return {"error": "network_error"}
