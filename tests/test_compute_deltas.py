"""
Tests for pure functions in scripts/compute_deltas.py.
All tests use in-memory data — no CSV I/O.
"""

import csv
import math
import sys
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import compute_deltas as cd


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def snapshot_3():
    """Three-row snapshot with clean perf data."""
    return pd.DataFrame({
        "name": ["Tech", "Energy", "Finance"],
        "perf_day":     [3.0, 1.0, 2.0],
        "perf_week":    [3.0, 1.0, 2.0],
        "perf_month":   [1.0, 3.0, 2.0],
        "perf_quarter": [2.0, 1.0, 3.0],
        "perf_half":    [1.0, 2.0, 3.0],
        "perf_year":    [3.0, 2.0, 1.0],
        "perf_ytd":     [2.0, 3.0, 1.0],
    })


# ---------------------------------------------------------------------------
# find_nearest_date
# ---------------------------------------------------------------------------

class TestFindNearestDate:
    def test_exact_match(self):
        dates = [date(2026, 1, 1), date(2026, 1, 8), date(2026, 1, 15)]
        assert cd.find_nearest_date(dates, date(2026, 1, 8)) == date(2026, 1, 8)

    def test_within_tolerance(self):
        dates = [date(2026, 1, 1), date(2026, 1, 10)]
        # target is Jan 13; Jan 10 is 3 days prior — within 5-day tolerance
        assert cd.find_nearest_date(dates, date(2026, 1, 13)) == date(2026, 1, 10)

    def test_beyond_tolerance_returns_none(self):
        dates = [date(2026, 1, 1)]
        # target is Jan 10; Jan 1 is 9 days prior — beyond 5-day tolerance
        assert cd.find_nearest_date(dates, date(2026, 1, 10)) is None

    def test_empty_list_returns_none(self):
        assert cd.find_nearest_date([], date(2026, 1, 1)) is None

    def test_no_dates_before_target_returns_none(self):
        dates = [date(2026, 1, 5)]
        assert cd.find_nearest_date(dates, date(2026, 1, 1)) is None


# ---------------------------------------------------------------------------
# find_trading_date_back
# ---------------------------------------------------------------------------

class TestFindTradingDateBack:
    # Sorted trading days with a weekend gap (Jan 9-10 are Fri/Mon-ish) — the
    # function counts sessions, so calendar gaps are irrelevant.
    DATES = [date(2026, 1, 5), date(2026, 1, 6), date(2026, 1, 7),
             date(2026, 1, 8), date(2026, 1, 9), date(2026, 1, 12),
             date(2026, 1, 13)]

    def test_counts_sessions_not_calendar_days(self):
        # 5 sessions before Jan 13 is Jan 6 (skips the weekend gap entirely).
        assert cd.find_trading_date_back(self.DATES, date(2026, 1, 13), 5) == date(2026, 1, 6)

    def test_one_session_back(self):
        assert cd.find_trading_date_back(self.DATES, date(2026, 1, 12), 1) == date(2026, 1, 9)

    def test_insufficient_history_returns_none(self):
        # Only 4 sessions exist before Jan 9 here; ask for 50.
        assert cd.find_trading_date_back(self.DATES, date(2026, 1, 13), 50) is None

    def test_target_not_present_returns_none(self):
        assert cd.find_trading_date_back(self.DATES, date(2026, 1, 11), 1) is None

    def test_zero_offset_returns_target(self):
        assert cd.find_trading_date_back(self.DATES, date(2026, 1, 8), 0) == date(2026, 1, 8)


# ---------------------------------------------------------------------------
# compute_ranks
# ---------------------------------------------------------------------------

class TestComputeRanks:
    def test_rank_1_is_best_performer(self, snapshot_3):
        result = cd.compute_ranks(snapshot_3)
        # perf_week: Tech=3.0 (best), Finance=2.0, Energy=1.0
        assert result.loc[result["name"] == "Tech", "rank_week"].iloc[0] == 1
        assert result.loc[result["name"] == "Energy", "rank_week"].iloc[0] == 3

    def test_nan_goes_to_bottom(self):
        df = pd.DataFrame({
            "name": ["A", "B", "C"],
            "perf_week": [2.0, float("nan"), 1.0],
            "perf_month": [1.0, 2.0, 3.0],
            "perf_quarter": [1.0, 2.0, 3.0],
            "perf_half": [1.0, 2.0, 3.0],
            "perf_year": [1.0, 2.0, 3.0],
            "perf_ytd": [1.0, 2.0, 3.0],
        })
        result = cd.compute_ranks(df)
        # NaN gets rank 3 (bottom) via na_option='bottom'
        assert result.loc[result["name"] == "B", "rank_week"].iloc[0] == 3

    def test_does_not_mutate_input(self, snapshot_3):
        original_cols = list(snapshot_3.columns)
        cd.compute_ranks(snapshot_3)
        assert list(snapshot_3.columns) == original_cols


# ---------------------------------------------------------------------------
# compute_momentum
# ---------------------------------------------------------------------------

class TestComputeMomentum:
    def test_scores_in_0_1_range(self, snapshot_3):
        scores = cd.compute_momentum(snapshot_3)
        assert scores.between(0.0, 1.0).all()

    def test_best_performer_has_highest_score(self, snapshot_3):
        # Tech leads perf_week/perf_year/perf_day; should score high overall
        scores = cd.compute_momentum(snapshot_3)
        snapshot_3 = snapshot_3.copy()
        snapshot_3["score"] = scores
        # Just verify no score is exactly equal across the board (all different)
        assert scores.nunique() > 1

    def test_single_row_returns_nan(self):
        df = pd.DataFrame({
            "name": ["Tech"],
            "perf_day": [1.0], "perf_week": [1.0], "perf_month": [1.0],
            "perf_quarter": [1.0], "perf_half": [1.0], "perf_year": [1.0],
            "perf_ytd": [1.0],
        })
        scores = cd.compute_momentum(df)
        assert math.isnan(scores.iloc[0])

    def test_all_nan_column_ignored(self):
        df = pd.DataFrame({
            "name": ["A", "B"],
            "perf_day":     [float("nan"), float("nan")],
            "perf_week":    [2.0, 1.0],
            "perf_month":   [2.0, 1.0],
            "perf_quarter": [2.0, 1.0],
            "perf_half":    [2.0, 1.0],
            "perf_year":    [2.0, 1.0],
            "perf_ytd":     [2.0, 1.0],
        })
        scores = cd.compute_momentum(df)
        # Should not crash and A should score higher than B
        assert scores.iloc[0] > scores.iloc[1]


