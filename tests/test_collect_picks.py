"""
Tests for collect_picks.py — the Phase-2 picks selector + scraper pipeline.

Pure functions only (no Finviz / Playwright):
  - select_groups (each bucket, floors, dedup, cap, grp_* snapshot, empty bucket)
  - paginate_group (mock pages; short/empty page; wrong-slug empty header)
  - scrape_selected_groups (global cap — no 51st page)
  - build_pick_rows (category-tag expansion)
  - write_picks (append/dedup + picks_latest == max-date slice; migration)
  - flip_validated (G4)
  - selector_versions.json registry (current/unique/monotonic/active match)
  - schema: golden-header sync, superset/reorder guard
"""

import csv
import hashlib
import json
import sys
from pathlib import Path

import pandas as pd
import pytest

BASE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BASE_DIR / "scripts"))

import picks_config as pc
from collect_picks import (
    select_groups,
    selection_summary,
    paginate_group,
    scrape_selected_groups,
    build_pick_rows,
    build_run_rows,
    write_picks,
    flip_validated,
    ensure_picks_csv,
    ticker_dup_rate,
    single_char_ticker_rate,
    missing_header_labels,
    header_check_action,
    TICKER_DUP_RATE_MAX,
    TICKER_SHORT_RATE_MAX,
    HEADER_MISSING_ABORT_FRAC,
    _PCTILE_CUTOFF,
)
from picks_config import (
    SELECTOR_VERSION,
    DAILY_GROUP_CAP,
    LEADER_SS_SLOTS,
    LEADER_MC_SLOTS,
    ALL_GREEN_SLOTS,
    ALL_GREEN_PERF_COLS,
    PAGE_SIZE,
    GLOBAL_FETCH_CAP,
)

SLUGS_PATH = BASE_DIR / "data" / "picks" / "finviz_industry_slugs.csv"
GOLDEN_HEADER_PATH = BASE_DIR / "tests" / "fixtures" / "probe_header_84col.txt"


# ---------------------------------------------------------------------------
# Helpers — build a minimal deltas DataFrame
# ---------------------------------------------------------------------------

GRP_NUMERIC_COLS = [
    "rank_month", "rank_quarter", "rank_half", "momentum_confirmed",
    "momentum_score", "momentum_accel", "momentum_weighted_mid", "rank_agreement",
    "regime_short_long", "rs_score", "rs_agreement", "rs_confirmed", "rs_accel",
    "rs_new_high", "rs_slope",
] + ALL_GREEN_PERF_COLS  # default NaN -> not all-green unless a test overrides them


def _delta_row(name, date="2026-06-24", **overrides):
    base = {"date": date, "name": name}
    for c in GRP_NUMERIC_COLS:
        base[c] = float("nan")
    base.update(overrides)
    return base


def _make_df(rows):
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# select_groups — leaders
# ---------------------------------------------------------------------------

class TestLeaders:
    def _leaders_df(self):
        # 15 groups (LEADER_SS_SLOTS=11 core + LEADER_MC_SLOTS=2 fill + 2 spare);
        # sum_mid increases with index so ordering is deterministic.
        rows = []
        for i in range(15):
            rows.append(_delta_row(
                f"G{i:02d}",
                rank_month=i + 1, rank_quarter=i + 1, rank_half=i + 1,
                momentum_score=1.0 - i * 0.05,
                momentum_confirmed=0.9 - i * 0.01,
            ))
        return _make_df(rows)

    def test_picks_eleven_by_sum_of_ranks(self):
        sels = select_groups(self._leaders_df())
        ss = [s for s in sels if s["grp_rank_basis"] == "sustained_strength"]
        assert len(ss) == LEADER_SS_SLOTS
        # Lowest sum-of-ranks first: G00..G10 (sums 3,6,9,...).
        assert [s["group"] for s in ss] == [f"G{i:02d}" for i in range(11)]
        # grp_category_rank is 1..11 in that order.
        assert [s["grp_category_rank"] for s in ss] == list(range(1, 12))
        assert ss[0]["grp_sum_mid_rank"] == 3  # 1+1+1

    def test_two_freshness_fills_not_in_core(self):
        sels = select_groups(self._leaders_df())
        fills = [s for s in sels if s["grp_rank_basis"] == "freshness_fill"]
        assert len(fills) == LEADER_MC_SLOTS
        core = {s["group"] for s in sels if s["grp_rank_basis"] == "sustained_strength"}
        for f in fills:
            assert f["group"] not in core
        # momentum_confirmed desc among the remaining (G11 highest of the rest).
        assert fills[0]["group"] == "G11"
        assert fills[0]["grp_category_rank"] == 1

    def test_no_hard_intersection_gate_degrades_gracefully(self):
        # Only 3 groups are "top" on all timeframes, but sum-of-ranks still fills 11.
        rows = [_delta_row(f"H{i:02d}", rank_month=i + 1, rank_quarter=i + 1,
                           rank_half=i + 1, momentum_confirmed=0.5)
                for i in range(11)]
        sels = select_groups(_make_df(rows))
        ss = [s for s in sels if s["grp_rank_basis"] == "sustained_strength"]
        assert len(ss) == 11  # not gated down to an intersection subset


