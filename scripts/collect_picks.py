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
from picks_metrics import METRICS_COLS, compute_metrics_row
# Inherit the pure scrape/url/parse helpers from the Phase-1 probe — no need to
# rewrite them. They are import-safe (Playwright is imported inside probe main()).
from probe_picks import slugify_industry, _build_url, _parse_table, SCREENER_TABLE_SELECTOR

BASE_DIR = Path(__file__).parent.parent
DELTAS_CSV = BASE_DIR / "data" / "industries" / "deltas.csv"

# Top-40% floor means percentile rank >= (1 - ANTIFLASH_PCTILE).
_PCTILE_CUTOFF = 1.0 - ANTIFLASH_PCTILE


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
    freshness-fill sub-bucket already excludes the core 8 by construction.

    Buckets are filled in priority order; a 0-group bucket is normal (e.g.
    momentum_accel is NaN until 11 sessions exist) — fill from the next priority,
    total unique groups stays ≤ DAILY_GROUP_CAP, never error.

    Pure: no Finviz access. Replayable over any historical date in deltas.csv.
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

    # ---- Priority 1: leaders (8 sustained_strength + 2 momentum_confirmed) ----
    latest["_sum_mid"] = (
        latest["rank_month"] + latest["rank_quarter"] + latest["rank_half"]
    )
    ss_ranked = latest.dropna(subset=["_sum_mid"]).sort_values("_sum_mid", ascending=True)
    core_names = list(ss_ranked["name"].head(LEADER_SS_SLOTS))
    for i, name in enumerate(core_names, start=1):
        add(name, "leaders", "sustained_strength", i)

    # Freshness fills: momentum_confirmed desc among groups NOT in the core 8.
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

    return selections


def selection_summary(selections: list) -> dict:
    """Per-bucket counts for the run summary (empty buckets are expected, G2)."""
    counts = {"leaders": 0, "emerging": 0, "accel": 0, "rs_new_high": 0}
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

def build_pick_rows(date_str, selections_for_group, scraped_rows, finviz_cols):
    """Expand one group's scraped stock rows × its category tags → picks rows.

    selections_for_group: the selection dicts whose group == this group (1 per
    category the group qualified in). Each scraped stock row produces one picks
    row per category tag, carrying that category's grp_* snapshot + computed metrics.
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


def build_run_rows(date_str, ordered_groups, results, selections, finviz_cols):
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
        all_new_rows.extend(build_pick_rows(date_str, group_sels, rows, finviz_cols))
    return all_new_rows, validated_groups, suspect_slugs


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
    _write_csv(picks_csv, all_rows, columns)

    # picks_latest.csv = max-date slice (written atomically alongside the append).
    max_date = max((r["date"] for r in all_rows), default=date_str)
    latest_rows = [r for r in all_rows if r.get("date") == max_date]
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
    """Backfill METRICS_COLS into picks.csv if they are absent from its header.

    Pattern: analogue of ensure_deltas_csv() in compute_deltas.py.
    (a) Read current header. If METRICS_COLS are already present → no-op.
    (b) Otherwise: read all rows, compute the 5 derived values for every row from its
        already-stored Finviz columns, and atomically rewrite picks_csv with the new
        113-col header. Then rewrite latest_csv (max-date slice) from the updated rows.

    This is a one-time auto-migration on the first run after Phase 3a is deployed —
    after that it is a pure no-op (header check is O(1)).
    """
    if not picks_csv.exists():
        return
    existing = _read_rows(picks_csv)
    if not existing:
        return
    first_keys = set(existing[0].keys())
    if all(c in first_keys for c in METRICS_COLS):
        return  # already migrated

    print(f"ensure_picks_csv: backfilling {METRICS_COLS} into {picks_csv} "
          f"({len(existing)} rows)…")

    config = pc.load_config()
    columns = pc.picks_columns(config)

    # Recompute metrics for every existing row.
    for r in existing:
        m = compute_metrics_row(r)
        for col in METRICS_COLS:
            v = m[col]
            r[col] = _f(v)

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

    # trading_date is imported lazily (collect.py imports Playwright at module
    # top) so the pure-function path / tests don't require a browser install.
    import pytz
    from collect import trading_date
    eastern = pytz.timezone("US/Eastern")
    date_str = args.date or trading_date(datetime.now(eastern))

    # Stale-read guard (D7/ADR-008): never select picks against yesterday's
    # rankings. If today's deltas aren't present, abort — cron drift, not a pick.
    max_delta_date = deltas["date"].max()
    if not args.date and max_delta_date != date_str:
        print(f"ABORT: deltas max date {max_delta_date} != trading date {date_str} "
              f"— today's group rankings not yet computed. Skipping picks scrape.")
        sys.exit(0)

    selections = select_groups(deltas[deltas["date"] == max_delta_date])
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
        date_str, ordered_groups, results, selections, finviz_cols
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


if __name__ == "__main__":
    main()
