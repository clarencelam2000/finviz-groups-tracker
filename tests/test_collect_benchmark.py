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
    SPY_FIELD_MAP,
    SPY_LABEL_MAP,
    _evict_bench_row,
    _normalize_spy_label,
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

# 2026-09-20 (issue #419): full quote-page field set fixture. Exercises the
# widened SPY_FIELD_MAP alongside the 7 perf labels.
FIXTURE_HTML_QUOTE_FULL = """
<html><body>
<table class="snapshot-table2">
  <tr>
    <td>Price</td><td>684.12</td>
    <td>Change</td><td>0.54%</td>
    <td>Perf Week</td><td>1.23%</td>
    <td>Perf Month</td><td>2.34%</td>
    <td>Perf Quart</td><td>5.67%</td>
    <td>Perf Half Y</td><td>8.90%</td>
  </tr>
  <tr>
    <td>Perf Year</td><td>15.23%</td>
    <td>Perf YTD</td><td>12.34%</td>
    <td>Prev Close</td><td>683.45</td>
    <td>High</td><td>685.30</td>
    <td>Low</td><td>681.10</td>
    <td>SMA20</td><td>0.85%</td>
  </tr>
  <tr>
    <td>SMA50</td><td>2.14%</td>
    <td>SMA200</td><td>5.32%</td>
    <td>52W High</td><td>-4.12%</td>
    <td>52W Low</td><td>15.25%</td>
    <td>52W Range</td><td>593.21 - 712.80</td>
    <td>RSI (14)</td><td>58.24</td>
  </tr>
  <tr>
    <td>Beta</td><td>1.00</td>
    <td>ATR</td><td>8.42</td>
    <td>Volatility</td><td>1.24% 1.87%</td>
    <td>Volume</td><td>45,231,098</td>
    <td>Avg Volume</td><td>58,234,112</td>
    <td>Rel Volume</td><td>0.89</td>
  </tr>
  <tr>
    <td>Market Cap</td><td>649.77B</td>
    <td>P/E</td><td>27.35</td>
    <td>Forward P/E</td><td>24.89</td>
    <td>Target Price</td><td>-</td>
    <td>Recom</td><td>-</td>
    <td>Short Ratio</td><td>1.02</td>
  </tr>
  <tr>
    <td>Short Float</td><td>1.12%</td>
    <td>Inst Own</td><td>95.20%</td>
    <td>Inst Trans</td><td>-0.21%</td>
    <td>Shs Outstand</td><td>948.52M</td>
    <td>Shs Float</td><td>948.51M</td>
    <td>Dividend</td><td>-</td>
  </tr>
  <tr>
    <td>Dividend TTM</td><td>-</td>
    <td>Dividend Est.</td><td>-</td>
    <td>Payout</td><td>-</td>
    <td>Income</td><td>23.77B</td>
    <td>Sales</td><td>0.00</td>
    <td>Optionable</td><td>Yes</td>
  </tr>
  <tr>
    <td>Shortable</td><td>Yes</td>
    <td>Index</td><td>DJI S&amp;P500</td>
    <td>Employees</td><td>-</td>
  </tr>
</table>
</body></html>
"""

# A label Finviz could add tomorrow — must be captured under a normalized name
# and warned about, never silently dropped.
FIXTURE_HTML_UNKNOWN_LABEL = """
<html><body>
<table class="snapshot-table2">
  <tr>
    <td>Change</td><td>0.54%</td>
    <td>Quantum Flux</td><td>42</td>
  </tr>
</table>
</body></html>
"""