# ---------------------------------------------------------------------------
# select_groups — emerging / accel / rs_new_high floors + empty buckets
# ---------------------------------------------------------------------------

class TestBuckets:
    def _base_leaders(self, n=LEADER_SS_SLOTS):
        return [_delta_row(f"L{i:02d}", rank_month=i + 1, rank_quarter=i + 1,
                           rank_half=i + 1, momentum_score=0.9 - i * 0.05,
                           momentum_confirmed=0.5)
                for i in range(n)]

    def test_emerging_requires_regime_and_rs(self):
        rows = self._base_leaders()
        rows.append(_delta_row("EM_ok", rank_month=50, rank_quarter=50, rank_half=50,
                               regime_short_long=0.3, rs_score=0.7, momentum_score=0.4))
        rows.append(_delta_row("EM_lowrs", rank_month=51, rank_quarter=51, rank_half=51,
                               regime_short_long=0.3, rs_score=0.4, momentum_score=0.3))
        sels = select_groups(_make_df(rows))
        em = [s["group"] for s in sels if s["list_category"] == "emerging"]
        assert "EM_ok" in em
        assert "EM_lowrs" not in em  # rs_score floor rejects it

    def test_accel_empty_when_all_nan(self):
        # G2: momentum_accel all NaN → accel bucket = 0, no error.
        sels = select_groups(_make_df(self._base_leaders()))
        accel = [s for s in sels if s["list_category"] == "accel"]
        assert accel == []
        summ = selection_summary(sels)
        assert summ["by_category"]["accel"] == 0
        assert summ["unique_groups"] <= DAILY_GROUP_CAP

    def test_accel_floor_uses_top_pctile(self):
        rows = self._base_leaders()
        # High accel but bottom-of-pack momentum → rejected by anti-flash floor.
        rows.append(_delta_row("ACC_lowmom", rank_month=60, rank_quarter=60, rank_half=60,
                               momentum_accel=0.2, momentum_score=0.01, rs_score=0.8))
        # High accel AND high momentum → accepted.
        rows.append(_delta_row("ACC_ok", rank_month=61, rank_quarter=61, rank_half=61,
                               momentum_accel=0.2, momentum_score=0.99, rs_score=0.8))
        sels = select_groups(_make_df(rows))
        accel = [s["group"] for s in sels if s["list_category"] == "accel"]
        assert "ACC_ok" in accel
        assert "ACC_lowmom" not in accel

    def test_rs_new_high_floor(self):
        rows = self._base_leaders()
        rows.append(_delta_row("RNH_ok", rank_month=70, rank_quarter=70, rank_half=70,
                               rs_new_high=1, rs_score=0.8, momentum_score=0.99,
                               rs_slope=0.1))
        rows.append(_delta_row("RNH_lowrs", rank_month=71, rank_quarter=71, rank_half=71,
                               rs_new_high=1, rs_score=0.5, momentum_score=0.99,
                               rs_slope=0.1))
        sels = select_groups(_make_df(rows))
        rnh = [s["group"] for s in sels if s["list_category"] == "rs_new_high"]
        assert "RNH_ok" in rnh
        assert "RNH_lowrs" not in rnh  # rs_score < 0.6


# ---------------------------------------------------------------------------
# Dedup + cap
# ---------------------------------------------------------------------------

