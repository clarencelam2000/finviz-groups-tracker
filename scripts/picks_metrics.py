"""
picks_metrics.py — per-row derived metrics for the stock-picks pipeline (Phase 3a).

Imported by collect_picks.py to compute the 5 backend metric columns (METRICS_COLS)
after scraping. Also imported by ensure_picks_csv() to back-fill them into any
existing picks.csv rows that predate the column addition.

Pure module — no Finviz access, no I/O. Fully tested in tests/test_picks_metrics.py.

Required reading: planning/stock-picks-from-leading-groups.md §Phase 3a (§§3a.0),
ADR-007 (selector policy), ADR-008 (collection architecture).
"""

import math

from picks_config import POWER_OF_3_ATR_MULT

# METRICS_COLS — the 6 backend-derived columns appended AFTER the 19 grp_* block.
# Computed from already-stored Finviz columns at write time; no selector_version bump
# needed (they are deterministic transforms of stored values, not selection-logic changes).
# Order is sticky — adding a new column is a two-way-door superset migration via
# ensure_picks_csv(); renaming/removing one is one-way once data flows.
# Triple-documented: here, README § Configurable parameters, CLAUDE.md § Picks pipeline.
METRICS_COLS = ["atr_ext_50", "risk_20ma_pct", "risk_50ma_pct", "range_atr", "stage2", "power_of_3"]

_NAN = float("nan")


def _pct(val) -> float:
    """Parse a Finviz percentage string → float (e.g., '3.52%' or '3.52' → 3.52).
    Blank, '-', or unparseable → NaN."""
    if val is None or val == "" or val == "-":
        return _NAN
    s = str(val).strip().rstrip("%")
    try:
        return float(s)
    except (ValueError, TypeError):
        return _NAN


def _cap_b(val) -> float:
    """Parse a Finviz market-cap string → float in $B.
    '208.34B' → 208.34; '1.23T' → 1230.0; '850M' → 0.85; '500K' → 0.0005.
    Blank, '-', or unparseable → NaN."""
    if val is None or val == "" or val == "-":
        return _NAN
    s = str(val).strip()
    suffixes = {"T": 1_000.0, "B": 1.0, "M": 0.001, "K": 0.000_001}
    if s and s[-1].upper() in suffixes:
        try:
            return float(s[:-1]) * suffixes[s[-1].upper()]
        except (ValueError, TypeError):
            return _NAN
    try:
        return float(s)
    except (ValueError, TypeError):
        return _NAN


def _float(val) -> float:
    """Parse a plain numeric column value. Blank, '-', None → NaN.
    Strips commas so '1,234.56' → 1234.56."""
    if val is None or val == "" or val == "-":
        return _NAN
    try:
        return float(str(val).strip().replace(",", ""))
    except (ValueError, TypeError):
        return _NAN


def _isnan(x) -> bool:
    return x is None or (isinstance(x, float) and math.isnan(x))