# 2026-08-07: Finviz renamed the quote-page daily-change label from "Change"
# to "Change %". Both forms must resolve to perf_day (SPY_LABEL_MAP).
FIXTURE_HTML_CHANGE_PCT_LABEL = """
<html><body>
<table class="snapshot-table2">
  <tr>
    <td>Change %</td><td>0.61%</td>
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

    def test_change_pct_label_accepted(self):
        # 2026-08-07 Finviz rename: "Change" -> "Change %" on the quote page.
        rec = self._parse(FIXTURE_HTML_CHANGE_PCT_LABEL)
        assert rec["perf_day"] == pytest.approx(0.61)

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


# ---------------------------------------------------------------------------
# Issue #419 — full quote-page field set
# ---------------------------------------------------------------------------

class TestQuoteFieldSet:
    def _parse(self, html, date_str="2026-09-18"):
        return parse_spy_quote(html, date_str, "2026-09-18T19:48:00Z")

    def test_perf_cols_unchanged_in_name_order_and_value(self):
        # The original 7 perf_* columns must be untouched by the widening.
        rec = self._parse(FIXTURE_HTML_QUOTE_FULL)
        assert rec["perf_day"] == pytest.approx(0.54)
        assert rec["perf_week"] == pytest.approx(1.23)
        assert rec["perf_month"] == pytest.approx(2.34)
        assert rec["perf_quarter"] == pytest.approx(5.67)
        assert rec["perf_half"] == pytest.approx(8.90)
        assert rec["perf_year"] == pytest.approx(15.23)
        assert rec["perf_ytd"] == pytest.approx(12.34)

    def test_price_and_ma_captured(self):
        rec = self._parse(FIXTURE_HTML_QUOTE_FULL)
        assert rec["price"] == "684.12"
        assert rec["prev_close"] == "683.45"
        assert rec["high"] == "685.30"
        assert rec["low"] == "681.10"
        assert rec["sma20"] == "0.85%"
        assert rec["sma50"] == "2.14%"
        assert rec["sma200"] == "5.32%"

    def test_range_volatility_momentum_captured(self):
        rec = self._parse(FIXTURE_HTML_QUOTE_FULL)
        assert rec["dist_52w_high"] == "-4.12%"
        assert rec["dist_52w_low"] == "15.25%"
        assert rec["range_52w"] == "593.21 - 712.80"
        assert rec["rsi_14"] == "58.24"
        assert rec["beta"] == "1.00"
        assert rec["atr"] == "8.42"
        assert rec["volatility"] == "1.24% 1.87%"

    def test_volume_fields_captured(self):
        rec = self._parse(FIXTURE_HTML_QUOTE_FULL)
        assert rec["volume"] == "45,231,098"
        assert rec["avg_volume"] == "58,234,112"
        assert rec["rel_volume"] == "0.89"

    def test_fundamental_fields_captured(self):
        rec = self._parse(FIXTURE_HTML_QUOTE_FULL)
        assert rec["market_cap"] == "649.77B"
        assert rec["pe"] == "27.35"
        assert rec["fwd_pe"] == "24.89"
        assert rec["short_ratio"] == "1.02"
        assert rec["short_float"] == "1.12%"
        assert rec["inst_own"] == "95.20%"
        assert rec["inst_trans"] == "-0.21%"
        assert rec["shs_outstand"] == "948.52M"
        assert rec["shs_float"] == "948.51M"
        assert rec["income"] == "23.77B"
        assert rec["sales"] == "0.00"
        assert rec["optionable"] == "Yes"
        assert rec["shortable"] == "Yes"
        assert rec["spy_index"] == "DJI S&P500"

    def test_dash_values_become_none(self):
        rec = self._parse(FIXTURE_HTML_QUOTE_FULL)
        assert rec["target_price"] is None
        assert rec["recom"] is None
        assert rec["dividend"] is None
        assert rec["employees"] is None

    def test_bench_csv_columns_first_ten_unchanged(self):
        # Schema is append-only: the original 10 columns keep name and order.
        assert BENCH_CSV_COLUMNS[:10] == [
            "date", "collected_at", "ticker",
            "perf_day", "perf_week", "perf_month", "perf_quarter",
            "perf_half", "perf_year", "perf_ytd",
        ]

    def test_field_map_covers_new_columns(self):
        # Every appended CSV column is reachable from a Finviz label, and
        # every mapped field has a CSV column — the two stay in sync.
        new_cols = set(BENCH_CSV_COLUMNS[10:])
        assert set(SPY_FIELD_MAP.values()) == new_cols

    def test_unknown_label_captured_and_warned(self, capsys):
        rec = self._parse(FIXTURE_HTML_UNKNOWN_LABEL)
        assert rec["quantum_flux"] == "42"
        assert rec["perf_day"] == pytest.approx(0.54)
        assert "Unknown SPY quote labels" in capsys.readouterr().err

    def test_normalize_spy_label(self):
        assert _normalize_spy_label("RSI (14)") == "rsi_14"
        assert _normalize_spy_label("52W Range") == "52w_range"
        assert _normalize_spy_label("Dividend Est.") == "dividend_est"

    def test_collect_spy_writes_new_columns(self, tmp_path, monkeypatch):
        bench_path = tmp_path / "benchmark" / "snapshots.csv"
        monkeypatch.setattr(
            "scripts.collect.fetch_html",
            lambda url, wait_selector=None: FIXTURE_HTML_QUOTE_FULL,
        )
        collect_module.collect_spy(bench_path=bench_path)
        with open(bench_path, newline="") as f:
            reader = csv.DictReader(f)
            assert list(reader.fieldnames) == BENCH_CSV_COLUMNS
            rows = list(reader)
        assert len(rows) == 1
        assert rows[0]["price"] == "684.12"
        assert rows[0]["sma20"] == "0.85%"
        assert rows[0]["rsi_14"] == "58.24"
        assert rows[0]["range_52w"] == "593.21 - 712.80"
        assert rows[0]["perf_week"] == "1.23"

    def test_backfill_safe_evict_of_old_schema_rows(self, tmp_path):
        # Old rows (10-column schema) rewritten by _evict_bench_row must keep
        # their data and get blanks for the new columns.
        path = tmp_path / "bench.csv"
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=BENCH_CSV_COLUMNS[:10])
            writer.writeheader()
            writer.writerow({"date": "2026-06-18", "ticker": "SPY", "perf_week": "0.5"})
            writer.writerow({"date": "2026-06-19", "ticker": "SPY", "perf_week": "1.0"})
        _evict_bench_row(path, "2026-06-19")
        with open(path, newline="") as f:
            reader = csv.DictReader(f)
            assert list(reader.fieldnames) == BENCH_CSV_COLUMNS
            rows = list(reader)
        assert len(rows) == 1
        assert rows[0]["date"] == "2026-06-18"
        assert rows[0]["perf_week"] == "0.5"
        assert rows[0]["price"] == ""
        assert rows[0]["sma20"] == ""