# ---------------------------------------------------------------------------
# _fmt
# ---------------------------------------------------------------------------

class TestFmt:
    def test_nan_returns_empty_string(self):
        assert cd._fmt(float("nan")) == ""

    def test_none_returns_empty_string(self):
        assert cd._fmt(None) == ""

    def test_valid_float_passes_through(self):
        assert cd._fmt(3.14) == 3.14

    def test_zero_passes_through(self):
        assert cd._fmt(0.0) == 0.0

    def test_negative_passes_through(self):
        assert cd._fmt(-5.0) == -5.0

    def test_string_nan_returns_empty_string(self):
        # "nan" as a string coerces to float nan
        assert cd._fmt("nan") == ""


# ---------------------------------------------------------------------------
# compute_rank_agreement
# ---------------------------------------------------------------------------

class TestComputeRankAgreement:
    def _make_df(self, rank_month, rank_quarter, rank_half):
        n = len(rank_month)
        return pd.DataFrame({
            "name": [f"G{i}" for i in range(n)],
            "rank_month":   rank_month,
            "rank_quarter": rank_quarter,
            "rank_half":    rank_half,
        })

    def test_perfect_agreement_scores_1(self):
        # All three timeframes give identical ranks → std = 0 → agreement = 1
        df = self._make_df([1, 2, 3], [1, 2, 3], [1, 2, 3])
        scores = cd.compute_rank_agreement(df)
        assert all(abs(s - 1.0) < 1e-9 for s in scores)

    def test_maximum_disagreement_scores_near_0(self):
        # Row 0: rank 1 in month, rank 3 in quarter, rank 3 in half → pct [1, 0, 0]
        # std([1,0,0]) = 1/sqrt(3) → agreement = 0
        df = self._make_df([1, 2, 3], [3, 2, 1], [3, 2, 1])
        scores = cd.compute_rank_agreement(df)
        assert scores.iloc[0] < 0.1

    def test_scores_in_0_1_range(self, snapshot_3):
        df = cd.compute_ranks(snapshot_3)
        scores = cd.compute_rank_agreement(df)
        assert scores.between(0.0, 1.0).all()

    def test_single_row_returns_nan(self):
        df = pd.DataFrame({
            "name": ["A"],
            "rank_month": [1], "rank_quarter": [1], "rank_half": [1],
        })
        scores = cd.compute_rank_agreement(df)
        assert math.isnan(scores.iloc[0])

    def test_missing_rank_columns_returns_nan(self):
        # Only one rank column available → can't compute agreement
        df = pd.DataFrame({
            "name": ["A", "B"],
            "rank_month": [1, 2],
        })
        scores = cd.compute_rank_agreement(df)
        assert all(math.isnan(s) for s in scores)

    def test_two_rank_columns_returns_nan(self):
        # With 2 of 3 columns the normalizer (_MAX_STD_3) is wrong for 2 values;
        # require all 3 to avoid misleading scores.
        df = pd.DataFrame({
            "name": ["A", "B"],
            "rank_month": [1, 2],
            "rank_quarter": [2, 1],
        })
        scores = cd.compute_rank_agreement(df)
        assert all(math.isnan(s) for s in scores)

    def test_middle_of_pack_has_moderate_agreement(self):
        # Mixed ranks — should be between 0 and 1
        df = self._make_df([1, 2, 3], [2, 1, 3], [3, 2, 1])
        scores = cd.compute_rank_agreement(df)
        assert all(0.0 <= s <= 1.0 for s in scores)
        # No perfect agreement since ranks differ per timeframe
        assert not any(abs(s - 1.0) < 1e-9 for s in scores)


# ---------------------------------------------------------------------------
# ensure_deltas_csv
# ---------------------------------------------------------------------------

class TestEnsureDeltasCsv:
    def _write_old_schema_csv(self, path, rows):
        """Write a deltas CSV using a schema that's missing rank_day."""
        old_cols = [c for c in cd.DELTA_COLUMNS if c != "rank_day"]
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=old_cols)
            writer.writeheader()
            for row in rows:
                writer.writerow({c: row.get(c, "") for c in old_cols})

    def test_creates_file_when_missing(self, tmp_path):
        csv_path = tmp_path / "deltas.csv"
        result = cd.ensure_deltas_csv(csv_path)
        assert csv_path.exists()
        assert result is False
        with open(csv_path, newline="") as f:
            assert csv.DictReader(f).fieldnames == cd.DELTA_COLUMNS

    def test_no_op_when_schema_matches(self, tmp_path):
        csv_path = tmp_path / "deltas.csv"
        cd.ensure_deltas_csv(csv_path)
        mtime = csv_path.stat().st_mtime
        result = cd.ensure_deltas_csv(csv_path)
        assert result is False
        assert csv_path.stat().st_mtime == mtime

    def test_migration_updates_schema(self, tmp_path):
        csv_path = tmp_path / "deltas.csv"
        self._write_old_schema_csv(csv_path, [{"date": "2026-01-01", "name": "Tech"}])
        result = cd.ensure_deltas_csv(csv_path)
        assert result is True
        with open(csv_path, newline="") as f:
            reader = csv.DictReader(f)
            assert reader.fieldnames == cd.DELTA_COLUMNS

    def test_migration_preserves_existing_data(self, tmp_path):
        csv_path = tmp_path / "deltas.csv"
        self._write_old_schema_csv(csv_path, [
            {"date": "2026-01-01", "name": "Tech", "rank_week": "1"},
            {"date": "2026-01-01", "name": "Energy", "rank_week": "2"},
        ])
        cd.ensure_deltas_csv(csv_path)
        with open(csv_path, newline="") as f:
            rows = list(csv.DictReader(f))
        assert len(rows) == 2
        assert rows[0]["name"] == "Tech"
        assert rows[0]["rank_week"] == "1"
        assert rows[1]["name"] == "Energy"

    def test_migration_leaves_no_tmp_file(self, tmp_path):
        csv_path = tmp_path / "deltas.csv"
        self._write_old_schema_csv(csv_path, [{"date": "2026-01-01", "name": "A"}])
        cd.ensure_deltas_csv(csv_path)
        assert not csv_path.with_suffix(".tmp").exists()


