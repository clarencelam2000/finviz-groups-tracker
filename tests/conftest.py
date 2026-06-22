import pandas as pd
import pytest


def pytest_addoption(parser):
    parser.addoption(
        "--update-snapshots",
        action="store_true",
        default=False,
        help="Regenerate golden prompt snapshots in tests/fixtures/ai/prompts/",
    )

SNAPSHOT_COLS = [
    "date", "collected_at", "group_type", "name", "stocks", "market_cap",
    "pe", "fwd_pe", "perf_day", "perf_week", "perf_month", "perf_quarter",
    "perf_half", "perf_year", "perf_ytd", "avg_volume", "rel_volume", "change",
]


@pytest.fixture
def minimal_snapshot_df():
    return pd.DataFrame([
        {
            "date": "2026-06-09", "collected_at": "2026-06-09T22:00:00Z",
            "group_type": "sector", "name": "Technology",
            "stocks": 100, "market_cap": 10000.0, "pe": 25.0, "fwd_pe": 22.0,
            "perf_day": 1.5, "perf_week": 3.2, "perf_month": 5.1,
            "perf_quarter": 8.0, "perf_half": 12.0, "perf_year": 20.0, "perf_ytd": 15.0,
            "avg_volume": 5000000, "rel_volume": None, "change": 1.5,
        },
        {
            "date": "2026-06-09", "collected_at": "2026-06-09T22:00:00Z",
            "group_type": "sector", "name": "Energy",
            "stocks": 50, "market_cap": 2000.0, "pe": 15.0, "fwd_pe": 14.0,
            "perf_day": -0.5, "perf_week": 1.0, "perf_month": 2.0,
            "perf_quarter": 3.0, "perf_half": 4.0, "perf_year": 5.0, "perf_ytd": None,
            "avg_volume": 2000000, "rel_volume": None, "change": -0.5,
        },
        {
            "date": "2026-06-09", "collected_at": "2026-06-09T22:00:00Z",
            "group_type": "sector", "name": "Utilities",
            "stocks": 30, "market_cap": 500.0, "pe": 20.0, "fwd_pe": 19.0,
            "perf_day": 0.2, "perf_week": None, "perf_month": 0.5,
            "perf_quarter": 1.0, "perf_half": 2.0, "perf_year": 3.0, "perf_ytd": 1.5,
            "avg_volume": 1000000, "rel_volume": None, "change": 0.2,
        },
    ])


@pytest.fixture
def empty_snapshot_df():
    return pd.DataFrame(columns=SNAPSHOT_COLS)


@pytest.fixture
def tmp_snapshot_csv(tmp_path, minimal_snapshot_df):
    path = tmp_path / "snapshots.csv"
    minimal_snapshot_df.to_csv(path, index=False)
    return path
