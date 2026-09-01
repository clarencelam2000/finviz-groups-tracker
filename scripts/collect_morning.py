"""
collect_morning.py — WS3 morning status writer (ADR-013), generalized (WS3b, issue #268
Phase A) to serve BOTH provisional sessions: `morning` (10:05 ET, default) and `pre_close`
(15:30 ET, `--session pre_close`). Kept under this filename per the WS3b spec's lower-churn
guidance (`planning/ws3b-preclose-surface-spec.md` §4) — the workflow/tests reference it and
a rename buys nothing. The pure/impure split is real (load -> fetch -> build -> write), but
`fetch_ticker_quotes` is exercised only via fixtures in this phase — live scrape wiring + the
cron job are Phase B (`collect_morning.yml`, `--dry-run` first, per ADR-013 Decision 6).

Writes a PROVISIONAL store (`data/picks/sessions/<session>*.csv`) — never the settled
snapshot/delta/picks files. `session_config.assert_provisional(session)` is called at the
write boundary (write_store) per ADR-011's enforcement point, generalized to whichever
session is active (previously hardcoded to "morning").

Must run on GitHub Actions (Azure IPs) once Phase B wires the live scrape — Cloudflare
blocks headless Chromium from Google Cloud IPs, same constraint as collect.py/collect_picks.py.
"""

import csv
import json
import math
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import probe_picks  # noqa: E402  (reuse _parse_table, PAGE_SIZE, SCREENER_TABLE_SELECTOR)
import replay_picks  # noqa: E402  (reuse the server-side Focus reconstruction — issue #293)
import session_config  # noqa: E402
from collect import NYSE_HOLIDAYS, _is_trading_day  # noqa: E402  (reuse holiday table only — NOT trading_date's rollback)
from pick_status import (  # noqa: E402
    compute_pick_status, compute_atr_from_lod, matched_reclaim_ref,
    ACTIONABLE_STATUSES, STATUS_RECLAIM,
)

# NOTE: `collect_held.py` imports FROM this module (CONFIG_PATH, _to_float,
# fetch_ticker_quotes) — importing `collect_held._authed_request` back here would
# create an import cycle. Per the P2 spec's explicit fallback, `_authed_request` is
# replicated verbatim below (same UA/Bearer pattern, same worker, same auth) rather
# than imported. Keep the two copies in sync if the auth pattern ever changes.

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).parent.parent
DATA_DIR = BASE_DIR / "data"
PICKS_DIR = DATA_DIR / "picks"
SESSIONS_DIR = PICKS_DIR / "sessions"

CONFIG_PATH = PICKS_DIR / "screener_config.json"
PICKS_LATEST_PATH = PICKS_DIR / "picks_latest.csv"

# Provisional morning store (ADR-013 Decision 4). append-only history + latest-date slice.
# Kept as module-level constants (rather than only a function) so existing callers/tests
# that reference cm.MORNING_STORE / cm.MORNING_LATEST directly keep working unchanged.
MORNING_STORE = SESSIONS_DIR / "morning.csv"
MORNING_LATEST = SESSIONS_DIR / "morning_latest.csv"


def session_store_paths(session: str) -> tuple:
    """Return (store_path, latest_path) for a given session key (WS3b, issue #268).

    Derives `data/picks/sessions/<session>.csv` / `<session>_latest.csv` from the
    current `SESSIONS_DIR` (not a hardcoded morning path), so `pre_close` gets its
    own store with the identical schema/dedup convention, and tests that monkeypatch
    `SESSIONS_DIR` transparently redirect every session's paths, not just morning's.
    """
    return SESSIONS_DIR / f"{session}.csv", SESSIONS_DIR / f"{session}_latest.csv"

# Store schema — exact column order (ADR-013 Decision 4). `session` is redundant with
# the filename on purpose: rows stay self-describing once sessions are concatenated
# later (session_config.PROVISIONAL_KEY_PREFIX == ("date", "session")).
# WIDE_SCRAPE_BLOCK — which screener_config.json block the morning/pre_close scrape renders.
# A-1 decision (2026-09-01, planning/compression-expansion-ideation.md §7.3a): the Morning-family
# cards need the wide volatility/setup columns, so the morning run scrapes the full 84-column block
# instead of the legacy 9-column "morning" block. "held" is the proven 84-col t=-filtered config
# (empty base_filters, same columns as "wide") already run in prod by collect_held.py — reused
# here rather than adding a duplicate block. This does NOT change the scrape's Cloudflare exposure:
# fetch_ticker_quotes' page.goto count is driven by ticker count (batched ≤50, 20 rows/page), not
# column count — only the c= param and the per-page payload size differ. The legacy "morning" block
# stays in screener_config.json as documentation of the minimal status set (unused by the live run).
WIDE_SCRAPE_BLOCK = "held"

