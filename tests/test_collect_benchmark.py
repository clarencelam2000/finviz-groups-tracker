"""
Tests for the SPY benchmark scraping additions in scripts/collect.py.
All tests use fixture HTML or tmp_path — no network access.
"""

import csv
from pathlib import Path

import pytest

import scripts.collect as collect_module
from scripts.collect import (
    BENCH_CSV_COLUMNS,
    _evict_bench_row,
    parse_spy_quote,
)


# ---------------------------------------------------------------------------
# Fixture HTML: minimal Finviz-like SPY quote page with all 7 perf metrics.
# Labels are in one <td>, values in the next sibling <td>.
# ---------------------------------------------------------------------------

FIXTURE_HTML_FULL = """
<html><body>
<table class="snapshot-table2">
  <tr>
    <td>Change</td><td>0.54%</td>
    <td>Perf Week</td><td>1.23%</td>
    <td>Perf Month</td><td>2.34%</td>
    <td>Perf Quart</td><td>5.67%</td>
  </tr>
  <tr>
    <td>Perf Half Y</td><td>8.90%</td>
    <td>Perf Year</td><td>15.23%</td>
    <td>Perf YTD</td><td>12.34%</td>
  </tr>
</table>
</body></html>
"""

FIXTURE_HTML_MISSING_SOME = """
<html><body>
<table class="snapshot-table2">
  <tr>
    <td>Perf Week</td><td>1.23%</td>
    <td>Perf Month</td><td>2.34%</td>
  </tr>
</table>
</body></html>
"""

FIXTURE_HTML_DASH_VALUES = """
<html><body>
<table class="snapshot-table2">
  <tr>
    <td>Change</td><td>-</td>
    <td>Perf Week</td><td>N/A</td>
    <td>Perf Month</td><td>2.34%</td>
    <td>Perf Quart</td><td></td>
    <td>Perf Half Y</td><td>-1.50%</td>
    <td>Perf Year</td><td>-</td>
    <td>Perf YTD</td><td>0.00%</td>
  </tr>
</table>
</body></html>
"""

FIXTURE_HTML_ALT_LABELS = """
<html><body>
<table>
  <tr>
    <td>Perf Day</td><td>0.54%</td>
    <td>Perf Quarter</td><td>5.67%</td>
    <td>Perf Half</td><td>8.90%</td>
  </tr>
</table>
</body></html>
"""

FIXTURE_HTML_EMPTY = "<html><body></body></html>"


# ---------------------------------------------------------------------------
# parse_spy_quote
# ---------------------------------------------------------------------------