class TestDedupAndCap:
    def test_dedup_group_tagged_per_category(self):
        # One group qualifies as both a leader and accel.
        rows = [_delta_row(f"L{i:02d}", rank_month=i + 2, rank_quarter=i + 2,
                           rank_half=i + 2, momentum_score=0.9, momentum_confirmed=0.5)
                for i in range(7)]
        rows.append(_delta_row("DUAL", rank_month=1, rank_quarter=1, rank_half=1,
                               momentum_score=0.99, momentum_accel=0.2, rs_score=0.8,
                               momentum_confirmed=0.6))
        sels = select_groups(_make_df(rows))
        dual = [s for s in sels if s["group"] == "DUAL"]
        cats = {s["list_category"] for s in dual}
        assert "leaders" in cats and "accel" in cats
        # Counts once toward unique groups.
        groups = [s["group"] for s in sels]
        assert groups.count("DUAL") == len(dual)
        summ = selection_summary(sels)
        assert summ["unique_groups"] == len(set(groups))

    def test_cap_limits_unique_groups(self):
        # 40 emerging-qualifying groups, but cap is 20 unique.
        rows = []
        for i in range(40):
            rows.append(_delta_row(f"E{i:02d}", rank_month=i + 1, rank_quarter=i + 1,
                                   rank_half=i + 1, regime_short_long=0.5,
                                   rs_score=0.7, momentum_score=0.5,
                                   momentum_confirmed=0.5))
        sels = select_groups(_make_df(rows))
        assert len({s["group"] for s in sels}) <= DAILY_GROUP_CAP

    def test_backfill_past_natural_top_n_when_leader_dups_in(self):
        # 11 leaders (sum_mid 3..33) fill the core. The #1-ranked accel candidate
        # is one of those leaders (rank_month=1 -> sum_mid=3 -> core leader), so
        # it still gets tagged "accel" (top-3 zone attribution preserved) but must
        # NOT eat one of the 3 accel slots — 3 additional, genuinely new, accel
        # candidates should still be admitted via backfill past rank 3.
        # (10 fillers + DUAL below = 11 low-sum_mid rows, exactly LEADER_SS_SLOTS,
        # so the 3 high-sum_mid ACC rows stay correctly excluded from the core.)
        rows = [_delta_row(f"L{i:02d}", rank_month=i + 2, rank_quarter=i + 2,
                           rank_half=i + 2, momentum_score=0.9, momentum_confirmed=0.5)
                for i in range(10)]
        # This group is both a core leader (sum_mid=3, lowest) AND accel rank 1.
        rows.append(_delta_row("DUAL", rank_month=1, rank_quarter=1, rank_half=1,
                               momentum_score=0.99, momentum_accel=0.5, rs_score=0.8,
                               momentum_confirmed=0.6))
        # 3 more accel-qualifying groups, ranked below DUAL, none of them leaders.
        for i, accel_val in enumerate([0.4, 0.3, 0.2]):
            rows.append(_delta_row(f"ACC{i}", rank_month=90 + i, rank_quarter=90 + i,
                                   rank_half=90 + i, momentum_accel=accel_val,
                                   momentum_score=0.95, rs_score=0.8))
        sels = select_groups(_make_df(rows))
        accel = [s for s in sels if s["list_category"] == "accel"]
        accel_groups = [s["group"] for s in accel]
        # DUAL is tagged accel (attribution) at its natural rank (1)...
        assert "DUAL" in accel_groups
        # ...but ACCEL_SLOTS (3) NEW groups still got in via backfill past rank 3.
        assert {"ACC0", "ACC1", "ACC2"} <= set(accel_groups)
        assert len(accel) == 4  # DUAL + 3 backfilled new
        # DUAL still counts once toward unique groups (already a leader).
        summ = selection_summary(sels)
        assert summ["unique_groups"] == len({s["group"] for s in sels})


# ---------------------------------------------------------------------------
# select_groups — all_green (5th bucket, lowest priority)
# ---------------------------------------------------------------------------

class TestAllGreen:
    def _green_row(self, name, **overrides):
        # All 5 ALL_GREEN_PERF_COLS positive by default; rank_month/quarter/half
        # high (weak) so it never accidentally lands in the leaders core.
        base = dict(rank_month=90, rank_quarter=90, rank_half=90, momentum_score=0.5)
        for col in ALL_GREEN_PERF_COLS:
            base[col] = 1.0
        base.update(overrides)
        return _delta_row(name, **base)

    def test_requires_all_five_positive(self):
        rows = [
            self._green_row("ALLGREEN"),
            self._green_row("ONE_RED", perf_ytd=-0.5),
        ]
        sels = select_groups(_make_df(rows))
        green = [s["group"] for s in sels if s["list_category"] == "all_green"]
        assert "ALLGREEN" in green
        assert "ONE_RED" not in green

    def test_missing_perf_columns_yields_zero_not_error(self):
        # A deltas_df without the merged perf_* columns (e.g. an old caller that
        # never merged snapshots.csv) must degrade to 0 groups, not KeyError.
        rows = [_delta_row(f"L{i:02d}", rank_month=i + 1, rank_quarter=i + 1,
                           rank_half=i + 1, momentum_score=0.9)
                for i in range(3)]
        bare_rows = [{k: v for k, v in r.items() if k not in ALL_GREEN_PERF_COLS}
                     for r in rows]
        sels = select_groups(_make_df(bare_rows))
        assert [s for s in sels if s["list_category"] == "all_green"] == []

    def test_sorted_by_momentum_score_desc(self):
        rows = [
            self._green_row("LOW", momentum_score=0.3),
            self._green_row("HIGH", momentum_score=0.9),
            self._green_row("MID", momentum_score=0.6),
        ]
        sels = select_groups(_make_df(rows))
        green = [s["group"] for s in sels if s["list_category"] == "all_green"]
        assert green == ["HIGH", "MID", "LOW"]

    def test_lowest_priority_loses_to_higher_bucket_on_overlap(self):
        # A group that is both all-green AND naturally a leader (low sum_mid) is
        # claimed by leaders first; all_green still tags it (attribution) but a
        # genuinely new all-green candidate should still get backfilled in.
        rows = [_delta_row(f"L{i:02d}", rank_month=i + 2, rank_quarter=i + 2,
                           rank_half=i + 2, momentum_score=0.9, momentum_confirmed=0.5)
                for i in range(10)]
        dual = self._green_row("DUAL", rank_month=1, rank_quarter=1, rank_half=1,
                               momentum_score=0.99)
        rows.append(dual)
        rows.append(self._green_row("NEWGREEN", momentum_score=0.7))
        sels = select_groups(_make_df(rows))
        green = [s for s in sels if s["list_category"] == "all_green"]
        green_groups = [s["group"] for s in green]
        assert "DUAL" in green_groups          # tagged (attribution), rank 1
        assert "NEWGREEN" in green_groups       # backfilled past rank 1
        summ = selection_summary(sels)
        assert summ["unique_groups"] == len({s["group"] for s in sels})

    def test_cap_is_four(self):
        rows = [self._green_row(f"G{i:02d}", momentum_score=1.0 - i * 0.01)
                for i in range(10)]
        sels = select_groups(_make_df(rows))
        green = [s["group"] for s in sels if s["list_category"] == "all_green"]
        assert len(green) == ALL_GREEN_SLOTS


