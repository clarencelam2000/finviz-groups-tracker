"""
collect_picks.py — daily Stage-2 stock-picks scraper.

Pipeline (Phase 2 of planning/stock-picks-from-leading-groups.md):
  1. select_groups(deltas_df) — pure, no Finviz: read the latest
     data/industries/deltas.csv → leaders / emerging / accel / rs_new_high
     groups (≤ DAILY_GROUP_CAP unique), each tagged with a grp_* metric snapshot.
  2. For each selected group (priority order), paginate the Finviz screener
     (v=151 wide net, &r= walk) until an empty/short page or PAGE_CAP, stopping
     entirely at GLOBAL_FETCH_CAP pages.
  3. Append one row per (stock × list_category) to data/picks/picks.csv
     (dedup key (date, list_category, ticker); last-write-wins per date).
  4. Rewrite data/picks/picks_latest.csv (max-date slice → the PWA fetches this).
  5. Flip validated=true on groups that returned rows (G4).

Like collect.py, this MUST run on GitHub Actions (Azure IPs) — Cloudflare blocks
the headless scrape from Google Cloud IPs used in the cloud Claude env.

select_groups and the row-building / pagination helpers are pure and fully
unit-tested in tests/test_collect_picks.py (no Finviz access needed).

Required reading before editing: ADR-007 (selector policy) and ADR-008
(collection architecture) in knowledge/decisions/.
"""

import argparse
import csv
import math
import sys
import time
from datetime import datetime
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import picks_config as pc
from picks_config import (
    SELECTOR_VERSION,
    DAILY_GROUP_CAP,
    LEADER_SS_SLOTS,
    LEADER_MC_SLOTS,
    EMERGING_SLOTS,
    ACCEL_SLOTS,
    RS_NH_SLOTS,
    ALL_GREEN_SLOTS,
    ALL_GREEN_PERF_COLS,
    ANTIFLASH_PCTILE,
    EMERGING_REGIME_FLOOR,
    ACCEL_THRESHOLD,
    EMERGING_RS_FLOOR,
    ACCEL_RS_FLOOR,
    RS_NH_RS_FLOOR,
    PAGE_SIZE,
    PAGE_CAP,
    GLOBAL_FETCH_CAP,
    PAGE_DELAY_S,
)
from picks_metrics import METRICS_COLS, compute_metrics_row, compute_trailing_setup
# Inherit the pure scrape/url/parse helpers from the Phase-1 probe — no need to
# rewrite them. They are import-safe (Playwright is imported inside probe main()).
from probe_picks import slugify_industry, _build_url, _parse_table, SCREENER_TABLE_SELECTOR

BASE_DIR = Path(__file__).parent.parent
DELTAS_CSV = BASE_DIR / "data" / "industries" / "deltas.csv"
SNAPSHOTS_CSV = BASE_DIR / "data" / "industries" / "snapshots.csv"

# Top-40% floor means percentile rank >= (1 - ANTIFLASH_PCTILE).
_PCTILE_CUTOFF = 1.0 - ANTIFLASH_PCTILE

# Ticker-corruption guard (added after the 2026-07-15 incident where a Finviz
# markup change made every scraped Ticker cell read as "<first-letter><real
# ticker>", e.g. "HSBC" -> "HHSBC"). A real day's ticker list naturally has a
# small rate of tickers whose first two letters coincide (AA, EE, MMM, ...);
# measured baseline across 10 real trading days (2026-06-25 .. 2026-07-14) was
# 1-4%. 25% gives wide headroom above that noise while still catching this
# corruption class (which hits ~100% of rows) long before it reaches CSV.
TICKER_DUP_RATE_MAX = 0.25

# Single-char-ticker guard (issue #252 — the 2026-07-16 corruption where every
# scraped Ticker read as a single avatar letter, which ticker_dup_rate() is blind
# to because a 1-char string has no duplicated PAIR). A real day carries a few
# genuine 1-char tickers (C, F, V, A, ...): measured baseline 2026-07-09..07-15
# was ~1.3-1.4%. 30% sits far above that noise and far below the ~100% a fully
# corrupted run shows, giving clean separation.
TICKER_SHORT_RATE_MAX = 0.30

