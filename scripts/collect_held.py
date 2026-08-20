"""
collect_held.py — WS5 phase 2 held-tickers EOD quote feed (ADR-012 §10 phase 2, §11
"Ticker-quote store = D1, append-only"; design: planning/trade-lifecycle-engine.md §5
D1 schema, §5a "Two separate feeds", §10 Phasing, §11 Decisions resolved; issues #312,
#297 full-scrape-column-set).

Settled-EOD feed for the *held* set (union of open/managing/closing positions), distinct
from WS3's morning picks/watch feed (§5a) — different membership, different store, same
shared scrape mechanism (`fetch_ticker_quotes` / `build_ticker_url` in collect_morning.py,
called here with `block="held"`).

Unlike collect_morning.py/collect.py this script does NOT write to the repo at all — it
POSTs to the `finviz-positions` Worker's authenticated `/ingest/quotes` endpoint, which
writes to D1's `ticker_quotes` table (append-only, one row per ticker per trade_date; see
planning doc §5). There is nothing to `git commit`. Auth is a static Bearer token
(`POSITIONS_INGEST_TOKEN`) against `POSITIONS_WORKER_URL` — both required env vars, set as
GitHub Actions secrets by the repo owner (out of band; not touched by this script or by
`wrangler deploy`).

Must run on GitHub Actions (Azure IPs) — Cloudflare blocks headless Chromium scraping
Finviz from Google Cloud IPs, same constraint as collect.py/collect_picks.py/collect_morning.py
(see root CLAUDE.md § Playwright notes).

WS5 phase 3b: immediately after a successful `post_quotes()` call, this script also POSTs
to the Worker's `/advance` endpoint to trigger a sweep of the daily trade-lifecycle engine
over the bars just ingested. Dependency-gated (fires right after fresh bars land), not a
separate cron. Same service token, no new env vars. Pass `--no-advance` to ingest bars
without triggering the sweep (a bars-only backfill escape hatch).

WS5-8: pass `--advisory` to run this same scrape as a 15:40 ET pre-close read instead of
the 17:30 ET settled feed. This POSTs the identical payload shape to the Worker's
`/positions/preclose-advisory` endpoint instead of `/ingest/quotes` — that endpoint
computes an advisory read and writes NOTHING to `positions`/`ticker_quotes`, so it is safe
to run ahead of the close without corrupting the 17:30 settled sweep. `--advisory` implies
no `/advance` call (there is no sweep to trigger; the advisory endpoint does its own
compute) — the flag is a superset of `--no-advance`, not a separate on/off axis.
"""

import json
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from collect import NYSE_HOLIDAYS, _is_trading_day  # noqa: E402  (reuse holiday table only)
from collect_morning import (  # noqa: E402  (reuse the shared scrape mechanism verbatim)
    CONFIG_PATH,
    _to_float,
    fetch_ticker_quotes,
)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

HELD_TICKERS_PATH = "/held-tickers"
INGEST_QUOTES_PATH = "/ingest/quotes"
ADVANCE_PATH = "/advance"
# WS5-8: advisory pre-close endpoint. Same payload shape as INGEST_QUOTES_PATH, but the
# Worker computes an advisory read and writes nothing to positions/ticker_quotes.
PRECLOSE_ADVISORY_PATH = "/positions/preclose-advisory"

# Finviz label -> ticker_quotes/ingest payload field. "Ticker" is handled separately
# (used as the row key + skip guard, not a `raw`-adjacent numeric). Kept as a module
# constant (not inlined in build_quote_payload) so the label set is visible/greppable
# in one place if Finviz ever renames a column (mirrors the header-drift concern
# documented for collect_picks.py in scripts/CLAUDE.md).
_FIELD_LABELS = {
    "prev_close": "Prev Close",
    "open": "Open",
    "high": "High",
    "low": "Low",
    "close": "Price",
    "change_pct": "Change",
    "atr": "ATR",
    "volume": "Volume",
}


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def build_quote_payload(quotes: list, trade_date: str, collected_at: str) -> dict:
    """Map scraped Finviz row dicts to the `/ingest/quotes` POST body.

    PURE — no I/O, no network. `quotes` is the flat list `fetch_ticker_quotes` returns
    (row dicts keyed by Finviz's scraped labels, block="held" -> full 84-column set).
    Rows missing/blank "Ticker" are skipped (defensive — fetch_ticker_quotes should
    never emit one, but a row with no ticker is unusable to the ingest endpoint's
    per-row keying). `raw` carries the ENTIRE original row dict verbatim (#297) so no
    scraped column is ever dropped, even though only a handful are pulled into typed
    top-level fields today.

    `days_to_earnings` is left None in phase 2 — phase 3 derives it from raw["Earnings"]
    (planning/trade-lifecycle-engine.md §6 EARNINGS_WARN_SESSIONS).
    """
    rows = []
    for row in quotes:
        ticker = row.get("Ticker")
        if not ticker:
            continue
        entry = {"ticker": ticker}
        for field, label in _FIELD_LABELS.items():
            entry[field] = _to_float(row.get(label))
        entry["days_to_earnings"] = None
        entry["raw"] = dict(row)
        rows.append(entry)

    return {
        "trade_date": trade_date,
        "collected_at": collected_at,
        "quotes": rows,
    }