# ---------------------------------------------------------------------------
# compute_for_group — rank_day backfill after migration
# ---------------------------------------------------------------------------

class TestComputeForGroupMigration:
    """After schema migration, compute_for_group must recompute target-date rows."""

    def _write_old_deltas(self, path, rows):
        """Write a deltas CSV using a schema without rank_day."""
        old_cols = [c for c in cd.DELTA_COLUMNS if c != "rank_day"]
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=old_cols)
            writer.writeheader()
            for row in rows:
                writer.writerow({c: row.get(c, "") for c in old_cols})

    def test_rank_day_populated_after_migration(self, tmp_path, tmp_snapshot_csv):
        delta_path = tmp_path / "deltas.csv"
        # Pre-populate deltas with old schema missing rank_day
        self._write_old_deltas(delta_path, [
            {"date": "2026-06-09", "name": "Technology", "rank_week": "1"},
            {"date": "2026-06-09", "name": "Energy", "rank_week": "2"},
            {"date": "2026-06-09", "name": "Utilities", "rank_week": "3"},
        ])

        cd.compute_for_group(
            "sector",
            snap_path=tmp_snapshot_csv,
            delta_path=delta_path,
        )

        with open(delta_path, newline="") as f:
            rows = {r["name"]: r for r in csv.DictReader(f)}

        # rank_day must be filled (Technology has highest perf_day=1.5 → rank 1)
        assert rows["Technology"]["rank_day"] == "1.0"
        assert rows["Energy"]["rank_day"] != ""
        assert rows["Utilities"]["rank_day"] != ""

    def test_non_target_date_rows_preserved_after_migration(self, tmp_path, tmp_snapshot_csv):
        delta_path = tmp_path / "deltas.csv"
        self._write_old_deltas(delta_path, [
            # older row — should survive untouched
            {"date": "2026-06-01", "name": "Technology", "rank_week": "2"},
            # target-date row — will be evicted and recomputed
            {"date": "2026-06-09", "name": "Technology", "rank_week": "1"},
            {"date": "2026-06-09", "name": "Energy", "rank_week": "2"},
            {"date": "2026-06-09", "name": "Utilities", "rank_week": "3"},
        ])

        cd.compute_for_group(
            "sector",
            snap_path=tmp_snapshot_csv,
            delta_path=delta_path,
        )

        with open(delta_path, newline="") as f:
            rows = list(csv.DictReader(f))

        dates = [r["date"] for r in rows]
        assert "2026-06-01" in dates  # older row preserved
        tech_old = next(r for r in rows if r["date"] == "2026-06-01" and r["name"] == "Technology")
        assert tech_old["rank_week"] == "2"


class TestComputeForGroupLastWriteWins:
    """A re-run for an already-computed date must recompute, not skip (stale-delta fix)."""

    def _write_deltas(self, path, rows):
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=cd.DELTA_COLUMNS)
            writer.writeheader()
            for row in rows:
                writer.writerow({c: row.get(c, "") for c in cd.DELTA_COLUMNS})

    def test_existing_target_date_rows_are_recomputed(self, tmp_path, tmp_snapshot_csv):
        delta_path = tmp_path / "deltas.csv"
        # Stale rows from an earlier (e.g. mid-morning) run with wrong ranks.
        self._write_deltas(delta_path, [
            {"date": "2026-06-09", "name": "Technology", "rank_day": "9.0"},
            {"date": "2026-06-09", "name": "Energy", "rank_day": "9.0"},
            {"date": "2026-06-09", "name": "Utilities", "rank_day": "9.0"},
        ])

        cd.compute_for_group("sector", snap_path=tmp_snapshot_csv, delta_path=delta_path)

        with open(delta_path, newline="") as f:
            rows = list(csv.DictReader(f))

        # No duplicates — exactly one row per name for the target date.
        target = [r for r in rows if r["date"] == "2026-06-09"]
        assert len(target) == 3
        by_name = {r["name"]: r for r in target}
        # Recomputed: Technology has the highest perf_day (1.5) → rank_day 1.0.
        assert by_name["Technology"]["rank_day"] == "1.0"

    def test_skips_eviction_when_target_date_missing(self, tmp_path, tmp_snapshot_csv):
        # If the snapshot has no rows for the requested date, existing delta rows
        # for other dates must survive (eviction happens only after the data check).
        delta_path = tmp_path / "deltas.csv"
        self._write_deltas(delta_path, [
            {"date": "2026-06-09", "name": "Technology", "rank_day": "1.0"},
        ])

        cd.compute_for_group(
            "sector", target_date_str="2026-05-01",
            snap_path=tmp_snapshot_csv, delta_path=delta_path,
        )

        with open(delta_path, newline="") as f:
            rows = list(csv.DictReader(f))
        assert any(r["date"] == "2026-06-09" for r in rows)