# SETUP_COLUMNS — wide scraped columns carried through into the session store (beyond the 9 status
# fields) so the PWA can render the "Volatility & setup" (B-1) section on Morning-family cards from
# the morning store directly, at 100% coverage and with fresh this-morning values (vs. a client-side
# cross-ref to last night's picks_latest that leaves ~⅓ of morning tickers blank — see §7.3a).
# Stored under their verbatim Finviz labels (not lowercased) so the PWA render can read them by the
# SAME keys it already uses on picks_latest rows — render symmetry with the cross-ref path. Values
# are carried through as the raw scraped strings (e.g. "3.92%", "-7.99%"), matching picks_latest.
# Adding a column here is a two-way-door superset migration (write_store backfills "" on old rows);
# removing one is one-way once data flows. 3-places documented (in-code here + README § Configurable
# parameters + scripts/CLAUDE.md § WS3 morning status). Extend as later B slices reach these cards.
SETUP_COLUMNS = ["RSI", "Volatility W", "Volatility M", "Rel Volume", "52W High"]

STORE_COLUMNS = [
    "date", "session", "collected_at", "ticker", "group", "list_category",
    "trigger", "stop", "atr", "price", "open", "high", "low", "change",
    "status", "atr_from_lod",
    # reclaim attribution (2026-08-27): which reference a reclaim row fired against
    # ("prior_low" | "sma50") and that level's value, for the PWA's "Reclaimed <level>"
    # copy. Blank on every non-reclaim row. Superset-additive: write_store rewrites the
    # whole file each run and backfills "" for these on pre-existing rows via r.get(col, ""),
    # so no separate ensure/migration step is needed (same two-way-door pattern as grp_*).
    "reclaim_ref", "reclaim_ref_value",
    # A-1 (2026-09-01) volatility/setup wide columns — see SETUP_COLUMNS above. Same
    # superset-additive two-way-door pattern: blank-backfilled on pre-A-1 rows by write_store.
    *SETUP_COLUMNS,
]

# URL-length safety: batch the scrape universe into chunks of <= 50 per `t=` screener
# URL (ADR-013 Decision 2 — batching is mandatory, not optional). Batching guarantees
# coverage regardless of size: every ticker lands in exactly one batch and is requested,
# so batch size only affects request *count*, never which names are fetched.
#
# WHY 50 (and NOT a multiple of PAGE_SIZE like 40/60): fetch_ticker_quotes paginates each
# batch with &r= until it sees a short page (< probe_picks.PAGE_SIZE == 20). A batch whose
# size is an exact multiple of 20 ends on a *full* 20-row page, so the loop can't tell it's
# done and issues one extra empty probe page — a wasted goto per full batch. 50 ends on a
# partial 10-row page (50 = 20+20+10), so it stops cleanly with no wasted probe. Empirically
# (issue #293, ~100 tickers/capped day) batch 50 = 6 gotos vs batch 60 = 7 — i.e. moving to
# 60 would *increase* Finviz requests, not cut them. Keep this at 50 unless you raise it all
# the way toward the batch = universe size (fewest batches), which trades URL length for it.
# Configurable constant — see README.md § Configurable parameters and
# scripts/CLAUDE.md § WS3 morning status for the other two required mentions.
MORNING_BATCH_SIZE = 50

# Scrape-universe narrowing (issue #293). picks_latest.csv carries the full daily picks
# list (observed 75–375 tickers/day) — too large to scrape efficiently and too large for a
# trader to act on. Instead of the full list, the morning run scrapes only the Focus view's
# top-N by focus_score, reconstructed server-side via replay_picks.replay(date, "focus").
#
# MORNING_FOCUS_TOP_N: hard cap on names scraped, taken best-first by focus_score. 100 fills
# a full strong list on rich days (cap binds ~17/31 sample days) without an unusable count.
# MORNING_FOCUS_SCORE_FLOOR: drop anything below this focus_score even when under the cap, so
# thin days self-trim instead of padding the list down to near-zero-conviction setups. At 0.3
# the sample universe becomes min 22 / median 95 / max 100 names/day. Both are display/scope
# knobs, not part of any settled artifact — safe to retune. 3-places documented per repo rule
# (in-code here + README § Configurable parameters + scripts/CLAUDE.md § WS3 morning status).
MORNING_FOCUS_TOP_N = 100
MORNING_FOCUS_SCORE_FLOOR = 0.3

# How stale picks_latest.csv is allowed to be (in trading sessions) before the
# morning run refuses to tag setups against it (ADR-013 Decision 4 stale-input guard).
MAX_STALE_SESSIONS = 5

SCREENER_BASE = "https://finviz.com/screener.ashx"