def compute_metrics_row(row: dict) -> dict:
    """Compute the 6 derived columns for one picks.csv row.

    Returns a dict with exactly the METRICS_COLS keys. Any blank/NaN/absent input
    propagates NaN for that metric; the function never raises.

    Formulas (ADR-008 / Phase 3a spec; power_of_3 is B-5, issue #379):
      SMA20/SMA50/SMA200 in picks.csv are the Finviz "% of price ABOVE that MA"
      columns (e.g., SMA50=3.52 means price is 3.52% above the 50MA). Reconstruct
      the dollar-level MA price as: sma_price = Price / (1 + SMA_pct/100).

      atr_ext_50   = (price − sma50_price) / ATR           [ATR multiples from 50MA]
      risk_20ma_pct = (price − sma20_price) / price        [fraction; display as % in PWA]
      risk_50ma_pct = (price − sma50_price) / price        [wider-stop alternative]
      range_atr    = (High − Low) / ATR                    [day tightness proxy, C1]
      stage2       = 1 if (SMA50 > 0) AND (SMA200 > SMA50) else 0
                   [SMA50>0 ↔ price>50MA; SMA200>SMA50 ↔ 50MA>200MA — proven equivalent]
      power_of_3   = 1 if max(price,sma20_price,sma50_price) − min(...) <=
                     POWER_OF_3_ATR_MULT × ATR else 0
                   [price/20MA/50MA all bunched inside one POWER_OF_3_ATR_MULT-wide ATR
                    band; NaN if price, sma20_price, sma50_price, or ATR is NaN, or ATR == 0]
    """
    price     = _float(row.get("Price"))
    atr       = _float(row.get("ATR"))
    high      = _float(row.get("High"))
    low       = _float(row.get("Low"))
    sma20_pct = _pct(row.get("SMA20"))
    sma50_pct = _pct(row.get("SMA50"))
    sma200_pct = _pct(row.get("SMA200"))

    # Reconstruct dollar-level MA prices from the Finviz "% above MA" columns.
    if not _isnan(price) and not _isnan(sma20_pct):
        sma20_price = price / (1.0 + sma20_pct / 100.0)
    else:
        sma20_price = _NAN

    if not _isnan(price) and not _isnan(sma50_pct):
        sma50_price = price / (1.0 + sma50_pct / 100.0)
    else:
        sma50_price = _NAN

    # atr_ext_50: CEO "rubber-band stretch" — ATR multiples from 50MA.
    if not _isnan(price) and not _isnan(sma50_price) and not _isnan(atr) and atr != 0.0:
        atr_ext_50 = (price - sma50_price) / atr
    else:
        atr_ext_50 = _NAN

    # risk_20ma_pct: fraction of price at risk if stopped at 20MA.
    if not _isnan(price) and not _isnan(sma20_price) and price != 0.0:
        risk_20ma_pct = (price - sma20_price) / price
    else:
        risk_20ma_pct = _NAN

    # risk_50ma_pct: wider-stop alternative.
    if not _isnan(price) and not _isnan(sma50_price) and price != 0.0:
        risk_50ma_pct = (price - sma50_price) / price
    else:
        risk_50ma_pct = _NAN

    # range_atr: day-range / ATR; small = quiet constructive bar (C1 tightness proxy).
    if not _isnan(high) and not _isnan(low) and not _isnan(atr) and atr != 0.0:
        range_atr = (high - low) / atr
    else:
        range_atr = _NAN

    # stage2: price above 50MA AND 50MA above 200MA.
    # Equivalently: SMA50_pct > 0 AND SMA200_pct > SMA50_pct.
    # Proof: sma50_price > sma200_price ↔ SMA200_pct > SMA50_pct (higher %-above = lower MA).
    if not _isnan(sma50_pct) and not _isnan(sma200_pct):
        stage2 = 1 if (sma50_pct > 0.0 and sma200_pct > sma50_pct) else 0
    else:
        stage2 = _NAN

    # power_of_3 (B-5, issue #379): 1 if price, the 20MA and the 50MA are all bunched
    # inside one POWER_OF_3_ATR_MULT×ATR-wide band; 0 otherwise; NaN if any input is
    # missing. Owner-specified band width (picks_config.POWER_OF_3_ATR_MULT), not an
    # invented cutoff — see that constant's comment for the doc §4.0 rationale.
    if (not _isnan(price) and not _isnan(sma20_price) and not _isnan(sma50_price)
            and not _isnan(atr) and atr != 0.0):
        spread = max(price, sma20_price, sma50_price) - min(price, sma20_price, sma50_price)
        power_of_3 = 1 if spread <= POWER_OF_3_ATR_MULT * atr else 0
    else:
        power_of_3 = _NAN

    return {
        "atr_ext_50":    atr_ext_50,
        "risk_20ma_pct": risk_20ma_pct,
        "risk_50ma_pct": risk_50ma_pct,
        "range_atr":     range_atr,
        "stage2":        stage2,
        "power_of_3":    power_of_3,
    }