# ---------------------------------------------------------------------------
# Momentum variants
# ---------------------------------------------------------------------------

class TestWeightedMomentum:
    def test_range_and_best_worst(self, snapshot_3):
        s = cd.weighted_momentum(snapshot_3, cd.WEIGHTS_MID)
        assert s.between(0.0, 1.0).all()
        # Finance leads quarter (best) and is mid on month — the two metrics the
        # mid profile weights heaviest — so it scores highest.
        assert s.idxmax() == snapshot_3.index[snapshot_3["name"] == "Finance"][0]

    def test_single_row_is_nan(self):
        df = pd.DataFrame({"name": ["A"], "perf_week": [1.0]})
        assert math.isnan(cd.weighted_momentum(df, cd.WEIGHTS_FAST).iloc[0])

    def test_all_nan_column_excluded(self):
        df = pd.DataFrame({
            "name": ["A", "B"],
            "perf_day": [1.0, 2.0],
            "perf_week": [float("nan"), float("nan")],
        })
        s = cd.weighted_momentum(df, {"perf_day": 1.0, "perf_week": 5.0})
        # perf_week all-NaN drops out; result driven entirely by perf_day.
        assert s.between(0.0, 1.0).all()
        assert not s.isna().any()

    def test_fast_vs_mid_differ_on_horizon_split(self):
        # A strong short-term, weak long-term; B the reverse.
        df = pd.DataFrame({
            "name": ["A", "B"],
            "perf_day": [2.0, 1.0], "perf_week": [2.0, 1.0],
            "perf_month": [1.0, 2.0], "perf_quarter": [1.0, 2.0],
            "perf_half": [1.0, 2.0], "perf_year": [1.0, 2.0], "perf_ytd": [1.0, 2.0],
        })
        fast = cd.weighted_momentum(df, cd.WEIGHTS_FAST)
        mid = cd.weighted_momentum(df, cd.WEIGHTS_MID)
        ai = df.index[df["name"] == "A"][0]
        # A scores relatively better under fast weighting than mid.
        assert fast[ai] > mid[ai]


class TestComputeRegime:
    def test_emerging_vs_fading_sign(self):
        df = pd.DataFrame({
            "name": ["Emerging", "Fading"],
            "perf_day": [2.0, 1.0], "perf_week": [2.0, 1.0],
            "perf_half": [1.0, 2.0], "perf_year": [1.0, 2.0], "perf_ytd": [1.0, 2.0],
        })
        s = cd.compute_regime(df)
        ei = df.index[df["name"] == "Emerging"][0]
        fi = df.index[df["name"] == "Fading"][0]
        assert s[ei] > 0  # strong short, weak long
        assert s[fi] < 0

    def test_single_row_is_nan(self):
        df = pd.DataFrame({"name": ["A"], "perf_day": [1.0], "perf_half": [1.0]})
        assert math.isnan(cd.compute_regime(df).iloc[0])

    def test_missing_bucket_is_nan(self):
        # No long-horizon metrics at all → NaN.
        df = pd.DataFrame({
            "name": ["A", "B"], "perf_day": [1.0, 2.0], "perf_week": [1.0, 2.0],
        })
        assert cd.compute_regime(df).isna().all()


class TestRankTrendSlope:
    def _hist(self, ranks_by_date):
        """Build a multi-date snapshot where group 'A' takes the given perf_ytd
        values (others fill the field)."""
        rows = []
        for d, a_perf in ranks_by_date.items():
            rows.append({"date": d, "name": "A", "perf_ytd": a_perf})
            rows.append({"date": d, "name": "B", "perf_ytd": 0.0})
            rows.append({"date": d, "name": "C", "perf_ytd": -5.0})
        return pd.DataFrame(rows)

    def test_improving_rank_positive_slope(self):
        # A's perf_ytd rises from below B (0.0) to above it → rank improves
        # (rank 2 → rank 1) → positive (negated) slope.
        dates = [date(2026, 1, i) for i in range(1, 6)]
        df = self._hist({d: float(i - 2) for i, d in enumerate(dates)})
        s = cd.compute_rank_trend_slope(df, dates, dates[-1])
        assert s["A"] > 0

    def test_flat_rank_zero_slope(self):
        dates = [date(2026, 1, i) for i in range(1, 6)]
        df = self._hist({d: 10.0 for d in dates})  # A always best, constant
        s = cd.compute_rank_trend_slope(df, dates, dates[-1])
        assert abs(s["A"]) < 1e-9

    def test_insufficient_history_returns_empty(self):
        dates = [date(2026, 1, 1)]
        df = self._hist({dates[0]: 5.0})
        s = cd.compute_rank_trend_slope(df, dates, dates[0])
        assert s.empty