# Header-drift guard (PICKS-2-HDR). build_pick_rows maps scraped cells by the
# config's 84 header labels (stock.get(col, "")) — if Finviz renames a label so
# it no longer matches screener_config.json, every affected column writes BLANK
# silently onto the irreplaceable capture. Policy is tiered, because aborting
# the whole day over one renamed column would trade bounded column loss for
# total loss of that day's list:
#   - "Ticker" missing, or > HEADER_MISSING_ABORT_FRAC of expected labels
#     missing → the parse itself is untrustworthy → abort BEFORE write (exit 1,
#     CI red, debug HTML uploads).
#   - any smaller drift → WRITE the partial capture (most columns intact),
#     print the missing labels loudly, then exit 1 AFTER the write so CI still
#     goes red and a human fixes screener_config.json before the next run.
# 0.10 of 84 labels ≈ 8 columns: enough headroom that a cosmetic single-label
# rename never nukes a day, low enough that a structural table change does.
HEADER_MISSING_ABORT_FRAC = 0.10


def _f(val):
    """Format a value for CSV: NaN/None → '' (mirrors compute_deltas._fmt)."""
    if val is None:
        return ""
    if isinstance(val, float) and math.isnan(val):
        return ""
    return val


# ---------------------------------------------------------------------------
# Group selection (pure — fully testable against deltas.csv)
# ---------------------------------------------------------------------------

def _grp_snapshot(row, basis, category_rank, pctile):
    """Build the 19 grp_* snapshot fields for one group×category selection."""
    sum_mid = row["rank_month"] + row["rank_quarter"] + row["rank_half"]
    return {
        "grp_rank_basis": basis,
        "grp_category_rank": category_rank,
        "grp_sum_mid_rank": sum_mid,
        "grp_rank_month": row["rank_month"],
        "grp_rank_quarter": row["rank_quarter"],
        "grp_rank_half": row["rank_half"],
        "grp_momentum_confirmed": row.get("momentum_confirmed"),
        "grp_momentum_score": row.get("momentum_score"),
        "grp_momentum_score_pctile": pctile,
        "grp_momentum_accel": row.get("momentum_accel"),
        "grp_momentum_weighted_mid": row.get("momentum_weighted_mid"),
        "grp_rank_agreement": row.get("rank_agreement"),
        "grp_regime_short_long": row.get("regime_short_long"),
        "grp_rs_score": row.get("rs_score"),
        "grp_rs_agreement": row.get("rs_agreement"),
        "grp_rs_confirmed": row.get("rs_confirmed"),
        "grp_rs_accel": row.get("rs_accel"),
        "grp_rs_new_high": row.get("rs_new_high"),
        "grp_rs_slope": row.get("rs_slope"),
    }