# P2 (WS5 §8b watchlist build brief §3/§4c/§4d/§5): watchlist union into the morning
# scrape universe. Same `finviz-positions` Worker as collect_held.py, distinct routes.
WATCHLIST_TICKERS_PATH = "/watchlist-tickers"
WATCHLIST_TICK_PATH = "/watchlist/tick"


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def build_ticker_url(config: dict, tickers: list, offset: int = 1, block: str = "morning") -> str:
    """Build a `t=`-filtered screener URL from a named config block.

    `block` selects which block of screener_config.json to render — "morning" (WS3,
    9 narrow status columns) or "held" (WS5 phase 2, the full 84-column scrape,
    issue #297). Both are `t=`-filtered with empty base_filters so exactly the given
    tickers return, regardless of cap/volume/52w-high status. offset is the &r=
    pagination parameter (1-based; page 2 = r=21, ...), same convention as
    probe_picks._build_url. No &f= is emitted when base_filters is empty.
    """
    cfg = config[block]
    col_ids = ",".join(str(c["id"]) for c in cfg["columns"])
    t_str = ",".join(tickers)
    url = (
        f"{SCREENER_BASE}"
        f"?v={cfg['v']}"
        f"&t={t_str}"
    )
    if cfg["base_filters"]:
        f_str = ",".join(cfg["base_filters"])
        url += f"&f={f_str}"
    url += f"&ft={cfg['ft']}" f"&c={col_ids}" f"&r={offset}"
    return url


def _batched(items: list, size: int) -> list:
    """Split items into consecutive chunks of at most `size`."""
    return [items[i:i + size] for i in range(0, len(items), size)]


def fetch_ticker_quotes(page, tickers: list, config: dict, block: str = "morning") -> list:
    """Fetch quote rows for `tickers` via a named screener config block, batched.

    Chunks `tickers` into MORNING_BATCH_SIZE-sized batches, and within each batch
    paginates with &r= (probe_picks.PAGE_SIZE=20 rows/page) exactly mirroring
    probe_picks._scrape_group's loop. Returns a flat list of row dicts keyed by the
    scraped Finviz labels — for `block="morning"` that is the 9 status columns
    (Ticker, Prev Close, Open, High, Low, Price, Change, ATR, Volume); for
    `block="held"` (WS5 phase 2) it is the full 84-column scrape (#297).

    Shared component (ADR-013 Decision 2): WS3b and WS5's held-tickers feed call
    this — WS3 with the default `block="morning"`, WS5 with `block="held"`. NOT
    exercised against live Finviz in Phase A — only via fixtures in tests, since
    Cloudflare blocks this from a cloud dev session. `page` is a Playwright Page
    (or, in tests, a stub exposing .goto/.wait_for_selector/.content).
    """
    all_rows: list = []
    for batch in _batched(tickers, MORNING_BATCH_SIZE):
        offset = 1
        while True:
            url = build_ticker_url(config, batch, offset=offset, block=block)
            page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            try:
                page.wait_for_selector(probe_picks.SCREENER_TABLE_SELECTOR, timeout=30_000)
            except Exception as exc:
                # An out-of-range/empty result page may not render the table shell.
                # Mirror probe_picks._scrape_group: fall through to parse (0 rows ->
                # break) rather than letting the exception crash the whole run and
                # drop every *later* batch's names. "No names lost" protection.
                # Log it (like probe_picks' WARNING) so a Cloudflare block / network
                # stall on a batch is distinguishable in CI logs from a genuinely
                # empty page — batch[0]..batch[-1] identifies which chunk stalled.
                print(f"  WARNING: '{probe_picks.SCREENER_TABLE_SELECTOR}' not found "
                      f"after 30s for batch {batch[0]}..{batch[-1]} (r={offset}): {exc}",
                      file=sys.stderr)
            html = page.content()
            _hdrs, rows = probe_picks._parse_table(html)
            if not rows:
                break
            all_rows.extend(rows)
            if len(rows) < probe_picks.PAGE_SIZE:
                break
            offset += probe_picks.PAGE_SIZE
    return all_rows


def _to_float(x):
    """Parse a Finviz-scraped numeric string (or already-numeric value) to float.

    Empty string / None / unparseable -> None (never raises). Strips a trailing
    '%' since some columns (e.g. Change) are percent-formatted.
    """
    if x is None:
        return None
    if isinstance(x, float):
        return None if math.isnan(x) else x
    s = str(x).strip()
    if s in ("", "-"):
        return None
    s = s.rstrip("%").replace(",", "")
    try:
        return float(s)
    except ValueError:
        return None