def _hl_range(row) -> float:
    """Today's raw daily range = High − Low. NaN if either is missing/unparseable."""
    high = _float(row.get("High"))
    low = _float(row.get("Low"))
    if _isnan(high) or _isnan(low):
        return _NAN
    return high - low


def compute_trailing_setup(latest_rows, history_rows,
                           window=7, spark_window=10, spark_min=3):
    """Populate TRAILING_COLS (tight_range_7, range_atr_spark, atr_spark, relvol_spark) on each
    row in `latest_rows` IN PLACE, from that ticker's trailing available bars in `history_rows`.

    `history_rows` is the full picks.csv log; `latest_rows` are a subset of it (the max-date
    slice the PWA reads). Compression spine, Effort B / issue #379 — doc §5.4/§5.7/§3 (B-2:
    tight_range_7 + the two range/ATR sparks) and doc §5.2/§10.3 (B-3: relvol_spark, the volume
    dry-up trend — a SHOWN value, owner-named as the strongest/cheapest VCP sub-signal).

    picks.csv history is gappy per-ticker (a name only appears on days its group was
    selected), so "the last N bars" here means the last N AVAILABLE daily bars, NOT N
    guaranteed-consecutive trading days. The tight-range read is therefore over available
    bars and is labeled honestly by the PWA ("tightest range, last 7 bars"), never "NR7"
    (owner decision 2026-08-31). Per-name graceful degradation (doc §3): a column is ""
    (blank) when the ticker lacks enough bars, never a fabricated value.

    Pure — no I/O. Returns `latest_rows` (also mutated in place). Values written are
    CSV-ready (int 0/1, pipe-joined string, or "").
    """
    from collections import defaultdict

    # One representative bar per (ticker, date): a ticker can appear on the same date under
    # multiple list_category buckets (scraped once, tagged per bucket) — those rows share
    # identical High/Low/ATR/range_atr, so collapse to one bar per date to avoid
    # double-counting a single session in a trailing window.
    bars_by_ticker = defaultdict(dict)  # ticker -> {date: row}
    for r in history_rows:
        t = r.get("ticker")
        if t is None:
            continue
        bars_by_ticker[t][r.get("date", "")] = r  # identical values → last write wins

    for row in latest_rows:
        t = row.get("ticker")
        d = row.get("date", "")
        dates = sorted(dt for dt in bars_by_ticker.get(t, {}) if dt <= d)
        bars = [bars_by_ticker[t][dt] for dt in dates]

        # tight_range_7 (a FACT, doc §4.0): today's raw H−L range is the narrowest of the
        # last `window` available bars. "" when fewer than `window` bars exist, or when any
        # bar in the window is missing High/Low (can't fairly compare).
        tight = ""
        if len(bars) >= window:
            ranges = [_hl_range(b) for b in bars[-window:]]
            if not any(_isnan(x) for x in ranges):
                tight = 1 if ranges[-1] <= min(ranges) else 0
        row["tight_range_7"] = tight

        # *_spark (SHOWN values, doc §4.0): last ≤`spark_window` available values,
        # oldest→newest, pipe-joined. "" when fewer than `spark_min` valid points.
        def _series(col):
            vals = [_float(b.get(col)) for b in bars[-spark_window:]]
            vals = [v for v in vals if not _isnan(v)]
            if len(vals) < spark_min:
                return ""
            return "|".join(f"{v:.2f}" for v in vals)

        row["range_atr_spark"] = _series("range_atr")
        row["atr_spark"] = _series("ATR")
        # relvol_spark (B-3): the Rel Volume trend — volume dry-up shows as this series sloping
        # below 1.0 while the range tightens. A SHOWN value (doc §4.0), never gated to a flag.
        row["relvol_spark"] = _series("Rel Volume")

    return latest_rows