# ---------------------------------------------------------------------------
# pagination
# ---------------------------------------------------------------------------

def _page_fetcher(total_rows, header=("Ticker", "Price")):
    """Return a fetch_fn serving total_rows across PAGE_SIZE-row pages."""
    def fetch(slug, offset):
        start = offset - 1
        remaining = max(0, total_rows - start)
        n = min(PAGE_SIZE, remaining)
        rows = [{"Ticker": f"T{start + i}", "Price": "1"} for i in range(n)]
        return list(header), rows
    return fetch


class TestPagination:
    def test_single_short_page(self):
        header, rows, pages = paginate_group(_page_fetcher(5), "x")
        assert pages == 1
        assert len(rows) == 5

    def test_multi_page_until_short(self):
        # page_cap/max_pages set well above PAGE_CAP (2) — this test exercises the
        # walk's own short-page stopping logic, independent of the configured cap.
        header, rows, pages = paginate_group(_page_fetcher(45), "x", page_cap=10, max_pages=10)
        assert len(rows) == 45
        assert pages == 3  # 20 + 20 + 5

    def test_exact_page_boundary_stops(self):
        # 40 rows = 2 full pages; 3rd page is empty → stop.
        header, rows, pages = paginate_group(_page_fetcher(40), "x", page_cap=10, max_pages=10)
        assert len(rows) == 40
        assert pages == 3  # 2 data pages + 1 empty terminator

    def test_wrong_slug_empty_header(self):
        # Wrong slug → HTTP 200 empty table → [] header, 0 rows (not a 404).
        def fetch(slug, offset):
            return [], []
        header, rows, pages = paginate_group(fetch, "badslug")
        assert header == []
        assert rows == []
        assert pages == 1

    def test_page_cap_respected(self):
        header, rows, pages = paginate_group(_page_fetcher(10_000), "x",
                                             page_cap=3, max_pages=99)
        assert pages == 3


class TestGlobalCap:
    def test_stops_at_global_cap_no_51st_page(self):
        calls = []

        def fetch(slug, offset):
            calls.append((slug, offset))
            return ["Ticker"], [{"Ticker": f"T{i}"} for i in range(PAGE_SIZE)]

        # Each group is "infinite" (always a full page) → each consumes its
        # remaining budget. With many groups, total pages must stop at the cap.
        groups = [f"G{i}" for i in range(60)]
        results, pages_used, skipped = scrape_selected_groups(fetch, groups)
        assert pages_used == GLOBAL_FETCH_CAP
        assert len(calls) == GLOBAL_FETCH_CAP  # no 51st fetch
        assert skipped  # later groups never reached


# ---------------------------------------------------------------------------
# build_pick_rows
# ---------------------------------------------------------------------------

