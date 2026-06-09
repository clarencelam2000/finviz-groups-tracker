import csv
import textwrap

import pytest

from scripts.collect import (
    CSV_COLUMNS,
    append_records,
    ensure_csv,
    parse_avg_volume,
    parse_market_cap,
    parse_perf,
    parse_table,
)

# ---------------------------------------------------------------------------
# parse_perf
# ---------------------------------------------------------------------------

class TestParsePerf:
    def test_valid_positive(self):
        assert parse_perf("+2.34%") == pytest.approx(2.34)

    def test_valid_negative(self):
        assert parse_perf("-1.23%") == pytest.approx(-1.23)

    def test_zero(self):
        assert parse_perf("0.00%") == pytest.approx(0.0)

    def test_empty_string(self):
        assert parse_perf("") is None

    def test_dash(self):
        assert parse_perf("-") is None

    def test_na(self):
        assert parse_perf("N/A") is None

    def test_no_percent_sign(self):
        assert parse_perf("5.67") == pytest.approx(5.67)


# ---------------------------------------------------------------------------
# parse_market_cap
# ---------------------------------------------------------------------------

class TestParseMarketCap:
    def test_trillions(self):
        assert parse_market_cap("1.5T") == pytest.approx(1500.0)

    def test_billions(self):
        assert parse_market_cap("23.4B") == pytest.approx(23.4)

    def test_millions(self):
        assert parse_market_cap("500M") == pytest.approx(0.5)

    def test_thousands(self):
        assert parse_market_cap("100K") == pytest.approx(0.0001)

    def test_empty(self):
        assert parse_market_cap("") is None

    def test_dash(self):
        assert parse_market_cap("-") is None

    def test_na(self):
        assert parse_market_cap("N/A") is None


# ---------------------------------------------------------------------------
# parse_avg_volume
# ---------------------------------------------------------------------------

class TestParseAvgVolume:
    def test_billions(self):
        assert parse_avg_volume("1.23B") == 1_230_000_000

    def test_millions(self):
        assert parse_avg_volume("456.7M") == 456_700_000

    def test_thousands(self):
        assert parse_avg_volume("89K") == 89_000

    def test_raw_integer(self):
        assert parse_avg_volume("1230000") == 1_230_000

    def test_empty(self):
        assert parse_avg_volume("") is None

    def test_dash(self):
        assert parse_avg_volume("-") is None


# ---------------------------------------------------------------------------
# parse_table
# ---------------------------------------------------------------------------

MINIMAL_HTML = textwrap.dedent("""\
    <html><body>
    <table class="groups_table">
      <tr>
        <th>No.</th><th>Name</th><th>Perf YTD</th><th>Change</th>
      </tr>
      <tr>
        <td>1</td><td>Technology</td><td>12.34%</td><td>1.23%</td>
      </tr>
      <tr>
        <td>2</td><td>Energy</td><td>-5.67%</td><td>-0.45%</td>
      </tr>
    </table>
    </body></html>
""")


class TestParseTable:
    def test_valid_rows_count(self):
        records = parse_table(MINIMAL_HTML, "sector", "2026-06-09", "2026-06-09T22:00:00Z")
        assert len(records) == 2

    def test_valid_row_values(self):
        records = parse_table(MINIMAL_HTML, "sector", "2026-06-09", "2026-06-09T22:00:00Z")
        assert records[0]["name"] == "Technology"
        assert records[0]["perf_ytd"] == pytest.approx(12.34)
        assert records[0]["change"] == pytest.approx(1.23)

    def test_perf_day_fallback_from_change(self):
        # No "Perf Day" column present; perf_day should be filled from change
        records = parse_table(MINIMAL_HTML, "sector", "2026-06-09", "2026-06-09T22:00:00Z")
        assert records[0]["perf_day"] == records[0]["change"]

    def test_empty_table(self):
        html = (
            '<html><body><table class="groups_table">'
            '<tr><th>No.</th><th>Name</th></tr>'
            '</table></body></html>'
        )
        records = parse_table(html, "sector", "2026-06-09", "2026-06-09T22:00:00Z")
        assert records == []

    def test_unknown_header_logged_to_stderr(self, capsys):
        html = textwrap.dedent("""\
            <html><body>
            <table class="groups_table">
              <tr><th>No.</th><th>Name</th><th>UnknownCol</th><th>Change</th></tr>
              <tr><td>1</td><td>Tech</td><td>ignored</td><td>1.0%</td></tr>
            </table>
            </body></html>
        """)
        records = parse_table(html, "sector", "2026-06-09", "2026-06-09T22:00:00Z")
        assert len(records) == 1
        assert records[0]["name"] == "Tech"
        captured = capsys.readouterr()
        assert "UnknownCol" in captured.err

    def test_missing_name_row_skipped(self):
        html = textwrap.dedent("""\
            <html><body>
            <table class="groups_table">
              <tr><th>No.</th><th>Name</th><th>Change</th></tr>
              <tr><td>1</td><td></td><td>1.0%</td></tr>
              <tr><td>2</td><td>Energy</td><td>0.5%</td></tr>
            </table>
            </body></html>
        """)
        records = parse_table(html, "sector", "2026-06-09", "2026-06-09T22:00:00Z")
        assert len(records) == 1
        assert records[0]["name"] == "Energy"

    def test_metadata_fields(self):
        records = parse_table(MINIMAL_HTML, "sector", "2026-06-09", "2026-06-09T22:00:00Z")
        assert records[0]["date"] == "2026-06-09"
        assert records[0]["group_type"] == "sector"
        assert records[0]["collected_at"] == "2026-06-09T22:00:00Z"


# ---------------------------------------------------------------------------
# append_records
# ---------------------------------------------------------------------------

class TestAppendRecords:
    def _base_record(self, name="Technology"):
        return {
            "date": "2026-06-09", "collected_at": "2026-06-09T22:00:00Z",
            "group_type": "sector", "name": name,
            "stocks": 100, "market_cap": 10000.0, "pe": 25.0, "fwd_pe": 22.0,
            "perf_day": 1.5, "perf_week": 3.2, "perf_month": 5.1,
            "perf_quarter": 8.0, "perf_half": 12.0, "perf_year": 20.0, "perf_ytd": 15.0,
            "avg_volume": 5000000, "rel_volume": None, "change": 1.5,
        }

    def test_new_records_appended(self, tmp_path):
        csv_path = tmp_path / "test.csv"
        ensure_csv(csv_path)
        records = [self._base_record("Technology")]
        count = append_records(csv_path, records, set())
        assert count == 1
        with open(csv_path) as f:
            rows = list(csv.DictReader(f))
        assert len(rows) == 1
        assert rows[0]["name"] == "Technology"

    def test_dedup_skips_existing(self, tmp_path):
        csv_path = tmp_path / "test.csv"
        ensure_csv(csv_path)
        records = [self._base_record("Technology")]
        existing_keys = {("2026-06-09", "Technology")}
        count = append_records(csv_path, records, existing_keys)
        assert count == 0

    def test_multiple_records_partial_dedup(self, tmp_path):
        csv_path = tmp_path / "test.csv"
        ensure_csv(csv_path)
        records = [self._base_record("Technology"), self._base_record("Energy")]
        existing_keys = {("2026-06-09", "Technology")}
        count = append_records(csv_path, records, existing_keys)
        assert count == 1
        with open(csv_path) as f:
            rows = list(csv.DictReader(f))
        assert rows[0]["name"] == "Energy"