def _authed_request(url: str, token: str, method: str = "GET", body: bytes = None):
    """UA+Bearer request helper — replicated verbatim from `collect_held.py` (see the
    import-cycle note near the top of this module for why it's a copy, not an import).
    """
    req = urllib.request.Request(url, data=body, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    # Cloudflare's Bot Fight Mode blocks the default "Python-urllib/x.y" User-Agent with a
    # generic 403 (error code 1010) on workers.dev zones, before the request ever reaches the
    # Worker's own auth code — verified live 2026-08-13. A non-generic UA (anything not matching
    # python-urllib/python-requests/curl/scrapy signatures) clears it.
    req.add_header("User-Agent", "finviz-groups-tracker-morning-feed/1.0")
    if body is not None:
        req.add_header("Content-Type", "application/json")
    return urllib.request.urlopen(req, timeout=30)


def build_watch_levels(watch_refs: list) -> list:
    """Map the `/watchlist-tickers` payload to `pick_levels`-shaped dicts (P2).

    PURE. Input rows: `{ticker, level_type, has_history, prior_high, prior_low, atr, sma20,
    sma50}` (P1's `/watchlist-tickers` response — note `level_value` is deliberately absent
    from that payload; the user's chosen level is never sent to this public store).
    Output rows mirror `load_pick_levels`'s shape plus `ref`/`has_history` keys:

      {ticker, group: "", list_category: "watchlist",
       trigger: prior_high, stop: prior_low, atr: atr, ref: sma50, has_history: bool}

    `ref` is the SYSTEM-read reclaim level — always the ticker's 50-day MA,
    independent of the watch entry's own `level_type` (lead decision 1: the user's
    reclaim_20ma/reclaim_50ma overlay is a separate client-side P3 concern, not this
    system read). Every numeric field is run through `_to_float` (payload values may
    already be numbers or None — Worker JSON round-trips numbers fine, but stay defensive).

    `has_history` (WS-POSITIONS-STATUS, 2026-08-25) threads straight through to
    `compute_pick_status`'s `has_history` param — True/False as returned by the Worker,
    or None if the key is absent (an older, not-yet-deployed Worker), which safely falls
    back to today's `STATUS_NO_QUOTE` behavior rather than guessing.

    A row with a null/None prior_high/prior_low/atr/sma50 is KEPT, not dropped — its
    status just resolves to awaiting_first_read/no_quote/setting_up naturally downstream
    (same contract as `load_pick_levels`'s missing-value handling). Only a blank/missing
    ticker is skipped (unusable as a row key).
    """
    levels = []
    for r in watch_refs:
        ticker = r.get("ticker") or ""
        if not ticker:
            continue
        levels.append({
            "ticker": ticker,
            "group": "",
            "list_category": "watchlist",
            "trigger": _to_float(r.get("prior_high")),
            "stop": _to_float(r.get("prior_low")),
            "atr": _to_float(r.get("atr")),
            "ref": _to_float(r.get("sma50")),
            "has_history": r.get("has_history"),
        })
    return levels


def union_watch_levels(pick_levels: list, watch_levels: list) -> tuple:
    """Union watch tickers into the Focus pick_levels universe, de-duping by ticker.

    PURE. Returns `(levels, tickers)` — `levels` is `pick_levels` plus any
    `watch_levels` rows whose ticker is NOT already present in `pick_levels`;
    `tickers` is the corresponding ticker list for the scrape (each ticker appears
    exactly once). A ticker that is BOTH a Focus pick and a watch entry keeps the
    Focus pick's level dict (it carries a real group/list_category for attribution;
    the watch dup contributes nothing) — the watchlist union only ever ADDS names
    that aren't already in the Focus universe, never a second row for one already
    there. Order is preserved: pick_levels first (Focus order), then new watch
    additions in their given order.
    """
    seen = {lvl["ticker"] for lvl in pick_levels if lvl.get("ticker")}
    levels = list(pick_levels)
    for lvl in watch_levels:
        ticker = lvl.get("ticker")
        if not ticker or ticker in seen:
            continue
        seen.add(ticker)
        levels.append(lvl)
    tickers = [lvl["ticker"] for lvl in levels if lvl.get("ticker")]
    return levels, tickers


def fetch_watchlist_tickers(worker_url: str, token: str) -> list:
    """GET {worker_url}/watchlist-tickers -> list of watch-ref row dicts (P2).

    IMPURE, NON-FATAL (brief §4d): unlike collect_held.py's fetch_held_tickers (which
    exits 1 loud on any failure, since the held feed has no fallback), a watchlist
    hiccup must NEVER drop the picks morning run — the watchlist is an ADDITIVE
    union on top of the Focus universe, so on ANY error (HTTPError, network failure,
    non-200, malformed JSON) this prints a loud stderr warning and returns `[]`,
    letting main() proceed with the Focus-only universe exactly as it would have
    pre-P2.
    """
    url = worker_url.rstrip("/") + WATCHLIST_TICKERS_PATH
    try:
        with _authed_request(url, token) as resp:
            status = resp.status
            data = json.loads(resp.read().decode("utf-8"))
        if status != 200:
            print(f"GET {WATCHLIST_TICKERS_PATH} returned HTTP {status} — "
                  f"skipping the watchlist union for this run.", file=sys.stderr)
            return []
        return data.get("tickers", [])
    except Exception as exc:
        print(f"GET {WATCHLIST_TICKERS_PATH} failed: {exc} — skipping the "
              f"watchlist union for this run (non-fatal, picks-only fallback).",
              file=sys.stderr)
        return []


def should_tick_watchlist(session: str) -> bool:
    """True if `session` is one that decrements the watchlist TTL (WS3b, issue #268).

    Pure gate around session_config.WATCHLIST_TICK_SESSIONS — kept as its own function
    (rather than an inline comparison in main()) so it's independently unit-testable
    without exercising the rest of main()'s scrape/write flow.
    """
    return session in session_config.WATCHLIST_TICK_SESSIONS


def post_watchlist_tick(worker_url: str, token: str, date: str) -> "dict | None":
    """POST {worker_url}/watchlist/tick {"date": date} -> parsed response dict, or
    None on any failure (P2).

    IMPURE, NON-FATAL: the tick decrements each watch entry's TTL for `date`. It is
    idempotent server-side and self-heals — a missed tick just means a TTL doesn't
    decrement that particular day, which is strictly better than failing the whole
    run (and the exit code) AFTER the status store has already been written
    successfully. So this never raises/exits; it logs and returns None on error.
    """
    url = worker_url.rstrip("/") + WATCHLIST_TICK_PATH
    body = json.dumps({"date": date}).encode("utf-8")
    try:
        with _authed_request(url, token, method="POST", body=body) as resp:
            status = resp.status
            data = json.loads(resp.read().decode("utf-8"))
        if status != 200:
            print(f"POST {WATCHLIST_TICK_PATH} returned HTTP {status} — "
                  f"tick not recorded for {date} (non-fatal).", file=sys.stderr)
            return None
        return data
    except Exception as exc:
        print(f"POST {WATCHLIST_TICK_PATH} failed: {exc} — tick not recorded for "
              f"{date} (non-fatal; idempotent, self-heals on a future run).",
              file=sys.stderr)
        return None


def select_focus_universe(focus_df, top_n=MORNING_FOCUS_TOP_N,
                          floor=MORNING_FOCUS_SCORE_FLOOR) -> list:
    """Return the ordered ticker list to scrape from a replay Focus view (issue #293).

    `focus_df` is the DataFrame from `replay_picks.replay(date, view="focus")` (already
    sorted focus_score desc), or any object with `ticker` and `focus_score` columns.
    Keeps rows with `focus_score >= floor`, then takes the top `top_n` by score. Returns
    a list of tickers in best-first order so a partial/failed scrape captures the strongest
    names first. Empty input (or all rows below the floor) -> []. PURE — no I/O.
    """
    if focus_df is None or len(focus_df) == 0 or "ticker" not in focus_df.columns:
        return []
    df = focus_df.copy()
    df["_score"] = pd.to_numeric(df["focus_score"], errors="coerce")
    df = df[df["_score"] >= floor]
    # Dedupe by ticker BEFORE capping: replay/picks rows are keyed
    # (date, list_category, ticker), so a ticker tagged under multiple buckets
    # appears multiple times (same score). Without this, one ticker eats >1 of the
    # top_n slots — shrinking unique coverage below top_n and double-listing it in
    # the scrape. keep="first" after the desc sort retains its highest-scoring copy.
    df = df.sort_values("_score", ascending=False, kind="stable")
    df = df.drop_duplicates(subset="ticker", keep="first").head(top_n)
    return [t for t in df["ticker"].tolist() if t]


def load_pick_levels(picks_latest) -> list:
    """Extract per-ticker reference levels from picks_latest's most-recent date.

    `picks_latest` may be a path (str/Path) to picks_latest.csv, or an already-
    loaded list of dict rows (e.g. from csv.DictReader) — either is accepted so
    tests can pass an in-memory fixture without touching the filesystem.

    Returns one dict per ticker: ticker, group, list_category, trigger (=today's
    reference High as float), stop (=reference Low as float), atr (float), and
    reclaim_refs (ordered [(label, value), ...] undercut-and-reclaim candidates — see
    `_pick_reclaim_refs`). Rows with an unparseable date are skipped; only the max
    date's rows are used.
    Missing/NaN High/Low/ATR are carried through as None (not dropped) — a
    ticker with no usable trigger/stop still gets a no_quote-worthy row.
    """
    if isinstance(picks_latest, (str, Path)):
        with open(picks_latest, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
    else:
        rows = list(picks_latest)

    if not rows:
        return []

    max_date = max(r["date"] for r in rows if r.get("date"))
    levels = []
    for r in rows:
        if r.get("date") != max_date:
            continue
        stop = _to_float(r.get("Low"))
        levels.append({
            "ticker": r.get("ticker", ""),
            "group": r.get("group", ""),
            "list_category": r.get("list_category", ""),
            "trigger": _to_float(r.get("High")),
            "stop": stop,
            "atr": _to_float(r.get("ATR")),
            "reclaim_refs": _pick_reclaim_refs(r, stop),
        })
    return levels


def _pick_reclaim_refs(row: dict, stop) -> list:
    """Ordered reclaim candidates for a Pick: [("prior_low", <Low>), ("sma50", <abs 50MA>)].

    A Pick's undercut-and-reclaim fires against EITHER its prior swing low OR its 50-day
    MA (owner decision 2026-08-27); order here IS the attribution precedence, so a name
    that reclaims both is credited to the prior low. Each candidate is omitted when its
    value can't be formed, so a row missing Low and/or SMA50 degrades cleanly to fewer
    (or zero) candidates rather than erroring.

    The 50MA is DERIVED from Finviz's `SMA50` column, which is a %-distance-from-price
    string (e.g. "19.32%" = price sits 19.32% above the 50MA), NOT an absolute level:
    `sma50 = Price / (1 + SMA50%/100)`. Both `Price` and `SMA50` are the picks_latest
    prior-EOD capture, so this 50MA is ~1 trading session stale by the morning read — an
    accepted approximation (owner-confirmed 2026-08-27): the 50MA moves only cents/day,
    and the morning scrape's narrow block carries no fresh MA to use instead.
    """
    refs = []
    if stop is not None:
        refs.append(("prior_low", stop))
    price_cap = _to_float(row.get("Price"))
    sma50_pct = _to_float(row.get("SMA50"))
    if price_cap is not None and sma50_pct is not None:
        denom = 1.0 + sma50_pct / 100.0
        if denom != 0:
            refs.append(("sma50", price_cap / denom))
    return refs


def build_status_rows(pick_levels: list, quotes: list, collected_at: str, date: str,
                       session: str = session_config.MORNING) -> list:
    """Join quotes to pick_levels by ticker and compute each row's status.

    PURE — the main in-cloud-tested function. `quotes` is the flat list returned
    by fetch_ticker_quotes (or an equivalent fixture); tickers with no matching
    quote row, or an unparseable price/open/high/low, get status=no_quote via
    compute_pick_status's own missing-value check. atr_from_lod is computed only
    for actionable statuses (triggered/gapped_through/reclaim) per ADR-013
    Decision 3 (extended by P2 lead decision 2) — left as "" otherwise, matching
    the CSV empty-value convention.

    Reclaim refs: Focus pick levels carry `reclaim_refs` (ordered prior_low + derived
    50MA — 2026-08-27); watch levels carry the scalar `ref=sma50`. `compute_pick_status`
    prefers `reclaim_refs` when present, else `ref`; a level with neither never reclaims.
    On a reclaim row the fired reference is re-derived via `matched_reclaim_ref` (the same
    helper the engine used) into the `reclaim_ref`/`reclaim_ref_value` columns.

    `has_history=lvl.get("has_history")` (WS-POSITIONS-STATUS): same pattern — Focus
    pick levels have no `has_history` key so `.get` returns None and
    compute_pick_status's missing-inputs gate always resolves to STATUS_NO_QUOTE for
    them, unchanged. Watch levels carry a real True/False from the Worker.
    """
    quotes_by_ticker = {q.get("Ticker"): q for q in quotes if q.get("Ticker")}

    rows = []
    for lvl in pick_levels:
        ticker = lvl["ticker"]
        q = quotes_by_ticker.get(ticker)

        price = _to_float(q.get("Price")) if q else None
        open_ = _to_float(q.get("Open")) if q else None
        high = _to_float(q.get("High")) if q else None
        low = _to_float(q.get("Low")) if q else None
        change = _to_float(q.get("Change")) if q else None

        status = compute_pick_status(lvl["trigger"], lvl["stop"], price, open_, high, low,
                                      ref=lvl.get("ref"), has_history=lvl.get("has_history"),
                                      reclaim_refs=lvl.get("reclaim_refs"))

        atr_from_lod = None
        if status in ACTIONABLE_STATUSES:
            atr_from_lod = compute_atr_from_lod(price, low, lvl["atr"])

        # On a reclaim row, re-derive WHICH reference fired (same helper the engine used,
        # so the two can't diverge) for the PWA's "Reclaimed <level>" copy. Picks carry
        # `reclaim_refs`; watch rows carry the scalar `ref` (the 50MA) — normalize both to
        # the candidate list `compute_pick_status` itself built. Blank on non-reclaim rows.
        reclaim_ref, reclaim_ref_value = "", ""
        if status == STATUS_RECLAIM:
            candidates = lvl.get("reclaim_refs")
            if candidates is None and lvl.get("ref") is not None:
                candidates = [("sma50", lvl["ref"])]
            matched = matched_reclaim_ref(price, low, lvl["stop"], candidates or [])
            if matched:
                reclaim_ref, reclaim_ref_value = matched[0], _fmt(matched[1])

        row = {
            "date": date,
            "session": session,
            "collected_at": collected_at,
            "ticker": ticker,
            "group": lvl["group"],
            "list_category": lvl["list_category"],
            "trigger": _fmt(lvl["trigger"]),
            "stop": _fmt(lvl["stop"]),
            "atr": _fmt(lvl["atr"]),
            "price": _fmt(price),
            "open": _fmt(open_),
            "high": _fmt(high),
            "low": _fmt(low),
            "change": _fmt(change),
            "status": status,
            "atr_from_lod": _fmt(atr_from_lod),
            "reclaim_ref": reclaim_ref,
            "reclaim_ref_value": reclaim_ref_value,
        }
        # A-1 (2026-09-01): carry the wide volatility/setup columns through verbatim from the
        # scraped quote (raw Finviz strings, keyed by Finviz label — render symmetry with
        # picks_latest). Blank when the scrape had no match or predates the wide scrape (e.g. an
        # older 9-column fixture); the store schema is a superset so the column still exists.
        for col in SETUP_COLUMNS:
            row[col] = (q.get(col) if q else "") or ""
        rows.append(row)
    return rows


def _trading_sessions_between(start_date, end_date) -> int:
    """Count trading days strictly between start_date and end_date (exclusive of
    start, inclusive of end), via collect._is_trading_day. Used for the
    MAX_STALE_SESSIONS guard — picks_latest more than N trading sessions behind
    today means the reference levels are too old to trust for morning tagging.
    """
    from datetime import timedelta
    n = 0
    d = start_date + timedelta(days=1)
    while d <= end_date:
        if _is_trading_day(d):
            n += 1
        d += timedelta(days=1)
    return n


def _fmt(x):
    """NaN/None -> '', else pass the value through (data-pipeline.md convention)."""
    if x is None:
        return ""
    if isinstance(x, float) and math.isnan(x):
        return ""
    return x


# ---------------------------------------------------------------------------
# Writer (impure)
# ---------------------------------------------------------------------------


def _read_existing(path: Path) -> list:
    if not path.exists():
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_store(rows: list, session: str = session_config.MORNING) -> None:
    """Dedup last-write-wins per (date, ticker) into the session's store; rewrite
    the session's `*_latest` file as the max-date slice. Same convention as
    picks.csv: collected_at is NOT part of the uniqueness key.

    Calls session_config.assert_provisional(session) first — the ADR-011
    enforcement point; morning was the first writer to actually use it (ADR-013),
    generalized here (WS3b, issue #268) to whichever provisional session is active.

    `session` defaults to "morning" and, for that default only, writes to the
    module-level MORNING_STORE/MORNING_LATEST constants (regression guard: this
    keeps the pre-WS3b morning code path byte-identical, including for callers/
    tests that monkeypatch those two attributes directly). Any other session
    (e.g. "pre_close") derives its store paths from `session_store_paths(session)`
    instead — same schema, same dedup convention, a session-keyed file pair.
    """
    session_config.assert_provisional(session)

    if not rows:
        return

    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)

    if session == session_config.MORNING:
        store_path, latest_path = MORNING_STORE, MORNING_LATEST
    else:
        store_path, latest_path = session_store_paths(session)

    existing = _read_existing(store_path)
    by_key = {(r["date"], r["ticker"]): r for r in existing}
    for r in rows:
        by_key[(r["date"], r["ticker"])] = r

    all_rows = sorted(by_key.values(), key=lambda r: (r["date"], r["ticker"]))
    with open(store_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=STORE_COLUMNS)
        writer.writeheader()
        for r in all_rows:
            writer.writerow({col: r.get(col, "") for col in STORE_COLUMNS})

    max_date = max(r["date"] for r in all_rows)
    latest_rows = [r for r in all_rows if r["date"] == max_date]
    with open(latest_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=STORE_COLUMNS)
        writer.writeheader()
        for r in latest_rows:
            writer.writerow({col: r.get(col, "") for col in STORE_COLUMNS})


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    import argparse
    import json
    import pytz

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                         help="Scrape + parse + print row counts; do not write the store.")
    parser.add_argument("--session", choices=[session_config.MORNING, session_config.PRE_CLOSE],
                         default=session_config.MORNING,
                         help="Which provisional session to capture (WS3b, issue #268). "
                              "Defaults to 'morning' — behavior is unchanged from pre-WS3b "
                              "for that default. 'pre_close' writes the same schema to "
                              "data/picks/sessions/pre_close{,_latest}.csv instead.")
    args = parser.parse_args()
    session = args.session

    et = pytz.timezone("America/New_York")
    now_et = datetime.now(et)
    today = now_et.date()

    # Guard (a): non-trading day -> exit 0 WITHOUT writing. Deliberately does NOT
    # import/reuse collect.trading_date()'s rollback — a morning run on a closed
    # day has no live session to snapshot; rolling back would mis-tag yesterday's
    # setups under today (ADR-013 Decision 4).
    if today.weekday() >= 5:
        print(f"{today} is a weekend — no morning session to capture. Exiting 0.")
        sys.exit(0)
    if today.strftime("%Y-%m-%d") in NYSE_HOLIDAYS:
        print(f"{today} is an NYSE holiday — no morning session to capture. Exiting 0.")
        sys.exit(0)
    if not _is_trading_day(today):
        print(f"{today} is not a trading day — no morning session to capture. Exiting 0.")
        sys.exit(0)

    # Guard (b): picks_latest must be strictly before today, and not stale by more
    # than MAX_STALE_SESSIONS trading sessions -> exit 1 LOUD, no write.
    pick_levels = load_pick_levels(PICKS_LATEST_PATH)
    if not pick_levels:
        print("picks_latest.csv is empty — cannot tag morning statuses.", file=sys.stderr)
        sys.exit(1)

    with open(PICKS_LATEST_PATH, newline="", encoding="utf-8") as f:
        picks_max_date = max(r["date"] for r in csv.DictReader(f) if r.get("date"))

    today_str = today.strftime("%Y-%m-%d")
    if picks_max_date >= today_str:
        print(f"picks_latest.csv max date {picks_max_date} is not strictly before "
              f"today {today_str} — refusing to write.", file=sys.stderr)
        sys.exit(1)

    picks_date = datetime.strptime(picks_max_date, "%Y-%m-%d").date()
    stale_sessions = _trading_sessions_between(picks_date, today)
    if stale_sessions > MAX_STALE_SESSIONS:
        print(f"picks_latest.csv is stale ({stale_sessions} trading sessions old, max "
              f"date {picks_max_date}) — refusing to write.", file=sys.stderr)
        sys.exit(1)

    # Narrow the scrape universe to the Focus view's top-N (issue #293). Reconstruct
    # the Focus view server-side for picks_max_date and keep only its top-N tickers
    # (>= floor). The Focus set is a subset of picks_latest's tickers by construction
    # (replay reads the same date's rows through the base + DQ filter), so reordering
    # pick_levels to Focus order also intersects — trigger/stop/atr still come from
    # picks_latest. replay failure is a LOUD exit (never silently scrape the full list).
    try:
        focus_df = replay_picks.replay(date=picks_max_date, view="focus")
    except Exception as exc:
        print(f"replay_picks.replay failed for {picks_max_date}: {exc} — refusing to "
              f"fall back to the full picks list.", file=sys.stderr)
        sys.exit(1)

    focus_tickers = select_focus_universe(focus_df)
    levels_by_ticker = {lvl["ticker"]: lvl for lvl in pick_levels}
    pick_levels = [levels_by_ticker[t] for t in focus_tickers if t in levels_by_ticker]

    # P2 watchlist union (WS5 §8b build brief §4d) — done BEFORE the emptiness guard
    # below on purpose: a watch item rides the morning scrape independently of whether
    # any Focus pick qualified, so a thin/zero-Focus day must NOT blind the watchlist.
    # Both env vars must be set to participate — either missing means a picks-only run,
    # not an error (the morning job must not hard-require watchlist config to run).
    import os
    worker_url = os.environ.get("POSITIONS_WORKER_URL")
    token = os.environ.get("POSITIONS_INGEST_TOKEN")
    watchlist_configured = bool(worker_url and token)
    watch_levels = []
    if not watchlist_configured:
        print("POSITIONS_WORKER_URL/POSITIONS_INGEST_TOKEN not both set — "
              "skipping the watchlist union (picks-only run).")
    else:
        watch_refs = fetch_watchlist_tickers(worker_url, token)
        watch_levels = build_watch_levels(watch_refs)
    # union_watch_levels is a no-op passthrough when watch_levels is empty (picks-only
    # or a non-fatal fetch that returned []), so this call is unconditional.
    pick_levels, tickers = union_watch_levels(pick_levels, watch_levels)

    if not pick_levels:
        print(f"No Focus candidates at/above focus_score {MORNING_FOCUS_SCORE_FLOOR} "
              f"for {picks_max_date} and no active watchlist tickers — nothing to tag. "
              f"Exiting 0.")
        sys.exit(0)

    config = json.loads(CONFIG_PATH.read_text())

    print(f"Universe: {len(tickers)} tickers to scrape "
          f"({len(watch_levels)} from watchlist, rest Focus top {MORNING_FOCUS_TOP_N}/"
          f"floor {MORNING_FOCUS_SCORE_FLOOR}) from picks {picks_max_date}.")

    if args.dry_run:
        print(f"[dry-run] {len(tickers)} tickers to fetch, "
              f"{len(_batched(tickers, MORNING_BATCH_SIZE))} batch(es).")
        # Dry-run still exercises the real scrape+parse path per ADR-013 Decision 2
        # verification note — only the final write_store() call is skipped.

    from playwright.sync_api import sync_playwright  # guarded import, mirrors probe_picks.py
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
        quotes = fetch_ticker_quotes(page, tickers, config, block=WIDE_SCRAPE_BLOCK)
        browser.close()

    collected_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    rows = build_status_rows(pick_levels, quotes, collected_at, today_str, session=session)

    print(f"Built {len(rows)} status rows from {len(quotes)} quote rows.")

    if args.dry_run:
        print("[dry-run] not writing.")
        return

    write_store(rows, session=session)
    store_path, latest_path = (
        (MORNING_STORE, MORNING_LATEST) if session == session_config.MORNING
        else session_store_paths(session)
    )
    print(f"Wrote {len(rows)} rows to {store_path} and {latest_path}.")

    # P2: tick the watchlist TTL once the store write has succeeded. Reached only on
    # a real (non-dry-run) trading-day run past the emptiness guard, so `rows` is
    # non-empty here — never on a dry-run (early return above) and never on a
    # non-trading day (exit-0 guards at the top). TTL counts trading mornings only,
    # so `should_tick_watchlist(session)` (WS3b, issue #268) restricts this to the
    # sessions in session_config.WATCHLIST_TICK_SESSIONS (currently `morning` only) —
    # `pre_close` must not also tick the same day's TTL. The call itself is
    # idempotent + non-fatal.
    if watchlist_configured and should_tick_watchlist(session):
        tick_result = post_watchlist_tick(worker_url, token, today_str)
        if tick_result is not None:
            print(f"Watchlist tick recorded for {today_str}: {tick_result}")


if __name__ == "__main__":
    main()