class TestBuildPickRows:
    def test_expands_per_category(self):
        sels = [
            {"group": "G", "list_category": "leaders", "selector_version": "v1",
             **{c: "" for c in pc.PICKS_GRP_COLS}},
            {"group": "G", "list_category": "accel", "selector_version": "v1",
             **{c: "" for c in pc.PICKS_GRP_COLS}},
        ]
        scraped = [{"Ticker": "NVDA", "Price": "100"}, {"Ticker": "AMD", "Price": "50"}]
        rows = build_pick_rows("2026-06-24", "2026-06-24T22:31:05Z", sels, scraped, ["Ticker", "Price"])
        assert len(rows) == 4  # 2 stocks × 2 categories
        cats = {r["list_category"] for r in rows}
        assert cats == {"leaders", "accel"}
        assert rows[0]["Price"] == "100"
        assert all(r["collected_at"] == "2026-06-24T22:31:05Z" for r in rows)

    def test_skips_rows_without_ticker(self):
        sels = [{"group": "G", "list_category": "leaders", "selector_version": "v1",
                 **{c: "" for c in pc.PICKS_GRP_COLS}}]
        rows = build_pick_rows("2026-06-24", "2026-06-24T22:31:05Z", sels,
                               [{"Ticker": "", "Price": "1"}], ["Ticker", "Price"])
        assert rows == []


# ---------------------------------------------------------------------------
# build_run_rows + empty-scrape guard (D14 / PICKS-2)
# ---------------------------------------------------------------------------

class TestBuildRunRows:
    def _sels(self):
        base = {"selector_version": "v1", **{c: "" for c in pc.PICKS_GRP_COLS}}
        return [
            {"group": "G1", "list_category": "leaders", **base},
            {"group": "G2", "list_category": "emerging", **base},
        ]

    def test_partitions_rows_validated_and_suspect(self):
        results = {
            "G1": (["Ticker"], [{"Ticker": "AAA"}, {"Ticker": "BBB"}]),
            "G2": (["Ticker"], []),  # scraped but 0 rows → suspect
        }
        rows, validated, suspect = build_run_rows(
            "2026-06-24", "2026-06-24T22:31:05Z", ["G1", "G2"], results, self._sels(), ["Ticker"]
        )
        assert validated == {"G1"}
        assert suspect == ["G2"]
        assert {r["ticker"] for r in rows} == {"AAA", "BBB"}
        assert all(r["collected_at"] == "2026-06-24T22:31:05Z" for r in rows)

    def test_all_empty_yields_no_validated_groups(self):
        # Cloudflare-block signature: every group HTTP 200 with an empty table.
        results = {"G1": ([], []), "G2": ([], [])}
        rows, validated, suspect = build_run_rows(
            "2026-06-24", "2026-06-24T22:31:05Z", ["G1", "G2"], results, self._sels(), ["Ticker"]
        )
        assert rows == []
        assert validated == set()          # guard in main() trips on this
        assert suspect == ["G1", "G2"]

    def test_empty_batch_would_wipe_existing_date(self, tmp_path):
        # Regression proving WHY the guard exists: write_picks evicts the date
        # before appending, so an empty batch silently erases a same-day capture
        # and reverts picks_latest to a prior date. The guard must prevent this
        # call from ever happening on an all-empty scrape.
        picks = tmp_path / "picks.csv"
        latest = tmp_path / "picks_latest.csv"
        cols = ["date", "list_category", "ticker", "Price"]
        good = {"date": "2026-06-24", "list_category": "leaders",
                "ticker": "AAA", "Price": "1"}
        write_picks(picks, latest, [good], "2026-06-24", cols)
        # Empty re-run for the same date wipes it (documents the hazard).
        write_picks(picks, latest, [], "2026-06-24", cols)
        assert list(csv.DictReader(open(picks))) == []
        assert list(csv.DictReader(open(latest))) == []


# ---------------------------------------------------------------------------
# ticker_dup_rate — corruption-signature guard (2026-07-15 incident)
# ---------------------------------------------------------------------------

class TestTickerDupRate:
    def test_empty_rows_is_zero(self):
        assert ticker_dup_rate([]) == 0.0

    def test_normal_run_stays_under_threshold(self):
        # One legitimately doubled-first-letter ticker (AA) among 19 clean
        # ones (~5%) — matches the observed 1-4% real baseline, comfortably
        # under the guard threshold.
        clean = ["MSFT", "NVDA", "AMD", "TSLA", "DINO", "VLO", "PSX", "SUN",
                 "JPM", "WFC", "SAN", "CM", "HSBC", "BBVA", "ING", "KEX",
                 "MATX", "AFN", "ZIM", "COO"]
        rows = [{"ticker": t} for t in ["AA"] + clean]
        assert ticker_dup_rate(rows) < TICKER_DUP_RATE_MAX

    def test_corrupted_run_trips_threshold(self):
        # Every ticker prefixed with its own first letter — the exact
        # 2026-07-15 signature ("HSBC" -> "HHSBC", "C" -> "CC").
        rows = [{"ticker": t} for t in ["HHSBC", "CC", "WWFC", "SSAN", "IING"]]
        assert ticker_dup_rate(rows) == 1.0
        assert ticker_dup_rate(rows) > TICKER_DUP_RATE_MAX

    def test_short_ticker_not_misflagged(self):
        assert ticker_dup_rate([{"ticker": "E"}]) == 0.0