def select_groups(deltas_df: pd.DataFrame) -> list:
    """Select leading groups for the latest date in deltas_df.

    Returns a list of selection dicts, one per (group × list_category), each with:
      group, list_category, selector_version, priority, + 19 grp_* fields.

    A group qualifying in multiple buckets is tagged once per bucket it qualifies
    for within that bucket's natural top-N (attribution is preserved — you can see
    a group is e.g. both a leader and accelerating), but only the FIRST time a
    group is added does it consume one of the bucket's N slots. If a bucket's
    natural top-N contains fewer than N groups that are new-to-today's-selection,
    the bucket keeps walking its ranked candidate list past rank N — skipping
    already-selected groups without tagging them there — until it has added N new
    groups or exhausted its qualifying pool. This is what backfill means below:
    duplicate groups no longer shrink a bucket's effective new-group yield (v2,
    see ADR-007 amendment). Applies to emerging/accel/rs_new_high; leaders' own
    freshness-fill sub-bucket already excludes the core 11 by construction.

    Buckets are filled in priority order; a 0-group bucket is normal (e.g.
    momentum_accel is NaN until 11 sessions exist) — fill from the next priority,
    total unique groups stays ≤ DAILY_GROUP_CAP, never error.

    NOTE on the all_green bucket (5th, lowest priority): it needs the raw
    perf_week/perf_month/perf_quarter/perf_half/perf_ytd columns, which live in
    snapshots.csv, NOT deltas.csv (deltas.csv only has ranks/deltas, never raw
    perf). Callers must merge those columns onto deltas_df before calling this
    function — main() does this from snapshots.csv; a deltas_df missing them
    makes all_green silently yield 0 groups rather than erroring (same
    graceful-degrade posture as every other bucket's NaN handling).

    Pure: no Finviz access. Replayable over any historical date in deltas.csv
    (+ snapshots.csv for all_green).
    """
    if deltas_df is None or len(deltas_df) == 0:
        return []

    latest = deltas_df[deltas_df["date"] == deltas_df["date"].max()].copy()
    if len(latest) == 0:
        return []

    # Cross-sectional momentum_score percentile (anti-flash floor). rank(pct=True)
    # gives 0..1; the top 40% are pctile >= 0.60. Invariant to formula rescaling.
    latest["_mpctile"] = latest["momentum_score"].rank(pct=True, ascending=True)
    pctile_by_group = dict(zip(latest["name"], latest["_mpctile"]))

    selections = []          # output rows (group × category)
    unique_groups = []       # ordered unique groups (counts toward the cap)

    def have_room_for_new() -> bool:
        return len(unique_groups) < DAILY_GROUP_CAP

    def add(name, category, basis, category_rank):
        """Add a tagged selection row. New groups consume a unique slot/cap."""
        is_new = name not in unique_groups
        if is_new and not have_room_for_new():
            return False
        if is_new:
            unique_groups.append(name)
        row = latest[latest["name"] == name].iloc[0]
        snap = _grp_snapshot(row, basis, category_rank, pctile_by_group.get(name))
        selections.append({
            "group": name,
            "list_category": category,
            "selector_version": SELECTOR_VERSION,
            "priority": len(selections) + 1,
            **snap,
        })
        return True

    def add_bucket_with_backfill(sorted_names, category, slots):
        """Tag a bucket's natural top-`slots` (attribution, dup or not), then
        backfill past rank `slots` — skipping already-selected groups — until
        `slots` NEW groups have been added or the candidate pool runs out."""
        new_count = 0
        for rank, name in enumerate(sorted_names, start=1):
            is_new = name not in unique_groups
            if rank <= slots:
                added = add(name, category, category, rank)
                if is_new and added:
                    new_count += 1
            else:
                if new_count >= slots:
                    break
                if not is_new:
                    continue
                if add(name, category, category, rank):
                    new_count += 1
                else:
                    break  # DAILY_GROUP_CAP hit — no point scanning for more new

    # ---- Priority 1: leaders (11 sustained_strength + 2 momentum_confirmed) ----
    latest["_sum_mid"] = (
        latest["rank_month"] + latest["rank_quarter"] + latest["rank_half"]
    )
    ss_ranked = latest.dropna(subset=["_sum_mid"]).sort_values("_sum_mid", ascending=True)
    core_names = list(ss_ranked["name"].head(LEADER_SS_SLOTS))
    for i, name in enumerate(core_names, start=1):
        add(name, "leaders", "sustained_strength", i)

    # Freshness fills: momentum_confirmed desc among groups NOT in the core 11.
    fresh_pool = latest[~latest["name"].isin(core_names)].dropna(
        subset=["momentum_confirmed"]
    ).sort_values("momentum_confirmed", ascending=False)
    for i, name in enumerate(list(fresh_pool["name"].head(LEADER_MC_SLOTS)), start=1):
        add(name, "leaders", "freshness_fill", i)

    # ---- Priority 2: emerging ----
    emerging = latest[
        (latest["regime_short_long"] > EMERGING_REGIME_FLOOR)
        & (latest["rs_score"] > EMERGING_RS_FLOOR)
    ].sort_values("regime_short_long", ascending=False)
    add_bucket_with_backfill(list(emerging["name"]), "emerging", EMERGING_SLOTS)

    # ---- Priority 3: accel ----
    accel = latest[
        (latest["momentum_accel"] > ACCEL_THRESHOLD)
        & (latest["_mpctile"] >= _PCTILE_CUTOFF)
        & (latest["rs_score"] > ACCEL_RS_FLOOR)
    ].sort_values("momentum_accel", ascending=False)
    add_bucket_with_backfill(list(accel["name"]), "accel", ACCEL_SLOTS)

    # ---- Priority 4: rs_new_high ----
    rs_nh = latest[
        (latest["rs_new_high"] == 1)
        & (latest["rs_score"] >= RS_NH_RS_FLOOR)
        & (latest["_mpctile"] >= _PCTILE_CUTOFF)
    ].sort_values("rs_slope", ascending=False)
    add_bucket_with_backfill(list(rs_nh["name"]), "rs_new_high", RS_NH_SLOTS)

    # ---- Priority 5: all_green (perf positive on every ALL_GREEN_PERF_COLS
    # timeframe — a pure consistency screen, no rs/strength floor of its own).
    # Lowest priority: fills last, so a group also qualifying for a
    # higher-priority bucket is claimed there first (intentional — higher-
    # conviction buckets get first pick). Requires perf_* columns merged in by
    # the caller (see docstring); missing columns degrade to 0 groups, not an
    # error, same as every other bucket's NaN handling.
    if all(c in latest.columns for c in ALL_GREEN_PERF_COLS):
        green_mask = pd.Series(True, index=latest.index)
        for col in ALL_GREEN_PERF_COLS:
            green_mask &= latest[col] > 0
        all_green = latest[green_mask].sort_values("momentum_score", ascending=False)
    else:
        all_green = latest.iloc[0:0]
    add_bucket_with_backfill(list(all_green["name"]), "all_green", ALL_GREEN_SLOTS)

    return selections


