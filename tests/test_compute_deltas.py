import csv
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from scripts.compute_deltas import (
    compute_for_group,
    compute_ranks,
    find_nearest_date,
)


# ---------------------------------------------------------------------------
# find_nearest_date
# ---------------------------------------------------------------------------

class TestFindNearestDate:
    def test_exact_match(self):
        dates = [date(2026, 6, 1), date(2026, 6, 5), date(2026, 6, 9)]
        assert find_nearest_date(dates, date(2026, 6, 9)) == date(2026, 6, 9)

    def test_within_tolerance(self):
        # 3 days after last available — within 5-day tolerance
        dates = [date(2026, 6, 1), date(2026, 6, 5)]
        assert find_nearest_date(dates, date(2026, 6, 8)) == date(2026, 6, 5)

    def test_outside_tolerance(self):
        # 6 days after last available — outside 5-day tolerance
        dates = [date(2026, 6, 1)]
        assert find_nearest_date(dates, date(2026, 6, 8)) is None

    def test_empty_list(self):
        assert find_nearest_date([], date(2026, 6, 9)) is None

    def test_all_after_target(self):
        dates = [date(2026, 6, 10), date(2026, 6, 11)]
        assert find_nearest_date(dates, date(2026, 6, 9)) is None


# ---------------------------------------------------------------------------
# compute_ranks
# ---------------------------------------------------------------------------

class TestComputeRanks:
    def test_basic_ytd_ranking(self):
        df = pd.DataFrame({
            "name": ["A", "B", "C"],
            "perf_ytd": [10.0, 5.0, 15.0],
        })
        result = compute_ranks(df)
        # C has highest perf_ytd → rank 1
        assert result.loc[result["name"] == "C", "rank_ytd"].values[0] == 1
        assert result.loc[result["name"] == "A", "rank_ytd"].values[0] == 2
        assert result.loc[result["name"] == "B", "rank_ytd"].values[0] == 3

    def test_rank_day_computed(self):
        df = pd.DataFrame({
            "name": ["A", "B"],
            "perf_day": [2.0, 1.0],
        })
        result = compute_ranks(df)
        assert "rank_day" in result.columns
        assert result.loc[result["name"] == "A", "rank_day"].values[0] == 1
        assert result.loc[result["name"] == "B", "rank_day"].values[0] == 2

    def test_all_nan_produces_ranks(self):
        # na_option="bottom" assigns all-NaN values to bottom ranks, not NaN
        df = pd.DataFrame({
            "name": ["A", "B"],
            "perf_ytd": [float("nan"), float("nan")],
        })
        result = compute_ranks(df)
        assert "rank_ytd" in result.columns
        assert result["rank_ytd"].notna().all()

    def test_single_row_rank_is_1(self):
        df = pd.DataFrame({
            "name": ["A"],
            "perf_ytd": [10.0],
            "perf_week": [5.0],
        })
        result = compute_ranks(df)
        assert result["rank_ytd"].values[0] == 1
        assert result["rank_week"].values[0] == 1


# ---------------------------------------------------------------------------
# compute_for_group (integration)
# ---------------------------------------------------------------------------