# ---------------------------------------------------------------------------
# single_char_ticker_rate — complementary guard for 1-char corruption (#252)
# ---------------------------------------------------------------------------

class TestSingleCharTickerRate:
    def test_empty_rows_is_zero(self):
        assert single_char_ticker_rate([]) == 0.0

    def test_all_single_char_trips_threshold(self):
        rows = [{"ticker": t} for t in ["A", "B", "C", "D"]]
        assert single_char_ticker_rate(rows) == 1.0
        assert single_char_ticker_rate(rows) > TICKER_SHORT_RATE_MAX

    def test_healthy_mix_stays_under_threshold(self):
        # A couple of legitimate 1-char tickers (C, F) among many multi-char
        # ones — matches the observed ~1.3-1.4% real baseline.
        clean = ["MSFT", "NVDA", "AMD", "TSLA", "DINO", "VLO", "PSX", "SUN",
                 "JPM", "WFC", "SAN", "HSBC", "BBVA", "ING", "KEX",
                 "MATX", "AFN", "ZIM", "COO"]
        rows = [{"ticker": t} for t in ["C", "F"] + clean]
        assert single_char_ticker_rate(rows) < TICKER_SHORT_RATE_MAX

    def test_multi_char_only_is_zero(self):
        rows = [{"ticker": t} for t in ["MSFT", "NVDA", "AMD"]]
        assert single_char_ticker_rate(rows) == 0.0


# ---------------------------------------------------------------------------
# write_picks + picks_latest
# ---------------------------------------------------------------------------

class TestWritePicks:
    def _cols(self):
        return ["date", "list_category", "ticker", "Price"]

    def _row(self, date, cat, ticker, price="1"):
        return {"date": date, "list_category": cat, "ticker": ticker, "Price": price}

    def test_latest_equals_max_date_slice(self, tmp_path):
        picks = tmp_path / "picks.csv"
        latest = tmp_path / "picks_latest.csv"
        cols = self._cols()
        write_picks(picks, latest, [self._row("2026-06-23", "leaders", "AAA")],
                    "2026-06-23", cols)
        write_picks(picks, latest, [self._row("2026-06-24", "leaders", "BBB")],
                    "2026-06-24", cols)
        latest_rows = list(csv.DictReader(open(latest)))
        assert all(r["date"] == "2026-06-24" for r in latest_rows)
        assert {r["ticker"] for r in latest_rows} == {"BBB"}
        # Full log keeps both dates.
        all_rows = list(csv.DictReader(open(picks)))
        assert {r["date"] for r in all_rows} == {"2026-06-23", "2026-06-24"}

    def test_rerun_same_date_last_write_wins(self, tmp_path):
        picks = tmp_path / "picks.csv"
        latest = tmp_path / "picks_latest.csv"
        cols = self._cols()
        write_picks(picks, latest, [self._row("2026-06-24", "leaders", "AAA", "1")],
                    "2026-06-24", cols)
        write_picks(picks, latest, [self._row("2026-06-24", "leaders", "AAA", "2")],
                    "2026-06-24", cols)
        all_rows = list(csv.DictReader(open(picks)))
        assert len(all_rows) == 1
        assert all_rows[0]["Price"] == "2"  # last write wins

    def test_migration_backfills_blank_for_new_column(self, tmp_path):
        picks = tmp_path / "picks.csv"
        latest = tmp_path / "picks_latest.csv"
        write_picks(picks, latest, [self._row("2026-06-23", "leaders", "AAA")],
                    "2026-06-23", ["date", "list_category", "ticker", "Price"])
        # New run adds a column → old rows get a blank for it (superset migration).
        new_cols = ["date", "list_category", "ticker", "Price", "NewCol"]
        write_picks(picks, latest,
                    [{"date": "2026-06-24", "list_category": "leaders",
                      "ticker": "BBB", "Price": "9", "NewCol": "x"}],
                    "2026-06-24", new_cols)
        all_rows = list(csv.DictReader(open(picks)))
        assert "NewCol" in all_rows[0]
        old = [r for r in all_rows if r["ticker"] == "AAA"][0]
        assert old["NewCol"] == ""  # backfilled blank


# ---------------------------------------------------------------------------
# flip_validated (G4)
# ---------------------------------------------------------------------------