def selection_summary(selections: list) -> dict:
    """Per-bucket counts for the run summary (empty buckets are expected, G2)."""
    counts = {"leaders": 0, "emerging": 0, "accel": 0, "rs_new_high": 0, "all_green": 0}
    for s in selections:
        counts[s["list_category"]] = counts.get(s["list_category"], 0) + 1
    unique = len({s["group"] for s in selections})
    return {"by_category": counts, "unique_groups": unique, "total_rows": len(selections)}


# ---------------------------------------------------------------------------
# Pagination (pure — fetch_fn abstracts the network for testing)
# ---------------------------------------------------------------------------

def paginate_group(fetch_fn, ind_slug, page_cap=PAGE_CAP, max_pages=PAGE_CAP):
    """Walk &r= pages for one slug. fetch_fn(slug, offset) -> (header, rows).

    Stops at: an empty page, a short (< PAGE_SIZE) page, page_cap, or max_pages
    (the remaining global budget). Returns (header, all_rows, pages_used).
    A wrong slug returns HTTP 200 with an empty table → header == [] → 0 rows,
    surfaced by the caller as a suspect slug (G4: do NOT rely on HTTP status).
    """
    all_rows = []
    header = []
    offset = 1
    pages_used = 0
    limit = min(page_cap, max_pages)
    while pages_used < limit:
        hdrs, rows = fetch_fn(ind_slug, offset)
        pages_used += 1
        if pages_used == 1:
            header = hdrs
            if not hdrs:
                break  # wrong slug / 0 results (empty table, HTTP 200)
        if not rows:
            break
        all_rows.extend(rows)
        if len(rows) < PAGE_SIZE:
            break
        offset += PAGE_SIZE
    return header, all_rows, pages_used


def scrape_selected_groups(fetch_fn, groups, global_cap=GLOBAL_FETCH_CAP,
                           delay_fn=None):
    """Scrape unique groups in priority order, stopping at global_cap pages.

    groups: ordered unique group names (priority order). Returns
    (results, pages_used, skipped) where results maps group -> (header, rows)
    and skipped lists groups not reached because the global cap was hit.
    """
    results = {}
    skipped = []
    pages_used = 0
    for g in groups:
        if pages_used >= global_cap:
            skipped.append(g)
            continue
        remaining = global_cap - pages_used
        header, rows, used = paginate_group(
            fetch_fn, slugify_industry(g), max_pages=remaining
        )
        pages_used += used
        results[g] = (header, rows)
        if delay_fn is not None:
            delay_fn()
    return results, pages_used, skipped


# ---------------------------------------------------------------------------
# Row building + CSV append (pure)
# ---------------------------------------------------------------------------

def build_pick_rows(date_str, collected_at, selections_for_group, scraped_rows, finviz_cols):
    """Expand one group's scraped stock rows × its category tags → picks rows.

    selections_for_group: the selection dicts whose group == this group (1 per
    category the group qualified in). Each scraped stock row produces one picks
    row per category tag, carrying that category's grp_* snapshot + computed metrics.

    collected_at: single run-wide UTC timestamp (see main()), stamped identically
    on every row this run produces.
    """
    out = []
    for stock in scraped_rows:
        ticker = stock.get("Ticker", "")
        if not ticker:
            continue
        finviz_part = {col: stock.get(col, "") for col in finviz_cols}
        # Compute Phase-3a backend metrics from the scraped Finviz columns.
        metrics = compute_metrics_row(stock)
        for sel in selections_for_group:
            row = {
                "date": date_str,
                "collected_at": collected_at,
                "list_category": sel["list_category"],
                "selector_version": sel["selector_version"],
                "group": sel["group"],
                "ticker": ticker,
            }
            row.update(finviz_part)
            for col in pc.PICKS_GRP_COLS:
                row[col] = _f(sel.get(col))
            for col in METRICS_COLS:
                row[col] = _f(metrics.get(col))
            out.append(row)
    return out