# ---------------------------------------------------------------------------
# Impure helpers (network)
# ---------------------------------------------------------------------------


def _authed_request(url: str, token: str, method: str = "GET", body: bytes = None):
    req = urllib.request.Request(url, data=body, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    # Cloudflare's Bot Fight Mode blocks the default "Python-urllib/x.y" User-Agent with a
    # generic 403 (error code 1010) on workers.dev zones, before the request ever reaches the
    # Worker's own auth code — verified live 2026-08-13. A non-generic UA (anything not matching
    # python-urllib/python-requests/curl/scrapy signatures) clears it.
    req.add_header("User-Agent", "finviz-groups-tracker-held-feed/1.0")
    if body is not None:
        req.add_header("Content-Type", "application/json")
    return urllib.request.urlopen(req, timeout=30)


def fetch_held_tickers(worker_url: str, token: str) -> list:
    """GET {worker_url}/held-tickers -> list of ticker strings. Loud exit(1) on any
    non-200 (misconfiguration/auth failure/worker down) — this feed has no fallback
    source of the held set, so a failed read must not silently proceed as "no positions".
    """
    url = worker_url.rstrip("/") + HELD_TICKERS_PATH
    try:
        with _authed_request(url, token) as resp:
            status = resp.status
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        print(f"GET {HELD_TICKERS_PATH} failed: HTTP {exc.code} {exc.reason}", file=sys.stderr)
        sys.exit(1)
    except Exception as exc:
        print(f"GET {HELD_TICKERS_PATH} failed: {exc}", file=sys.stderr)
        sys.exit(1)

    if status != 200:
        print(f"GET {HELD_TICKERS_PATH} returned HTTP {status}", file=sys.stderr)
        sys.exit(1)

    return data.get("tickers", [])


def post_quotes(worker_url: str, token: str, payload: dict, path: str = INGEST_QUOTES_PATH) -> int:
    """POST {worker_url}{path} -> written count. Loud exit(1) on any non-200.

    `path` defaults to `/ingest/quotes` (the settled feed); WS5-8's `--advisory` mode
    passes `PRECLOSE_ADVISORY_PATH` instead. Same auth, same UA, same payload builder —
    only the destination endpoint differs.
    """
    url = worker_url.rstrip("/") + path
    body = json.dumps(payload).encode("utf-8")
    try:
        with _authed_request(url, token, method="POST", body=body) as resp:
            status = resp.status
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
        print(f"POST {path} failed: HTTP {exc.code} {exc.reason} {detail}", file=sys.stderr)
        sys.exit(1)
    except Exception as exc:
        print(f"POST {path} failed: {exc}", file=sys.stderr)
        sys.exit(1)

    if status != 200:
        print(f"POST {path} returned HTTP {status}", file=sys.stderr)
        sys.exit(1)

    return data.get("written", 0)


def trigger_advance(worker_url: str, token: str) -> "dict | None":
    """POST {worker_url}/advance -> counts dict, e.g. {"dry_run": false, "positions": 3,
    "advanced": 3, "signalled": 1, "unchanged": 0, "stale": 0}. A service-token caller gets
    counts only, no per-position detail — don't expect more than that here.

    Unlike post_quotes/fetch_held_tickers, failure here does NOT sys.exit — it prints a loud
    stderr error and returns None, leaving the exit-code decision to the caller. Rationale: by
    the time this runs, this run's bars are ALREADY committed to D1 by post_quotes(); the
    engine sweep is a catch-up fold over whatever bars exist, so a failed sweep today is
    loud-but-recoverable — tomorrow's sweep advances through today's bars anyway. It must never
    be treated as a reason to lose (or retry-and-duplicate) the ingest that already succeeded.
    """
    url = worker_url.rstrip("/") + ADVANCE_PATH
    # Empty JSON object body, not None: the route is a real POST match on the Worker side, but
    # it does not parse a request body for this endpoint — `{}` is the conventional "POST with
    # no meaningful payload" shape rather than a bodyless POST that changes the request's headers.
    body = b"{}"
    try:
        with _authed_request(url, token, method="POST", body=body) as resp:
            status = resp.status
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
        print(f"POST {ADVANCE_PATH} failed: HTTP {exc.code} {exc.reason} {detail}", file=sys.stderr)
        return None
    except Exception as exc:
        print(f"POST {ADVANCE_PATH} failed: {exc}", file=sys.stderr)
        return None

    if status != 200:
        print(f"POST {ADVANCE_PATH} returned HTTP {status}", file=sys.stderr)
        return None

    return data


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    import argparse
    import os
    import pytz

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                         help="Scrape + map + print row counts; do not POST to the ingest endpoint.")
    parser.add_argument("--no-advance", action="store_true",
                         help="Ingest bars but skip the post-ingest engine sweep (POST /advance). "
                              "Escape hatch for a bars-only backfill run.")
    parser.add_argument("--advisory", action="store_true",
                         help="WS5-8: run the 15:40 ET pre-close advisory scrape. POSTs to "
                              "/positions/preclose-advisory instead of /ingest/quotes, and never "
                              "calls /advance (implies --no-advance).")
    args = parser.parse_args()

    et = pytz.timezone("America/New_York")
    now_et = datetime.now(et)
    today = now_et.date()

    # Non-trading-day guard: settled EOD feed, no rollback (unlike collect.py's
    # trading_date()) — a closed day has no session to capture, and rolling back
    # would re-stamp a stale bar under today's trade_date.
    if today.weekday() >= 5:
        print(f"{today} is a weekend — no session to capture. Exiting 0.")
        sys.exit(0)
    if today.strftime("%Y-%m-%d") in NYSE_HOLIDAYS:
        print(f"{today} is an NYSE holiday — no session to capture. Exiting 0.")
        sys.exit(0)
    if not _is_trading_day(today):
        print(f"{today} is not a trading day — no session to capture. Exiting 0.")
        sys.exit(0)

    trade_date = today.strftime("%Y-%m-%d")

    worker_url = os.environ.get("POSITIONS_WORKER_URL")
    token = os.environ.get("POSITIONS_INGEST_TOKEN")
    if not worker_url or not token:
        print("POSITIONS_WORKER_URL and POSITIONS_INGEST_TOKEN must both be set.", file=sys.stderr)
        sys.exit(1)

    tickers = fetch_held_tickers(worker_url, token)
    if not tickers:
        print("No held positions — nothing to fetch.")
        sys.exit(0)

    print(f"Held universe: {len(tickers)} ticker(s) for {trade_date}.")

    config = json.loads(CONFIG_PATH.read_text())

    if args.dry_run:
        print(f"[dry-run] {len(tickers)} tickers to fetch.")

    from playwright.sync_api import sync_playwright  # guarded import, mirrors collect_morning.py

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
            ignore_https_errors=True,
        )
        page = ctx.new_page()
        quotes = fetch_ticker_quotes(page, tickers, config, block="held")
        browser.close()

    # Empty-scrape guard: held set was non-empty but nothing came back — the
    # Cloudflare-block signature (every page 200s with an empty table). Don't POST
    # junk / an empty overwrite; make CI red instead (mirrors collect_picks.py's
    # empty-scrape guard, simpler here since there's no local file to protect).
    if not quotes:
        print("Held set was non-empty but the scrape returned 0 rows "
              "(Cloudflare block signature) — refusing to POST.", file=sys.stderr)
        sys.exit(1)

    collected_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    payload = build_quote_payload(quotes, trade_date, collected_at)

    print(f"Built {len(payload['quotes'])} quote rows from {len(quotes)} scraped rows.")

    if args.dry_run:
        print("[dry-run] not posting.")
        return

    if args.advisory:
        # The advisory endpoint returns {trade_date, users, checked, flagged}, NOT {written} — so
        # don't print a bar-count here (post_quotes would report 0 and mislead a CI-log reader). The
        # advisory writes no ticker_quotes rows by design; count of positions read/flagged lives in
        # the endpoint's own response/logs.
        post_quotes(worker_url, token, payload, path=PRECLOSE_ADVISORY_PATH)
        print(f"Posted pre-close advisory scrape for {trade_date} ({len(payload['quotes'])} tickers).")
        print("Skipping engine sweep (--advisory implies no /advance call).")
        return

    written = post_quotes(worker_url, token, payload)
    print(f"Wrote {written} row(s) to D1 ticker_quotes for {trade_date}.")

    if args.no_advance:
        print("Skipping engine sweep (--no-advance).")
        return

    result = trigger_advance(worker_url, token)
    if result is None:
        # Bars are already safely in D1 (post_quotes succeeded above) — this is a loud
        # notification, not data loss. Exit 1 so GitHub Actions emails about it; tomorrow's
        # sweep will fold through today's bars regardless.
        print("Engine sweep failed to run — bars ARE safely stored in D1; "
              "the next scheduled sweep will catch up. Not retrying here.", file=sys.stderr)
        sys.exit(1)

    print(
        f"Engine sweep: {result.get('positions', '?')} position(s) considered, "
        f"{result.get('advanced', '?')} advanced, {result.get('signalled', '?')} exit signal(s), "
        f"{result.get('stale', '?')} stale."
    )


if __name__ == "__main__":
    main()
