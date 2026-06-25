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
    write_picks,
    flip_validated,
    _PCTILE_CUTOFF,
)
from picks_config import (
    SELECTOR_VERSION,
    DAILY_GROUP_CAP,
    LEADER_SS_SLOTS,
    LEADER_MC_SLOTS,
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
]


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
        # 12 groups; sum_mid increases with index so ordering is deterministic.
        rows = []
        for i in range(12):
            rows.append(_delta_row(
                f"G{i:02d}",
                rank_month=i + 1, rank_quarter=i + 1, rank_half=i + 1,
                momentum_score=1.0 - i * 0.05,
                momentum_confirmed=0.9 - i * 0.01,
            ))
        return _make_df(rows)

    def test_picks_eight_by_sum_of_ranks(self):
        sels = select_groups(self._leaders_df())
        ss = [s for s in sels if s["grp_rank_basis"] == "sustained_strength"]
        assert len(ss) == LEADER_SS_SLOTS
        # Lowest sum-of-ranks first: G00..G07 (sums 3,6,9,...).
        assert [s["group"] for s in ss] == [f"G{i:02d}" for i in range(8)]
        # grp_category_rank is 1..8 in that order.
        assert [s["grp_category_rank"] for s in ss] == list(range(1, 9))
        assert ss[0]["grp_sum_mid_rank"] == 3  # 1+1+1

    def test_two_freshness_fills_not_in_core(self):
        sels = select_groups(self._leaders_df())
        fills = [s for s in sels if s["grp_rank_basis"] == "freshness_fill"]
        assert len(fills) == LEADER_MC_SLOTS
        core = {s["group"] for s in sels if s["grp_rank_basis"] == "sustained_strength"}
        for f in fills:
            assert f["group"] not in core
        # momentum_confirmed desc among the remaining (G08 highest of the rest).
        assert fills[0]["group"] == "G08"
        assert fills[0]["grp_category_rank"] == 1

    def test_no_hard_intersection_gate_degrades_gracefully(self):
        # Only 3 groups are "top" on all timeframes, but sum-of-ranks still fills 8.
        rows = [_delta_row(f"H{i:02d}", rank_month=i + 1, rank_quarter=i + 1,
                           rank_half=i + 1, momentum_confirmed=0.5)
                for i in range(8)]
        sels = select_groups(_make_df(rows))
        ss = [s for s in sels if s["grp_rank_basis"] == "sustained_strength"]
        assert len(ss) == 8  # not gated down to an intersection subset


# ---------------------------------------------------------------------------
# select_groups — emerging / accel / rs_new_high floors + empty buckets
# ---------------------------------------------------------------------------

class TestBuckets:
    def _base_leaders(self, n=8):
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
        header, rows, pages = paginate_group(_page_fetcher(45), "x")
        assert len(rows) == 45
        assert pages == 3  # 20 + 20 + 5

    def test_exact_page_boundary_stops(self):
        # 40 rows = 2 full pages; 3rd page is empty → stop.
        header, rows, pages = paginate_group(_page_fetcher(40), "x")
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
        rows = build_pick_rows("2026-06-24", sels, scraped, ["Ticker", "Price"])
        assert len(rows) == 4  # 2 stocks × 2 categories
        cats = {r["list_category"] for r in rows}
        assert cats == {"leaders", "accel"}
        assert rows[0]["Price"] == "100"

    def test_skips_rows_without_ticker(self):
        sels = [{"group": "G", "list_category": "leaders", "selector_version": "v1",
                 **{c: "" for c in pc.PICKS_GRP_COLS}}]
        rows = build_pick_rows("2026-06-24", sels, [{"Ticker": "", "Price": "1"}],
                               ["Ticker", "Price"])
        assert rows == []


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
            # no frozen (non-active) entries yet — v1 is the active version.
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
        assert cols[:5] == pc.PICKS_LEAD_COLS
        assert cols[-len(pc.PICKS_GRP_COLS):] == pc.PICKS_GRP_COLS
        assert len(cols) == 5 + 84 + len(pc.PICKS_GRP_COLS)

    def test_grp_cols_count_is_19(self):
        assert len(pc.PICKS_GRP_COLS) == 19

    def test_picks_header_is_superset_of_golden(self):
        # Reorder/removal guard: the 84 Finviz labels appear in-order as a
        # contiguous block → removing or reordering a column would break this.
        cols = pc.picks_columns()
        golden = [l for l in GOLDEN_HEADER_PATH.read_text().splitlines() if l]
        assert cols[5:5 + len(golden)] == golden