class TestFlipValidated:
    def test_flips_only_scraped_groups(self, tmp_path):
        path = tmp_path / "slugs.csv"
        with open(path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["industry_name", "ind_slug", "validated", "note"])
            w.writeheader()
            w.writerow({"industry_name": "Semiconductors", "ind_slug": "semiconductors",
                        "validated": "false", "note": ""})
            w.writerow({"industry_name": "Banks - Regional", "ind_slug": "banksregional",
                        "validated": "false", "note": ""})
        flip_validated(path, {"Semiconductors"})
        rows = {r["industry_name"]: r for r in csv.DictReader(open(path))}
        assert rows["Semiconductors"]["validated"] == "true"
        assert rows["Banks - Regional"]["validated"] == "false"


# ---------------------------------------------------------------------------
# selector_versions.json registry
# ---------------------------------------------------------------------------

class TestSelectorRegistry:
    def _load(self):
        return json.loads(pc.SELECTOR_VERSIONS_PATH.read_text())

    def test_active_version_has_exactly_one_entry(self):
        reg = self._load()
        matches = [v for v in reg["versions"] if v["version"] == SELECTOR_VERSION]
        assert len(matches) == 1

    def test_current_matches_active_constant(self):
        assert self._load()["current"] == SELECTOR_VERSION

    def test_versions_unique_and_monotonic(self):
        versions = [v["version"] for v in self._load()["versions"]]
        assert len(versions) == len(set(versions)), "duplicate selector versions"
        nums = [int(v.lstrip("v")) for v in versions]
        # Registry is newest-first → strictly decreasing integers.
        assert nums == sorted(nums, reverse=True)
        assert nums == list(range(max(nums), max(nums) - len(nums), -1)), "non-contiguous"

    def test_every_entry_has_params_and_description(self):
        for v in self._load()["versions"]:
            assert v.get("description"), f"{v['version']} missing description"
            assert isinstance(v.get("params"), dict) and v["params"], \
                f"{v['version']} missing params block"

    def test_published_entries_immutable(self):
        # Pin a hash of every NON-active (published, frozen) entry. Editing a
        # frozen entry's content fails CI (ADR-007 immutability rule). When a new
        # active version is published, the previously-active entry becomes frozen
        # and its hash is added here.
        FROZEN_HASHES = {
            # v1 frozen when v2 (dedup backfill fix) became active 2026-07-02.
            "v1": "0550518c11ffd07da2cd5b103886745b3cd8e592d83b77e7f121b1e3860ef644",
            # v2 frozen when v3 (leaders core 8->11, all_green bucket, cap 20->27)
            # became active 2026-08-24.
            "v2": "c3ce50a3624b16a0c67d46f27dfdfd1a6cbb88502ac7ab9e779f2cc290f8b92b",
        }
        for v in self._load()["versions"]:
            if v["version"] == SELECTOR_VERSION:
                continue
            h = hashlib.sha256(
                json.dumps(v, sort_keys=True).encode("utf-8")
            ).hexdigest()
            assert v["version"] in FROZEN_HASHES, \
                f"frozen entry {v['version']} not pinned — add its hash"
            assert h == FROZEN_HASHES[v["version"]], \
                f"frozen entry {v['version']} was edited (hash mismatch)"


# ---------------------------------------------------------------------------
# Schema — golden header sync + superset/reorder guard
# ---------------------------------------------------------------------------

class TestSchema:
    def test_config_labels_match_golden_header(self):
        golden = [l for l in GOLDEN_HEADER_PATH.read_text().splitlines() if l]
        assert pc.finviz_cols() == golden, (
            "screener_config.json labels drifted from the golden 84-col header"
        )

    def test_picks_columns_layout(self):
        cols = pc.picks_columns()
        assert cols[:6] == pc.PICKS_LEAD_COLS
        # grp_* block is followed by METRICS_COLS (Phase 3a superset append)
        grp_start = 6 + 84
        assert cols[grp_start:grp_start + len(pc.PICKS_GRP_COLS)] == pc.PICKS_GRP_COLS
        # METRICS_COLS (Phase 3a) then TRAILING_COLS (B-2) are the two trailing blocks.
        metrics_start = grp_start + len(pc.PICKS_GRP_COLS)
        assert cols[metrics_start:metrics_start + len(pc.METRICS_COLS)] == pc.METRICS_COLS
        assert cols[-len(pc.TRAILING_COLS):] == pc.TRAILING_COLS
        assert len(cols) == (6 + 84 + len(pc.PICKS_GRP_COLS)
                             + len(pc.METRICS_COLS) + len(pc.TRAILING_COLS))

    def test_grp_cols_count_is_19(self):
        assert len(pc.PICKS_GRP_COLS) == 19

    def test_picks_header_is_superset_of_golden(self):
        # Reorder/removal guard: the 84 Finviz labels appear in-order as a
        # contiguous block → removing or reordering a column would break this.
        cols = pc.picks_columns()
        golden = [l for l in GOLDEN_HEADER_PATH.read_text().splitlines() if l]
        assert cols[6:6 + len(golden)] == golden