def build_run_rows(date_str, collected_at, ordered_groups, results, selections, finviz_cols):
    """Expand one run's scrape results into picks rows + validation bookkeeping.

    Pure (no Finviz, no I/O). Returns (all_new_rows, validated_groups,
    suspect_slugs):
      - all_new_rows: every (stock × category) picks row across all groups.
      - validated_groups: set of groups that returned >= 1 row (G4 flip set).
      - suspect_slugs: groups that scraped but returned 0 rows (wrong slug or
        block) — surfaced in the run summary.

    `validated_groups` empty after this means the whole scrape came back empty,
    which the caller treats as a failed/blocked run (see the empty-scrape guard
    in main()).
    """
    all_new_rows = []
    validated_groups = set()
    suspect_slugs = []
    for g in ordered_groups:
        if g not in results:
            continue
        _header, rows = results[g]
        if not rows:
            suspect_slugs.append(g)
            continue
        validated_groups.add(g)
        group_sels = [s for s in selections if s["group"] == g]
        all_new_rows.extend(build_pick_rows(date_str, collected_at, group_sels, rows, finviz_cols))
    return all_new_rows, validated_groups, suspect_slugs


def missing_header_labels(results, expected_cols):
    """Union of expected Finviz labels absent from every scraped group header.

    results: {group: (header, rows)} from scrape_selected_groups. Only groups
    that returned rows are considered (an empty header just means a wrong slug /
    empty table, which the suspect-slug path already surfaces). A label counts
    as missing only if NO group's header contains it — all groups share one
    &c= column list, so a label present anywhere proves the config still maps.
    Returns a sorted list; [] when nothing usable was scraped.
    """
    seen = set()
    any_rows = False
    for _g, (header, rows) in results.items():
        if rows:
            any_rows = True
            seen.update(header)
    if not any_rows:
        return []
    return sorted(set(expected_cols) - seen)


def header_check_action(missing, expected_n):
    """Tiered policy for header drift: 'ok' | 'warn' | 'abort' (pure).

    'abort': Ticker missing (rows would be unkeyed) or more than
    HEADER_MISSING_ABORT_FRAC of the expected labels missing — the parse is
    untrustworthy, do not write. 'warn': some labels missing but the capture is
    mostly intact — write it, but exit non-zero after so CI goes red.
    """
    if not missing:
        return "ok"
    if "Ticker" in missing or len(missing) > HEADER_MISSING_ABORT_FRAC * expected_n:
        return "abort"
    return "warn"


def ticker_dup_rate(rows):
    """Fraction of rows whose ticker's first two characters are identical.

    Pure/testable signature-detector for the 2026-07-15 corruption class (see
    TICKER_DUP_RATE_MAX above). Returns 0.0 for an empty list.
    """
    if not rows:
        return 0.0
    dup = sum(1 for r in rows if len(r.get("ticker", "")) >= 2 and r["ticker"][0] == r["ticker"][1])
    return dup / len(rows)


def single_char_ticker_rate(rows):
    """Fraction of rows whose ticker is a single character.

    Complements ticker_dup_rate() (issue #252): catches the 2026-07-16
    corruption class where the parser returned only the avatar's leading letter,
    which the pair-duplication check misses (len<2). Returns 0.0 for empty input.
    """
    if not rows:
        return 0.0
    short = sum(1 for r in rows if len(r.get("ticker", "")) == 1)
    return short / len(rows)