class TestComputeForGroup:
    SNAPSHOT_COLS = [
        "date", "collected_at", "group_type", "name", "stocks", "market_cap",
        "pe", "fwd_pe", "perf_day", "perf_week", "perf_month", "perf_quarter",
        "perf_half", "perf_year", "perf_ytd", "avg_volume", "rel_volume", "change",
    ]

    def _write_snapshots(self, path: Path, rows: list):
        with open(path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=self.SNAPSHOT_COLS)
            writer.writeheader()
            for row in rows:
                writer.writerow({c: row.get(c, "") for c in self.SNAPSHOT_COLS})

    def _row(self, date_str, name, perf_ytd=10.0, perf_week=2.0, perf_day=0.5):
        return {
            "date": date_str, "collected_at": f"{date_str}T22:00:00Z",
            "group_type": "sector", "name": name,
            "stocks": 10, "market_cap": 100.0, "pe": 20.0, "fwd_pe": 18.0,
            "perf_day": perf_day, "perf_week": perf_week, "perf_month": 1.0,
            "perf_quarter": 2.0, "perf_half": 3.0, "perf_year": 5.0, "perf_ytd": perf_ytd,
            "avg_volume": 1000000, "rel_volume": "", "change": perf_day,
        }

    def test_empty_snapshot_no_crash(self, tmp_path):
        snap_path = tmp_path / "snapshots.csv"
        delta_path = tmp_path / "deltas.csv"
        with open(snap_path, "w") as f:
            f.write(",".join(self.SNAPSHOT_COLS) + "\n")
        compute_for_group("sector", snap_path=snap_path, delta_path=delta_path)

    def test_single_day_ranks_populated_deltas_empty(self, tmp_path):
        snap_path = tmp_path / "snapshots.csv"
        delta_path = tmp_path / "deltas.csv"
        self._write_snapshots(snap_path, [
            self._row("2026-06-09", "Technology", perf_ytd=15.0),
            self._row("2026-06-09", "Energy", perf_ytd=5.0),
        ])
        compute_for_group("sector", snap_path=snap_path, delta_path=delta_path)

        df = pd.read_csv(delta_path)
        assert len(df) == 2
        # Rank columns populated
        assert df["rank_ytd"].notna().all()
        assert df["rank_day"].notna().all()
        # 7d delta columns empty (no prior data)
        assert df["rank_ytd_delta_7d"].isna().all()

    def test_idempotent(self, tmp_path):
        snap_path = tmp_path / "snapshots.csv"
        delta_path = tmp_path / "deltas.csv"
        self._write_snapshots(snap_path, [self._row("2026-06-09", "Technology")])
        compute_for_group("sector", snap_path=snap_path, delta_path=delta_path)
        compute_for_group("sector", snap_path=snap_path, delta_path=delta_path)

        df = pd.read_csv(delta_path)
        assert len(df) == 1  # no duplicate rows

    def test_delta_values_correct(self, tmp_path):
        snap_path = tmp_path / "snapshots.csv"
        delta_path = tmp_path / "deltas.csv"

        # Prior: Technology rank 2, Energy rank 1
        # Today: Technology rank 1, Energy rank 2
        self._write_snapshots(snap_path, [
            self._row("2026-06-02", "Technology", perf_ytd=10.0),
            self._row("2026-06-02", "Energy", perf_ytd=15.0),
            self._row("2026-06-09", "Technology", perf_ytd=20.0),
            self._row("2026-06-09", "Energy", perf_ytd=8.0),
        ])
        compute_for_group("sector", target_date_str="2026-06-09",
                          snap_path=snap_path, delta_path=delta_path)

        df = pd.read_csv(delta_path)
        df["rank_ytd_delta_7d"] = pd.to_numeric(df["rank_ytd_delta_7d"], errors="coerce")

        tech = df[df["name"] == "Technology"].iloc[0]
        energy = df[df["name"] == "Energy"].iloc[0]

        # Technology: was rank 2, now rank 1 → delta = prior - today = 2 - 1 = +1
        assert tech["rank_ytd_delta_7d"] == pytest.approx(1.0)
        # Energy: was rank 1, now rank 2 → delta = 1 - 2 = -1
        assert energy["rank_ytd_delta_7d"] == pytest.approx(-1.0)

    def test_schema_migration_adds_new_columns(self, tmp_path):
        snap_path = tmp_path / "snapshots.csv"
        delta_path = tmp_path / "deltas.csv"

        # Write a deltas.csv missing rank_day (old schema)
        old_cols = [c for c in __import__("scripts.compute_deltas", fromlist=["DELTA_COLUMNS"]).DELTA_COLUMNS
                    if c != "rank_day"]
        with open(delta_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=old_cols)
            writer.writeheader()
            writer.writerow({c: "1" for c in old_cols})

        self._write_snapshots(snap_path, [
            self._row("2026-06-10", "Technology"),
        ])
        compute_for_group("sector", target_date_str="2026-06-10",
                          snap_path=snap_path, delta_path=delta_path)

        df = pd.read_csv(delta_path)
        assert "rank_day" in df.columns