class TestParseSpyQuote:
    def _parse(self, html, date_str="2026-06-20"):
        return parse_spy_quote(html, date_str, "2026-06-20T19:48:00Z")

    def test_all_7_metrics_populated(self):
        rec = self._parse(FIXTURE_HTML_FULL)
        assert rec["ticker"] == "SPY"
        assert rec["date"] == "2026-06-20"
        assert rec["perf_day"] == pytest.approx(0.54)
        assert rec["perf_week"] == pytest.approx(1.23)
        assert rec["perf_month"] == pytest.approx(2.34)
        assert rec["perf_quarter"] == pytest.approx(5.67)
        assert rec["perf_half"] == pytest.approx(8.90)
        assert rec["perf_year"] == pytest.approx(15.23)
        assert rec["perf_ytd"] == pytest.approx(12.34)

    def test_dash_value_returns_none(self):
        rec = self._parse(FIXTURE_HTML_DASH_VALUES)
        assert rec["perf_day"] is None
        assert rec["perf_week"] is None
        assert rec["perf_year"] is None

    def test_na_value_returns_none(self):
        rec = self._parse(FIXTURE_HTML_DASH_VALUES)
        assert rec["perf_week"] is None

    def test_empty_cell_returns_none(self):
        rec = self._parse(FIXTURE_HTML_DASH_VALUES)
        assert rec["perf_quarter"] is None

    def test_negative_value_parsed_correctly(self):
        rec = self._parse(FIXTURE_HTML_DASH_VALUES)
        assert rec["perf_half"] == pytest.approx(-1.50)

    def test_zero_value_parsed_correctly(self):
        rec = self._parse(FIXTURE_HTML_DASH_VALUES)
        assert rec["perf_ytd"] == pytest.approx(0.0)

    def test_positive_value_with_pct_sign(self):
        rec = self._parse(FIXTURE_HTML_DASH_VALUES)
        assert rec["perf_month"] == pytest.approx(2.34)

    def test_missing_labels_leave_none(self):
        rec = self._parse(FIXTURE_HTML_MISSING_SOME)
        assert rec["perf_week"] == pytest.approx(1.23)
        assert rec["perf_month"] == pytest.approx(2.34)
        # Not present in fixture → None
        assert rec["perf_day"] is None
        assert rec["perf_quarter"] is None
        assert rec["perf_year"] is None

    def test_alternate_label_forms_accepted(self):
        # "Perf Day", "Perf Quarter", "Perf Half" (without Y)
        rec = self._parse(FIXTURE_HTML_ALT_LABELS)
        assert rec["perf_day"] == pytest.approx(0.54)
        assert rec["perf_quarter"] == pytest.approx(5.67)
        assert rec["perf_half"] == pytest.approx(8.90)

    def test_empty_page_returns_all_none(self):
        rec = self._parse(FIXTURE_HTML_EMPTY)
        assert rec["ticker"] == "SPY"
        assert all(rec[col] is None for col in
                   ["perf_day", "perf_week", "perf_month", "perf_quarter",
                    "perf_half", "perf_year", "perf_ytd"])

    def test_metadata_fields_set(self):
        rec = self._parse(FIXTURE_HTML_FULL, date_str="2026-01-15")
        assert rec["date"] == "2026-01-15"
        assert rec["collected_at"] == "2026-06-20T19:48:00Z"
        assert rec["ticker"] == "SPY"


# ---------------------------------------------------------------------------
# _evict_bench_row
# ---------------------------------------------------------------------------

class TestEvictBenchRow:
    def _write_bench(self, path: Path, rows: list):
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=BENCH_CSV_COLUMNS)
            writer.writeheader()
            for row in rows:
                writer.writerow({col: row.get(col, "") for col in BENCH_CSV_COLUMNS})

    def test_returns_zero_when_file_missing(self, tmp_path):
        result = _evict_bench_row(tmp_path / "missing.csv", "2026-06-20")
        assert result == 0

    def test_returns_zero_when_date_not_present(self, tmp_path):
        path = tmp_path / "bench.csv"
        self._write_bench(path, [{"date": "2026-06-19", "ticker": "SPY"}])
        result = _evict_bench_row(path, "2026-06-20")
        assert result == 0

    def test_removes_matching_date_row(self, tmp_path):
        path = tmp_path / "bench.csv"
        self._write_bench(path, [
            {"date": "2026-06-19", "ticker": "SPY", "perf_week": "1.0"},
            {"date": "2026-06-20", "ticker": "SPY", "perf_week": "2.0"},
        ])
        result = _evict_bench_row(path, "2026-06-20")
        assert result == 1
        with open(path, newline="") as f:
            rows = list(csv.DictReader(f))
        assert len(rows) == 1
        assert rows[0]["date"] == "2026-06-19"

    def test_preserves_other_dates(self, tmp_path):
        path = tmp_path / "bench.csv"
        self._write_bench(path, [
            {"date": "2026-06-18", "ticker": "SPY", "perf_week": "0.5"},
            {"date": "2026-06-19", "ticker": "SPY", "perf_week": "1.0"},
            {"date": "2026-06-20", "ticker": "SPY", "perf_week": "2.0"},
        ])
        _evict_bench_row(path, "2026-06-20")
        with open(path, newline="") as f:
            rows = list(csv.DictReader(f))
        assert len(rows) == 2
        assert {r["date"] for r in rows} == {"2026-06-18", "2026-06-19"}

    def test_no_tmp_file_left_behind(self, tmp_path):
        path = tmp_path / "bench.csv"
        self._write_bench(path, [{"date": "2026-06-20", "ticker": "SPY"}])
        _evict_bench_row(path, "2026-06-20")
        assert not path.with_suffix(".tmp").exists()