class TestMomentumAccelIntegration:
    """momentum_accel is assembled in compute_for_group; verify sign end-to-end."""

    def _snap(self, path, dates_perf):
        cols = cd.SNAPSHOT_COLS
        rows = []
        for d, perfs in dates_perf.items():
            for name, p in perfs.items():
                row = {c: "" for c in cols}
                row.update({"date": d, "name": name, "group_type": "sector"})
                for k in ["perf_day", "perf_week", "perf_month", "perf_quarter",
                          "perf_half", "perf_year", "perf_ytd"]:
                    row[k] = p
                rows.append(row)
        with open(path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            w.writerows(rows)

    def test_no_prior_frame_is_blank(self, tmp_path):
        snap = tmp_path / "snapshots.csv"
        self._snap(snap, {"2026-06-09": {"A": 3.0, "B": 1.0, "C": 2.0}})
        delta = tmp_path / "deltas.csv"
        cd.compute_for_group("sector", snap_path=snap, delta_path=delta)
        rows = list(csv.DictReader(open(delta)))
        # Only one date → no ACCEL_WINDOW history → momentum_accel empty.
        assert all(r["momentum_accel"] == "" for r in rows)

    def test_improving_momentum_accel_positive(self, tmp_path):
        """Group that goes from weak to strong over ACCEL_WINDOW sessions has
        momentum_accel > 0 on the final date (plan spec: improving → positive)."""
        snap = tmp_path / "snapshots.csv"
        # 12 dates total so the last date has a valid 10-session prior frame.
        # A is weak for dates 1–8 (rank last), then strong for dates 9–12 (rank first).
        # B and C stay flat at 0.0 throughout.
        date_perfs = {}
        for i in range(1, 9):
            date_perfs[f"2026-01-{i:02d}"] = {"A": -5.0, "B": 0.0, "C": 0.0}
        for i in range(9, 13):
            date_perfs[f"2026-01-{i:02d}"] = {"A": 5.0, "B": 0.0, "C": 0.0}
        self._snap(snap, date_perfs)
        delta = tmp_path / "deltas.csv"
        cd.compute_for_group("sector", snap_path=snap, delta_path=delta)
        rows = list(csv.DictReader(open(delta)))
        # Last date is 2026-01-12; A was weak 10 sessions earlier (2026-01-02).
        a_row = next(r for r in rows if r["date"] == "2026-01-12" and r["name"] == "A")
        assert float(a_row["momentum_accel"]) > 0


# ---------------------------------------------------------------------------
# RS pure functions
# ---------------------------------------------------------------------------

@pytest.fixture
def rs_df():
    """Three-row snapshot with rs_* spreads already computed."""
    return pd.DataFrame({
        "name": ["Alpha", "Beta", "Gamma"],
        "rs_day":     [2.0, 0.0, -1.0],
        "rs_week":    [3.0, 1.0, -2.0],
        "rs_month":   [4.0, 0.5, -1.5],
        "rs_quarter": [5.0, 1.0, -3.0],
        "rs_half":    [6.0, 0.5, -2.5],
        "rs_year":    [7.0, 1.0, -4.0],
        "rs_ytd":     [3.5, 0.0, -2.0],
    })


class TestComputeRsScore:
    def test_scores_in_0_1_range(self, rs_df):
        s = cd.compute_rs_score(rs_df)
        assert s.between(0.0, 1.0).all()

    def test_best_rs_has_highest_score(self, rs_df):
        s = cd.compute_rs_score(rs_df)
        # Alpha dominates all timeframes → highest rs_score
        assert s.idxmax() == 0

    def test_worst_rs_has_lowest_score(self, rs_df):
        s = cd.compute_rs_score(rs_df)
        assert s.idxmin() == 2

    def test_single_row_returns_valid_score(self):
        # Breadth is per-group, not cross-sectional — single row is meaningful
        df = pd.DataFrame({"name": ["A"], "rs_week": [1.0], "rs_month": [0.5]})
        s = cd.compute_rs_score(df)
        assert not math.isnan(s.iloc[0])
        assert s.iloc[0] == 1.0  # both cols positive → 100% breadth

    def test_no_rs_columns_returns_nan(self):
        df = pd.DataFrame({"name": ["A", "B"], "perf_week": [1.0, 2.0]})
        s = cd.compute_rs_score(df)
        assert s.isna().all()

    def test_all_nan_rs_column_skipped(self):
        df = pd.DataFrame({
            "name": ["A", "B"],
            "rs_week": [float("nan"), float("nan")],
            "rs_month": [2.0, 1.0],
        })
        s = cd.compute_rs_score(df)
        # rs_week all-NaN skipped; result from rs_month only — no crash
        assert not s.isna().all()


class TestComputeRsAgreement:
    def test_perfect_agreement_scores_1(self):
        # All three RS agreement cols rank the same way
        df = pd.DataFrame({
            "name": ["A", "B", "C"],
            "rs_month":   [3.0, 2.0, 1.0],
            "rs_quarter": [3.0, 2.0, 1.0],
            "rs_half":    [3.0, 2.0, 1.0],
        })
        s = cd.compute_rs_agreement(df)
        assert all(abs(v - 1.0) < 1e-9 for v in s)

    def test_scores_in_0_1_range(self, rs_df):
        s = cd.compute_rs_agreement(rs_df)
        assert s.between(0.0, 1.0).all()

    def test_single_row_returns_valid_score(self):
        # Sign consistency is per-group across timeframes — single row is meaningful
        df = pd.DataFrame({
            "name": ["A"],
            "rs_month": [1.0], "rs_quarter": [1.0], "rs_half": [1.0],
        })
        s = cd.compute_rs_agreement(df)
        assert not math.isnan(s.iloc[0])
        assert abs(s.iloc[0] - 1.0) < 1e-9  # all same sign → perfect agreement

    def test_missing_rs_agreement_cols_returns_nan(self):
        df = pd.DataFrame({
            "name": ["A", "B"],
            "rs_month": [1.0, 2.0],
        })
        s = cd.compute_rs_agreement(df)
        assert s.isna().all()


class TestComputeRsSlope:
    def _make_hist(self, dates, spy_perf_month, group_perf_months):
        """Build a multi-date history and a bench_df for slope computation."""
        group_rows = []
        bench_rows = []
        for d, spy_val, group_vals in zip(dates, spy_perf_month, group_perf_months):
            bench_rows.append({"date": d, "perf_month": spy_val})
            for name, gval in group_vals.items():
                group_rows.append({"date": d, "name": name, "perf_month": gval})
        return pd.DataFrame(group_rows), pd.DataFrame(bench_rows)

    def test_positive_slope_when_rs_building(self):
        # Group A's perf_month beat SPY by increasing amounts over 5 sessions.
        dates = [date(2026, 1, i) for i in range(1, 6)]
        spy = [1.0] * 5
        groups = [{name: v for name, v in [("A", float(i)), ("B", 0.0)]}
                  for i in range(1, 6)]
        df_hist, bench = self._make_hist(dates, spy, groups)
        s = cd.compute_rs_slope(df_hist, bench, dates, dates[-1])
        assert s["A"] > 0

    def test_negative_slope_when_rs_fading(self):
        dates = [date(2026, 1, i) for i in range(1, 6)]
        spy = [5.0] * 5  # SPY at 5; group A falls from 5 to 1 → RS worsens
        groups = [{name: v for name, v in [("A", float(5 - i)), ("B", 0.0)]}
                  for i in range(1, 6)]
        df_hist, bench = self._make_hist(dates, spy, groups)
        s = cd.compute_rs_slope(df_hist, bench, dates, dates[-1])
        assert s["A"] < 0

    def test_no_spy_data_returns_empty(self):
        df_hist = pd.DataFrame({"date": [date(2026, 1, 1)], "name": ["A"], "perf_month": [1.0]})
        bench = pd.DataFrame(columns=["date", "perf_month"])
        s = cd.compute_rs_slope(df_hist, bench, [date(2026, 1, 1)], date(2026, 1, 1))
        assert s.empty

    def test_single_session_returns_empty(self):
        dates = [date(2026, 1, 1)]
        df_hist = pd.DataFrame({"date": dates, "name": ["A"], "perf_month": [1.0]})
        bench = pd.DataFrame({"date": dates, "perf_month": [0.5]})
        s = cd.compute_rs_slope(df_hist, bench, dates, dates[0])
        assert s.empty


class TestComputeRsRegime:
    def test_positive_when_short_rs_leads(self):
        # Alpha beats SPY on recent (week/month) but trails on long-term.
        df = pd.DataFrame({
            "name": ["Alpha", "Beta"],
            "rs_week":    [3.0, 1.0],
            "rs_month":   [2.0, 1.0],
            "rs_quarter": [0.5, 1.0],
            "rs_half":    [0.5, 1.0],
            "rs_year":    [0.0, 1.0],
        })
        s = cd.compute_rs_regime(df)
        assert s.iloc[0] > 0  # Alpha: short RS > long RS

    def test_negative_when_long_rs_leads(self):
        df = pd.DataFrame({
            "name": ["Alpha", "Beta"],
            "rs_week":    [0.0, 1.0],
            "rs_month":   [0.0, 1.0],
            "rs_quarter": [3.0, 1.0],
            "rs_half":    [3.0, 1.0],
            "rs_year":    [3.0, 1.0],
        })
        s = cd.compute_rs_regime(df)
        assert s.iloc[0] < 0  # Alpha: long RS > short RS → fading

    def test_single_row_returns_valid_score(self):
        # Breadth is per-group — single row is meaningful (all positive → regime=0)
        df = pd.DataFrame({
            "name": ["A"], "rs_week": [1.0], "rs_month": [1.0],
            "rs_quarter": [1.0], "rs_half": [1.0], "rs_year": [1.0],
        })
        result = cd.compute_rs_regime(df).iloc[0]
        assert not math.isnan(result)
        assert result == 0.0  # short breadth (1.0) - long breadth (1.0) = 0

    def test_missing_long_bucket_is_nan(self):
        df = pd.DataFrame({
            "name": ["A", "B"], "rs_week": [1.0, 2.0], "rs_month": [1.0, 2.0],
        })
        assert cd.compute_rs_regime(df).isna().all()


class TestComputeForGroupRSColumns:
    """End-to-end: RS columns populate correctly when SPY data is present."""

    def _make_snapshot_csv(self, path, dates_perf):
        cols = cd.SNAPSHOT_COLS
        rows = []
        for d, groups in dates_perf.items():
            for name, p in groups.items():
                row = {c: "" for c in cols}
                row.update({"date": d, "name": name, "group_type": "sector"})
                for k in ["perf_day", "perf_week", "perf_month", "perf_quarter",
                          "perf_half", "perf_year", "perf_ytd"]:
                    row[k] = p
                rows.append(row)
        import csv as _csv
        with open(path, "w", newline="") as f:
            w = _csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            w.writerows(rows)

    def _make_bench_df(self, date_str, spy_perf=1.0):
        return pd.DataFrame([{
            "date": date(int(date_str[:4]), int(date_str[5:7]), int(date_str[8:])),
            "perf_day": spy_perf, "perf_week": spy_perf, "perf_month": spy_perf,
            "perf_quarter": spy_perf, "perf_half": spy_perf, "perf_year": spy_perf,
            "perf_ytd": spy_perf,
        }])

    def test_rs_columns_present_when_spy_available(self, tmp_path):
        snap = tmp_path / "snapshots.csv"
        self._make_snapshot_csv(snap, {
            "2026-06-09": {"Alpha": 3.0, "Beta": 1.0, "Gamma": -1.0}
        })
        bench_df = self._make_bench_df("2026-06-09", spy_perf=0.5)
        delta = tmp_path / "deltas.csv"
        cd.compute_for_group("sector", snap_path=snap, delta_path=delta, bench_df=bench_df)
        with open(delta, newline="") as f:
            rows = {r["name"]: r for r in __import__("csv").DictReader(f)}
        # Alpha: perf_month = 3.0, SPY = 0.5 → rs_month = 2.5 (positive)
        assert float(rows["Alpha"]["rs_month"]) == pytest.approx(2.5)
        # Gamma: perf_month = -1.0, SPY = 0.5 → rs_month = -1.5 (negative)
        assert float(rows["Gamma"]["rs_month"]) == pytest.approx(-1.5)

    def test_rs_columns_blank_when_no_spy(self, tmp_path):
        snap = tmp_path / "snapshots.csv"
        self._make_snapshot_csv(snap, {
            "2026-06-09": {"Alpha": 3.0, "Beta": 1.0}
        })
        delta = tmp_path / "deltas.csv"
        cd.compute_for_group("sector", snap_path=snap, delta_path=delta, bench_df=None)
        with open(delta, newline="") as f:
            rows = {r["name"]: r for r in __import__("csv").DictReader(f)}
        # No SPY → all RS columns empty
        from scripts.delta_config import RS_COLS
        assert all(rows["Alpha"][c] == "" for c in RS_COLS)

    def test_rs_score_and_confirmed_in_0_1(self, tmp_path):
        snap = tmp_path / "snapshots.csv"
        self._make_snapshot_csv(snap, {
            "2026-06-09": {"Alpha": 5.0, "Beta": 2.0, "Gamma": -1.0}
        })
        bench_df = self._make_bench_df("2026-06-09", spy_perf=1.0)
        delta = tmp_path / "deltas.csv"
        cd.compute_for_group("sector", snap_path=snap, delta_path=delta, bench_df=bench_df)
        with open(delta, newline="") as f:
            rows = {r["name"]: r for r in __import__("csv").DictReader(f)}
        for name in ("Alpha", "Beta", "Gamma"):
            assert 0.0 <= float(rows[name]["rs_score"]) <= 1.0
            assert 0.0 <= float(rows[name]["rs_confirmed"]) <= 1.0


# ---------------------------------------------------------------------------
# Tier 5: compute_beats_benchmark
# ---------------------------------------------------------------------------

class TestComputeBeatsBenchmark:
    def _df(self):
        return pd.DataFrame({
            "name": ["Alpha", "Beta", "Gamma"],
            "rs_day":     [1.5, -0.5, float("nan")],
            "rs_week":    [2.0, -1.0, 0.5],
            "rs_month":   [3.0, -2.0, 0.0],
            "rs_quarter": [1.0, -1.0, 0.0],
            "rs_half":    [0.5, -0.5, 0.0],
            "rs_year":    [4.0, -4.0, 0.1],
            "rs_ytd":     [3.5, -3.5, 0.0],
        })

    def test_positive_rs_gives_1(self):
        bb = cd.compute_beats_benchmark(self._df())
        assert bb["beats_benchmark_day"].iloc[0] == 1

    def test_negative_rs_gives_0(self):
        bb = cd.compute_beats_benchmark(self._df())
        assert bb["beats_benchmark_day"].iloc[1] == 0

    def test_nan_rs_gives_nan(self):
        bb = cd.compute_beats_benchmark(self._df())
        assert math.isnan(bb["beats_benchmark_day"].iloc[2])

    def test_zero_rs_gives_0(self):
        bb = cd.compute_beats_benchmark(self._df())
        # rs_month for Gamma = 0.0 → beats_benchmark_month = 0
        assert bb["beats_benchmark_month"].iloc[2] == 0

    def test_all_7_columns_present(self):
        bb = cd.compute_beats_benchmark(self._df())
        from scripts.delta_config import RS_BEAT_TIMEFRAMES
        for tf in RS_BEAT_TIMEFRAMES:
            assert "beats_benchmark_" + tf in bb.columns

    def test_missing_rs_column_produces_nan(self):
        df = pd.DataFrame({"name": ["A", "B"], "rs_week": [1.0, -1.0]})
        bb = cd.compute_beats_benchmark(df)
        assert bb["beats_benchmark_day"].isna().all()


# ---------------------------------------------------------------------------
# Tier 5: compute_rs_new_high and compute_rs_cross
# ---------------------------------------------------------------------------

@pytest.fixture
def rs_history_4sessions():
    """4 sessions of group + SPY data for rs_new_high / rs_cross tests."""
    dates = [date(2026, 6, 9), date(2026, 6, 10), date(2026, 6, 11), date(2026, 6, 12)]
    bench = pd.DataFrame({
        "date": dates,
        "perf_month": [1.0, 1.0, 1.0, 1.0],
    })
    # Tech rs_month: [0.5, 0.8, 1.0, 1.2] — building to new high
    # Energy rs_month: [0.5, -0.5, -0.2, 0.2] — crossed from neg to pos
    # Finance rs_month: [3.0, 2.5, 2.0, 1.5] — declining, past high at start
    hist = pd.DataFrame({
        "date": dates * 3,
        "name": ["Tech"] * 4 + ["Energy"] * 4 + ["Finance"] * 4,
        "perf_month": [
            1.5, 1.8, 2.0, 2.2,   # Tech:    +0.5, +0.8, +1.0, +1.2 vs SPY
            1.5, 0.5, 0.8, 1.2,   # Energy:  +0.5, -0.5, -0.2, +0.2 vs SPY
            4.0, 3.5, 3.0, 2.5,   # Finance: +3.0, +2.5, +2.0, +1.5 vs SPY
        ],
    })
    return dates, bench, hist


class TestComputeRsNewHigh:
    def test_at_window_high_returns_1(self, rs_history_4sessions):
        dates, bench, hist = rs_history_4sessions
        s = cd.compute_rs_new_high(hist, bench, dates, date(2026, 6, 12), window=4, min_sessions=4)
        assert s["Tech"] == 1

    def test_not_at_window_high_returns_0(self, rs_history_4sessions):
        dates, bench, hist = rs_history_4sessions
        s = cd.compute_rs_new_high(hist, bench, dates, date(2026, 6, 12), window=4, min_sessions=4)
        # Energy's max rs_month was +0.5 early; today is +0.2 → not a new high
        assert s["Energy"] == 0

    def test_declining_returns_0(self, rs_history_4sessions):
        dates, bench, hist = rs_history_4sessions
        s = cd.compute_rs_new_high(hist, bench, dates, date(2026, 6, 12), window=4, min_sessions=4)
        # Finance's highest was session 0 (+3.0); today is +1.5 → not a new high
        assert s["Finance"] == 0

    def test_insufficient_history_returns_nan(self, rs_history_4sessions):
        # Only 4 sessions exist but the gate demands more → every group is NaN,
        # not a spurious 1. This is the fix for the "NH on 100% of cards" bug.
        dates, bench, hist = rs_history_4sessions
        s = cd.compute_rs_new_high(hist, bench, dates, date(2026, 6, 12), window=4, min_sessions=20)
        assert s.isna().all()

    def test_single_session_returns_empty(self, rs_history_4sessions):
        dates, bench, hist = rs_history_4sessions
        s = cd.compute_rs_new_high(hist, bench, dates, date(2026, 6, 12), window=1)
        assert len(s) == 0

    def test_no_spy_data_returns_empty(self, rs_history_4sessions):
        dates, _, hist = rs_history_4sessions
        s = cd.compute_rs_new_high(hist, pd.DataFrame(), dates, date(2026, 6, 12))
        assert len(s) == 0

    def test_date_not_in_available_returns_empty(self, rs_history_4sessions):
        dates, bench, hist = rs_history_4sessions
        s = cd.compute_rs_new_high(hist, bench, dates, date(2026, 6, 13))
        assert len(s) == 0


class TestComputeRsCross:
    def test_crossed_from_negative_returns_1(self, rs_history_4sessions):
        dates, bench, hist = rs_history_4sessions
        s = cd.compute_rs_cross(hist, bench, dates, date(2026, 6, 12), window=4)
        # Energy was negative, now positive → rs_cross = 1
        assert s["Energy"] == 1

    def test_consistently_positive_returns_0(self, rs_history_4sessions):
        dates, bench, hist = rs_history_4sessions
        s = cd.compute_rs_cross(hist, bench, dates, date(2026, 6, 12), window=4)
        # Tech was always positive → rs_cross = 0
        assert s["Tech"] == 0

    def test_currently_negative_returns_0(self):
        dates = [date(2026, 6, 9), date(2026, 6, 10)]
        bench = pd.DataFrame({"date": dates, "perf_month": [1.0, 1.0]})
        hist = pd.DataFrame({
            "date": dates * 2,
            "name": ["A", "A", "B", "B"],
            "perf_month": [2.0, 0.5, 1.5, 0.8],  # A: rs_month +1, -0.5; B: +0.5, -0.2
        })
        s = cd.compute_rs_cross(hist, bench, dates, date(2026, 6, 10), window=2)
        # Both end negative → rs_cross = 0
        assert s["A"] == 0
        assert s["B"] == 0

    def test_single_session_returns_empty(self, rs_history_4sessions):
        dates, bench, hist = rs_history_4sessions
        s = cd.compute_rs_cross(hist, bench, dates, date(2026, 6, 12), window=1)
        assert len(s) == 0

    def test_no_spy_data_returns_empty(self, rs_history_4sessions):
        dates, _, hist = rs_history_4sessions
        s = cd.compute_rs_cross(hist, pd.DataFrame(), dates, date(2026, 6, 12))
        assert len(s) == 0


class TestBeatsAndDiscreteInComputeForGroup:
    """beats_benchmark_X, rs_new_high, rs_cross appear in end-to-end output."""

    def _make_snapshot(self, path, dates_groups):
        import csv as _csv
        cols = cd.SNAPSHOT_COLS
        rows = []
        for d, groups in dates_groups.items():
            for name, p in groups.items():
                row = {c: "" for c in cols}
                row.update({"date": d, "name": name, "group_type": "sector"})
                for k in ["perf_day", "perf_week", "perf_month", "perf_quarter",
                          "perf_half", "perf_year", "perf_ytd"]:
                    row[k] = p
                rows.append(row)
        with open(path, "w", newline="") as f:
            w = _csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            w.writerows(rows)

    def _make_bench_df(self, dates_perf: dict):
        rows = []
        for d_str, p in dates_perf.items():
            rows.append({
                "date": date(int(d_str[:4]), int(d_str[5:7]), int(d_str[8:])),
                "perf_day": p, "perf_week": p, "perf_month": p,
                "perf_quarter": p, "perf_half": p, "perf_year": p, "perf_ytd": p,
            })
        return pd.DataFrame(rows)

    def test_beats_benchmark_month_correct(self, tmp_path):
        snap = tmp_path / "snapshots.csv"
        self._make_snapshot(snap, {"2026-06-09": {"Alpha": 3.0, "Beta": 0.5}})
        bench_df = self._make_bench_df({"2026-06-09": 1.0})
        delta = tmp_path / "deltas.csv"
        cd.compute_for_group("sector", snap_path=snap, delta_path=delta, bench_df=bench_df)
        import csv as _csv
        with open(delta, newline="") as f:
            rows = {r["name"]: r for r in _csv.DictReader(f)}
        # Alpha: perf_month 3.0, SPY 1.0 → rs_month +2.0 → beats = 1
        assert rows["Alpha"]["beats_benchmark_month"] == "1"
        # Beta: perf_month 0.5, SPY 1.0 → rs_month -0.5 → beats = 0
        assert rows["Beta"]["beats_benchmark_month"] == "0"

    def test_discrete_columns_blank_when_no_spy(self, tmp_path):
        snap = tmp_path / "snapshots.csv"
        self._make_snapshot(snap, {"2026-06-09": {"Alpha": 3.0}})
        delta = tmp_path / "deltas.csv"
        cd.compute_for_group("sector", snap_path=snap, delta_path=delta, bench_df=None)
        import csv as _csv
        with open(delta, newline="") as f:
            rows = {r["name"]: r for r in _csv.DictReader(f)}
        assert rows["Alpha"]["beats_benchmark_month"] == ""
        assert rows["Alpha"]["rs_new_high"] == ""
        assert rows["Alpha"]["rs_cross"] == ""
