"""Tests for scripts/delta_config.py — the single source of truth for the
deltas.csv schema."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import delta_config as dc


def test_delta_columns_starts_with_date_name_ranks():
    cols = dc.delta_columns()
    assert cols[:2] == ["date", "name"]
    # rank columns follow immediately
    assert cols[2:2 + len(dc.RANK_COLS)] == dc.RANK_COLS


def test_delta_columns_has_no_duplicates():
    cols = dc.delta_columns()
    assert len(cols) == len(set(cols))


def test_delta_columns_includes_every_window_metric_combo():
    cols = set(dc.delta_columns())
    for w in dc.LOOKBACK_WINDOWS:
        for m in dc.RANK_DELTA_METRICS:
            assert f"{m}_delta_{w}d" in cols
        for m in dc.PERF_DELTA_METRICS:
            assert f"{m}_delta_{w}d" in cols


def test_delta_columns_ends_with_momentum_cols():
    cols = dc.delta_columns()
    assert cols[-len(dc.MOMENTUM_COLS):] == dc.MOMENTUM_COLS


def test_delta_columns_count():
    n_delta = len(dc.LOOKBACK_WINDOWS) * (
        len(dc.RANK_DELTA_METRICS) + len(dc.PERF_DELTA_METRICS)
    )
    expected = 2 + len(dc.RANK_COLS) + n_delta + len(dc.MOMENTUM_COLS)
    assert len(dc.delta_columns()) == expected


def test_trading_basis_and_windows():
    assert dc.LOOKBACK_BASIS == "trading"
    assert dc.LOOKBACK_WINDOWS == [5, 10, 20, 50]