def _read_rows(csv_path):
    if not csv_path.exists():
        return []
    with open(csv_path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_picks(picks_csv, latest_csv, new_rows, date_str, columns):
    """Append new_rows to picks.csv (evicting existing rows for date_str first;
    last-write-wins per (date, list_category, ticker)), then rewrite
    picks_latest.csv with the max-date slice. Returns (appended, latest_count)."""
    picks_csv.parent.mkdir(parents=True, exist_ok=True)
    existing = _read_rows(picks_csv)
    kept = [r for r in existing if r.get("date") != date_str]

    # Dedup the new batch on the uniqueness key (last-write-wins within batch).
    by_key = {}
    for r in new_rows:
        by_key[(r["date"], r["list_category"], r["ticker"])] = r
    deduped = list(by_key.values())

    all_rows = kept + deduped

    # picks_latest.csv = max-date slice. Enrich the TRAILING_COLS on that slice from the
    # full log (B-2, issue #379) BEFORE writing either file — latest_rows are references
    # into all_rows, so populating them here fills both picks.csv's max-date rows and
    # picks_latest.csv in one pass. Older rows keep "" (they're never read by the PWA).
    max_date = max((r["date"] for r in all_rows), default=date_str)
    latest_rows = [r for r in all_rows if r.get("date") == max_date]
    compute_trailing_setup(latest_rows, all_rows,
                           window=pc.TIGHT_RANGE_WINDOW,
                           spark_window=pc.SPARK_WINDOW,
                           spark_min=pc.SPARK_MIN_BARS)

    _write_csv(picks_csv, all_rows, columns)
    _write_csv(latest_csv, latest_rows, columns)

    return len(deduped), len(latest_rows)


# ---------------------------------------------------------------------------
# Slug-map validated flag (G4)
# ---------------------------------------------------------------------------

def flip_validated(slugs_path, validated_groups):
    """Write back validated=true for groups that returned rows this run (G4)."""
    rows = _read_rows(slugs_path)
    if not rows:
        return
    fieldnames = list(rows[0].keys())
    changed = False
    for r in rows:
        if r["industry_name"] in validated_groups and r.get("validated") != "true":
            r["validated"] = "true"
            changed = True
    if not changed:
        return
    with open(slugs_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


# ---------------------------------------------------------------------------
# Migration guard (Phase 3a — superset schema append)
# ---------------------------------------------------------------------------

def ensure_picks_csv(picks_csv, latest_csv=None):
    """Backfill any missing superset columns (METRICS_COLS, collected_at) into
    picks.csv's header.

    Pattern: analogue of ensure_deltas_csv() in compute_deltas.py. Each gap is
    checked independently so this stays a no-op-per-gap as each one is closed,
    but only ever rewrites the file once per call if ANY gap is found:
    (a) METRICS_COLS missing → recompute the 5 derived columns for every row
        from its already-stored Finviz columns (Phase 3a).
    (b) collected_at missing → backfill with date + COLLECTED_AT_CRON_UTC, an
        approximation of the collect_picks.yml cron fire time (worker-cron
        `31 22 * * 1-5` UTC) rather than a blank — the daily cron time is a
        known constant, so this is a reasonable estimate for historical rows;
        it is never used for new rows, which get the real per-run timestamp
        from main().

    This is a one-time auto-migration on the first run after each gap is
    deployed — after that it is a pure no-op (header check is O(1)).
    """
    if not picks_csv.exists():
        return
    existing = _read_rows(picks_csv)
    if not existing:
        return
    first_keys = set(existing[0].keys())
    needs_metrics = not all(c in first_keys for c in METRICS_COLS)
    needs_collected_at = "collected_at" not in first_keys
    needs_trailing = not all(c in first_keys for c in pc.TRAILING_COLS)
    if not needs_metrics and not needs_collected_at and not needs_trailing:
        return  # already migrated

    if needs_metrics:
        print(f"ensure_picks_csv: backfilling {METRICS_COLS} into {picks_csv} "
              f"({len(existing)} rows)…")
    if needs_collected_at:
        print(f"ensure_picks_csv: backfilling collected_at (approximated from "
              f"cron time {pc.COLLECTED_AT_CRON_UTC}) into {picks_csv} "
              f"({len(existing)} rows)…")
    if needs_trailing:
        print(f"ensure_picks_csv: backfilling {pc.TRAILING_COLS} onto the max-date "
              f"slice of {picks_csv}…")

    config = pc.load_config()
    columns = pc.picks_columns(config)

    for r in existing:
        if needs_metrics:
            m = compute_metrics_row(r)
            for col in METRICS_COLS:
                r[col] = _f(m[col])
        if needs_collected_at:
            r["collected_at"] = f"{r.get('date', '')}T{pc.COLLECTED_AT_CRON_UTC}Z"

    # TRAILING_COLS are trailing-window derived, populated only on the max-date slice the
    # PWA reads (older rows stay "" via _write_csv's r.get(col, "")). Compute after the
    # per-row backfills above so range_atr is present for the range_atr_spark series.
    if needs_trailing and existing:
        max_date = max(r.get("date", "") for r in existing)
        latest_rows = [r for r in existing if r.get("date") == max_date]
        compute_trailing_setup(latest_rows, existing,
                               window=pc.TIGHT_RANGE_WINDOW,
                               spark_window=pc.SPARK_WINDOW,
                               spark_min=pc.SPARK_MIN_BARS)

    picks_csv.parent.mkdir(parents=True, exist_ok=True)
    _write_csv(picks_csv, existing, columns)

    # Rewrite latest_csv from the updated full log.
    if latest_csv is not None and existing:
        max_date = max(r.get("date", "") for r in existing)
        latest_rows = [r for r in existing if r.get("date") == max_date]
        _write_csv(latest_csv, latest_rows, columns)
    print(f"ensure_picks_csv: done.")


def _write_csv(path, rows, columns):
    """Write rows to path using columns as the header (extrasaction='ignore')."""
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for r in rows:
            writer.writerow({c: r.get(c, "") for c in columns})


# ---------------------------------------------------------------------------
# Main (network path — runs on GitHub Actions only)
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", help="Override trading date (YYYY-MM-DD); default = today's trading date")
    parser.add_argument("--dry-run", action="store_true",
                        help="Run select_groups and print the plan; no Finviz scrape")
    args = parser.parse_args()

    # Phase-3a migration: backfill METRICS_COLS into any existing picks.csv that
    # predates the column addition. One-time auto-migration; pure no-op after day 1.
    ensure_picks_csv(pc.PICKS_CSV, pc.PICKS_LATEST_CSV)

    if not DELTAS_CSV.exists():
        print(f"FATAL: {DELTAS_CSV} not found — run collect.py + compute_deltas.py first")
        sys.exit(1)
    deltas = pd.read_csv(DELTAS_CSV)

    if not SNAPSHOTS_CSV.exists():
        print(f"FATAL: {SNAPSHOTS_CSV} not found — run collect.py first")
        sys.exit(1)
    snapshots = pd.read_csv(SNAPSHOTS_CSV)

    # trading_date is imported lazily (collect.py imports Playwright at module
    # top) so the pure-function path / tests don't require a browser install.
    import pytz
    from collect import trading_date
    eastern = pytz.timezone("US/Eastern")
    date_str = args.date or trading_date(datetime.now(eastern))

    # Single run-wide UTC timestamp, captured once and stamped on every row this
    # run produces (mirrors collect.py's collected_at pattern) — not per-page,
    # so a run's rows all agree even though the scrape itself takes minutes.
    collected_at = datetime.now(pytz.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Stale-read guard (D7/ADR-008): never select picks against yesterday's
    # rankings. If today's deltas aren't present, abort — cron drift, not a pick.
    max_delta_date = deltas["date"].max()
    if not args.date and max_delta_date != date_str:
        print(f"ABORT: deltas max date {max_delta_date} != trading date {date_str} "
              f"— today's group rankings not yet computed. Skipping picks scrape.")
        sys.exit(0)

    # all_green needs raw perf_* columns, which live in snapshots.csv, not
    # deltas.csv — merge them onto the latest-date slice before selecting.
    latest_deltas = deltas[deltas["date"] == max_delta_date]
    latest_snaps = snapshots[snapshots["date"] == max_delta_date][["name"] + ALL_GREEN_PERF_COLS]
    selector_input = latest_deltas.merge(latest_snaps, on="name", how="left")

    selections = select_groups(selector_input)
    summary = selection_summary(selections)
    print(f"=== Picks selection for {date_str} (selector {SELECTOR_VERSION}) ===")
    print(f"  by category: {summary['by_category']}")
    print(f"  unique groups: {summary['unique_groups']}  total rows: {summary['total_rows']}")

    if not selections:
        print("No groups selected — nothing to scrape.")
        sys.exit(0)

    # Unique groups in priority order (first appearance order in selections).
    seen = set()
    ordered_groups = []
    for s in selections:
        if s["group"] not in seen:
            seen.add(s["group"])
            ordered_groups.append(s["group"])

    if args.dry_run:
        for g in ordered_groups:
            cats = [s["list_category"] for s in selections if s["group"] == g]
            print(f"  {g}: {cats}")
        return

    config = pc.load_config()
    finviz_cols = pc.finviz_cols(config)
    columns = pc.picks_columns(config)

    from playwright.sync_api import sync_playwright
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

        def fetch_fn(slug, offset):
            url = _build_url(config, slug, offset=offset)
            print(f"  GET {url}")
            page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            try:
                page.wait_for_selector(SCREENER_TABLE_SELECTOR, timeout=30_000)
            except Exception as exc:
                print(f"  WARNING: table selector not found: {exc}")
            return _parse_table(page.content())

        def delay_fn():
            if PAGE_DELAY_S > 0:
                time.sleep(PAGE_DELAY_S)

        results, pages_used, skipped = scrape_selected_groups(
            fetch_fn, ordered_groups, delay_fn=delay_fn
        )
        browser.close()

    # Build rows + validation bookkeeping.
    all_new_rows, validated_groups, suspect_slugs = build_run_rows(
        date_str, collected_at, ordered_groups, results, selections, finviz_cols
    )

    # Empty-scrape guard (D14 / PICKS-2): if NOT ONE selected group returned a
    # single row, the scrape did not really succeed — this is the exact signature
    # of a Cloudflare challenge (every page is HTTP 200 with an empty table, which
    # _parse_table returns as 0 rows, no exception). Selected groups are leaders
    # etc. that always contain member stocks, so an all-empty result is never a
    # genuine "no qualifying stocks" — it is a blocked/broken run.
    #
    # We MUST abort BEFORE write_picks here, because write_picks evicts the date's
    # existing rows before appending: writing an empty batch would silently wipe an
    # earlier same-day capture and revert picks_latest.csv to a prior date. The
    # daily list is irreplaceable (no backfill), so a blocked run must be a loud
    # no-op, not a destructive overwrite. exit(1) turns CI red and fires the
    # if:failure() debug-HTML upload in collect_picks.yml.
    if not validated_groups:
        print(
            f"\nABORT: scraped {len(ordered_groups)} group(s) over {pages_used} page(s) "
            f"but got 0 rows total — likely a Cloudflare block or broken slugs. "
            f"NOT writing picks.csv (would wipe any existing {date_str} capture). "
            f"suspect slugs: {suspect_slugs}"
        )
        sys.exit(1)

    # Header-drift guard (PICKS-2-HDR): see missing_header_labels /
    # header_check_action + the HEADER_MISSING_ABORT_FRAC comment for the
    # tiered policy (abort pre-write vs write-then-fail-loud).
    missing = missing_header_labels(results, finviz_cols)
    header_action = header_check_action(missing, len(finviz_cols))
    if header_action == "abort":
        print(
            f"\nABORT: scraped header is missing {len(missing)}/{len(finviz_cols)} expected "
            f"Finviz labels — screener_config.json no longer matches the live screener "
            f"table; the parse is untrustworthy. NOT writing picks.csv. "
            f"missing: {missing}"
        )
        sys.exit(1)

    # Ticker-corruption guard: catches a repeat of the 2026-07-15 incident (or
    # any future Finviz markup change with the same signature) BEFORE writing
    # — same "abort before write_picks" reasoning as the empty-scrape guard
    # above, since write_picks evicts the date's existing rows first.
    dup_rate = ticker_dup_rate(all_new_rows)
    if dup_rate > TICKER_DUP_RATE_MAX:
        sample = [r["ticker"] for r in all_new_rows[:10]]
        print(
            f"\nABORT: {dup_rate:.0%} of {len(all_new_rows)} scraped tickers have a "
            f"duplicated leading character (max allowed {TICKER_DUP_RATE_MAX:.0%}) — "
            f"likely a Finviz Ticker-cell markup change corrupting the parse. "
            f"NOT writing picks.csv. sample: {sample}"
        )
        sys.exit(1)

    # Single-char-ticker guard (issue #252): complements the dup-rate guard
    # above by catching the class of corruption the pair-based check is blind
    # to (a 1-char ticker has no duplicated pair to detect).
    short_rate = single_char_ticker_rate(all_new_rows)
    if short_rate > TICKER_SHORT_RATE_MAX:
        sample = [r["ticker"] for r in all_new_rows[:10]]
        print(
            f"\nABORT: {short_rate:.0%} of {len(all_new_rows)} scraped tickers are a "
            f"single character (max allowed {TICKER_SHORT_RATE_MAX:.0%}) — likely a "
            f"Finviz Ticker-cell markup change corrupting the parse (issue #252). "
            f"NOT writing picks.csv. sample: {sample}"
        )
        sys.exit(1)

    appended, latest_count = write_picks(
        pc.PICKS_CSV, pc.PICKS_LATEST_CSV, all_new_rows, date_str, columns
    )
    flip_validated(pc.SLUGS_PATH, validated_groups)

    print(f"\n=== Scrape summary ===")
    print(f"  pages fetched: {pages_used} (cap {GLOBAL_FETCH_CAP})")
    print(f"  groups scraped with rows: {len(validated_groups)}")
    print(f"  picks rows appended: {appended}  picks_latest rows: {latest_count}")
    if suspect_slugs:
        print(f"  WARNING suspect slugs (0 rows): {suspect_slugs}")
    if skipped:
        print(f"  groups skipped (global cap hit): {skipped}")

    # Header-drift 'warn' tier: the capture above was written (bounded column
    # loss beats losing the whole day), but exit non-zero so CI goes red, the
    # debug-HTML artifact uploads, and the success-only healthcheck ping is
    # skipped — a human must reconcile screener_config.json with the live table.
    if header_action == "warn":
        print(
            f"\nFAIL (after write): scraped header is missing {len(missing)} expected "
            f"Finviz label(s): {missing} — those columns were written BLANK for "
            f"{date_str}. Update data/picks/screener_config.json to match the live "
            f"screener header."
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