# ---------------------------------------------------------------------------
# ensure_picks_csv — collected_at backfill migration
# ---------------------------------------------------------------------------

class TestEnsurePicksCsvCollectedAt:
    def _old_cols_no_collected_at(self):
        config = pc.load_config()
        old_lead = ["date", "list_category", "selector_version", "group", "ticker"]
        return old_lead + pc.finviz_cols(config) + pc.PICKS_GRP_COLS + pc.METRICS_COLS

    def test_backfills_collected_at_from_cron_time(self, tmp_path):
        old_cols = self._old_cols_no_collected_at()
        csv_path = tmp_path / "picks.csv"
        latest_path = tmp_path / "picks_latest.csv"
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=old_cols, extrasaction="ignore")
            writer.writeheader()
            writer.writerow({c: "" for c in old_cols} | {
                "date": "2026-06-25", "list_category": "leaders",
                "selector_version": "v1", "group": "G", "ticker": "AAA",
            })

        ensure_picks_csv(csv_path, latest_path)

        with open(csv_path) as f:
            reader = csv.DictReader(f)
            assert "collected_at" in reader.fieldnames
            rows = list(reader)
        assert rows[0]["collected_at"] == f"2026-06-25T{pc.COLLECTED_AT_CRON_UTC}Z"

        with open(latest_path) as f:
            latest_rows = list(csv.DictReader(f))
        assert latest_rows[0]["collected_at"] == f"2026-06-25T{pc.COLLECTED_AT_CRON_UTC}Z"

    def test_noop_when_collected_at_present(self, tmp_path):
        all_cols = pc.picks_columns()
        csv_path = tmp_path / "picks.csv"
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=all_cols)
            writer.writeheader()
            writer.writerow({c: "" for c in all_cols})
        mtime_before = csv_path.stat().st_mtime
        ensure_picks_csv(csv_path)
        assert csv_path.stat().st_mtime == mtime_before


class TestHeaderDriftGuard:
    """PICKS-2-HDR: missing_header_labels + header_check_action tiered policy."""

    EXPECTED = ["Ticker", "Company", "Price", "Change", "Volume"]

    def test_no_drift_returns_empty_and_ok(self):
        results = {"G": (self.EXPECTED, [{"Ticker": "AAPL"}])}
        missing = missing_header_labels(results, self.EXPECTED)
        assert missing == []
        assert header_check_action(missing, len(self.EXPECTED)) == "ok"

    def test_renamed_label_detected_as_missing(self):
        drifted = ["Ticker", "Company Name", "Price", "Change", "Volume"]
        results = {"G": (drifted, [{"Ticker": "AAPL"}])}
        assert missing_header_labels(results, self.EXPECTED) == ["Company"]

    def test_label_present_in_any_group_not_missing(self):
        # All groups share one &c= list — one group proving a label maps clears it.
        results = {
            "A": (["Ticker", "Company", "Price", "Change"], [{"Ticker": "X"}]),
            "B": (["Ticker", "Company", "Price", "Volume"], [{"Ticker": "Y"}]),
        }
        assert missing_header_labels(results, self.EXPECTED) == []

    def test_empty_header_groups_ignored(self):
        # A wrong slug (header == [], 0 rows) is the suspect-slug path, not drift.
        results = {
            "good": (self.EXPECTED, [{"Ticker": "AAPL"}]),
            "bad": ([], []),
        }
        assert missing_header_labels(results, self.EXPECTED) == []

    def test_all_empty_scrape_returns_no_missing(self):
        # Nothing usable scraped → empty-scrape guard's job, not this guard's.
        assert missing_header_labels({"G": ([], [])}, self.EXPECTED) == []
        assert missing_header_labels({}, self.EXPECTED) == []

    def test_missing_ticker_aborts(self):
        assert header_check_action(["Ticker"], 84) == "abort"

    def test_small_drift_warns(self):
        # 1 missing of 84 is well under HEADER_MISSING_ABORT_FRAC → warn tier.
        assert 1 <= HEADER_MISSING_ABORT_FRAC * 84
        assert header_check_action(["P/E"], 84) == "warn"

    def test_large_drift_aborts(self):
        missing = [f"col{i}" for i in range(int(HEADER_MISSING_ABORT_FRAC * 84) + 1)]
        assert header_check_action(missing, 84) == "abort"

    def test_threshold_boundary_is_warn(self):
        # Exactly at the fraction (not above) stays in the warn tier.
        at_threshold = [f"col{i}" for i in range(int(HEADER_MISSING_ABORT_FRAC * 100))]
        assert header_check_action(at_threshold, 100) == "warn"