# ---------------------------------------------------------------------------
# collect_spy — integration (mocked fetch, real CSV I/O)
# ---------------------------------------------------------------------------

class TestCollectSpy:
    def test_writes_spy_row_to_csv(self, tmp_path, monkeypatch):
        bench_path = tmp_path / "benchmark" / "snapshots.csv"
        monkeypatch.setattr(
            "scripts.collect.fetch_html",
            lambda url, wait_selector=None: FIXTURE_HTML_FULL,
        )
        collect_module.collect_spy(bench_path=bench_path)
        with open(bench_path, newline="") as f:
            rows = list(csv.DictReader(f))
        assert len(rows) == 1
        assert rows[0]["ticker"] == "SPY"
        assert rows[0]["perf_week"] == "1.23"
        assert rows[0]["perf_month"] == "2.34"

    def test_last_write_wins_on_rerun(self, tmp_path, monkeypatch):
        bench_path = tmp_path / "benchmark" / "snapshots.csv"
        # First run
        monkeypatch.setattr(
            "scripts.collect.fetch_html",
            lambda url, wait_selector=None: FIXTURE_HTML_FULL,
        )
        collect_module.collect_spy(bench_path=bench_path)
        # Second run — same date, different data (simulate late-day update)
        html2 = FIXTURE_HTML_FULL.replace("1.23%", "1.99%")
        monkeypatch.setattr(
            "scripts.collect.fetch_html",
            lambda url, wait_selector=None: html2,
        )
        collect_module.collect_spy(bench_path=bench_path)
        with open(bench_path, newline="") as f:
            rows = list(csv.DictReader(f))
        assert len(rows) == 1
        assert rows[0]["perf_week"] == "1.99"

    def test_raises_when_partial_perf_cols_parsed(self, tmp_path, monkeypatch):
        # FIXTURE_HTML_DASH_VALUES has 7 labels but 4 are "-"/N/A/empty → only
        # 3 non-None values. collect_spy must raise rather than silently write
        # a partial row (SPY always has full perf history; fewer than 7 = parser
        # failure, e.g. Finviz label change on the quote page).
        bench_path = tmp_path / "benchmark" / "snapshots.csv"
        monkeypatch.setattr(
            "scripts.collect.fetch_html",
            lambda url, wait_selector=None: FIXTURE_HTML_DASH_VALUES,
        )
        with pytest.raises(RuntimeError, match="perf values"):
            collect_module.collect_spy(bench_path=bench_path)

    def test_raises_when_no_perf_cols_parsed(self, tmp_path, monkeypatch):
        bench_path = tmp_path / "benchmark" / "snapshots.csv"
        monkeypatch.setattr(
            "scripts.collect.fetch_html",
            lambda url, wait_selector=None: FIXTURE_HTML_EMPTY,
        )
        with pytest.raises(RuntimeError, match="perf values"):
            collect_module.collect_spy(bench_path=bench_path)

    def test_creates_benchmark_directory(self, tmp_path, monkeypatch):
        bench_path = tmp_path / "nested" / "dir" / "snapshots.csv"
        monkeypatch.setattr(
            "scripts.collect.fetch_html",
            lambda url, wait_selector=None: FIXTURE_HTML_FULL,
        )
        collect_module.collect_spy(bench_path=bench_path)
        assert bench_path.exists()

    def test_csv_has_correct_columns(self, tmp_path, monkeypatch):
        bench_path = tmp_path / "benchmark" / "snapshots.csv"
        monkeypatch.setattr(
            "scripts.collect.fetch_html",
            lambda url, wait_selector=None: FIXTURE_HTML_FULL,
        )
        collect_module.collect_spy(bench_path=bench_path)
        with open(bench_path, newline="") as f:
            reader = csv.DictReader(f)
            assert list(reader.fieldnames) == BENCH_CSV_COLUMNS
