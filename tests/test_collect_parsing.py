import csv
import textwrap
from datetime import datetime

import pytz
import pytest

import scripts.collect as collect_module
from scripts.collect import (
    CSV_COLUMNS,
    append_records,
    ensure_csv,
    evict_today_rows,
    parse_avg_volume,
    parse_market_cap,
    parse_perf,
    parse_table,
    trading_date,
)

# ---------------------------------------------------------------------------
# trading_date
# ---------------------------------------------------------------------------

class TestTradingDate:
    _et = pytz.timezone("US/Eastern")

    def _et_dt(self, date_str, hour, minute=0):
        return self._et.localize(datetime(
            int(date_str[:4]), int(date_str[5:7]), int(date_str[8:]),
            hour, minute,
        ))

    def test_normal_collection_same_day(self):
        # 22:00 ET (after market close) → same calendar day
        assert trading_date(self._et_dt("2026-06-09", 22)) == "2026-06-09"

    def test_collection_at_market_open_boundary(self):
        # Exactly 9:00 AM ET → same day (market open, data is today's)
        assert trading_date(self._et_dt("2026-06-09", 9)) == "2026-06-09"

    def test_collection_before_market_open(self):
        # 2:19 AM ET → previous calendar day (Finviz shows yesterday's session)
        assert trading_date(self._et_dt("2026-06-09", 2, 19)) == "2026-06-08"

    def test_collection_just_before_boundary(self):
        # 8:59 AM ET → previous calendar day
        assert trading_date(self._et_dt("2026-06-09", 8, 59)) == "2026-06-08"

    def test_midnight_collection(self):
        # Midnight ET → previous calendar day
        assert trading_date(self._et_dt("2026-06-09", 0)) == "2026-06-08"

    def test_saturday_rolls_back_to_friday(self):
        # Sat 2026-06-13 evening → Friday 2026-06-12 (markets closed Saturday)
        assert trading_date(self._et_dt("2026-06-13", 20)) == "2026-06-12"

    def test_sunday_rolls_back_to_friday(self):
        # Sun 2026-06-14 evening → Friday 2026-06-12
        assert trading_date(self._et_dt("2026-06-14", 18)) == "2026-06-12"

    def test_monday_pre_open_rolls_back_to_friday(self):
        # Mon 2026-06-15 2 AM → step back to Sunday, then roll to Friday 06-12
        assert trading_date(self._et_dt("2026-06-15", 2)) == "2026-06-12"

    def test_saturday_pre_open_rolls_back_to_friday(self):
        # Sat 2026-06-13 1 AM → step back to Friday 06-12 directly
        assert trading_date(self._et_dt("2026-06-13", 1)) == "2026-06-12"


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

    def test_collect_raises_when_eviction_skipped(self, tmp_path, monkeypatch):
        """collect() raises RuntimeError if eviction is a no-op and all rows deduplicate."""
        import scripts.collect as collect_module

        snap_dir = tmp_path / "sectors"
        snap_dir.mkdir(parents=True)
        snap_path = snap_dir / "snapshots.csv"
        ensure_csv(snap_path)
        # Pre-populate with 2 rows dated 2026-06-09 so append_records returns 0
        for name in ["Technology", "Energy"]:
            rec = {col: "" for col in CSV_COLUMNS}
            rec.update({"date": "2026-06-09", "collected_at": "2026-06-09T06:00:00Z",
                        "group_type": "sector", "name": name})
            append_records(snap_path, [rec], set())

        monkeypatch.setattr(collect_module, "evict_today_rows", lambda path, date: 0)
        monkeypatch.setattr(collect_module, "trading_date", lambda _: "2026-06-09")
        monkeypatch.setattr(collect_module, "fetch_html", lambda url: MINIMAL_HTML)
        monkeypatch.setattr(collect_module, "DATA_DIR", tmp_path)

        with pytest.raises(RuntimeError, match="0 rows written"):
            collect_module.collect("sector")


# ---------------------------------------------------------------------------
# evict_today_rows — last-write-wins
# ---------------------------------------------------------------------------

class TestEvictTodayRows:
    def _write_rows(self, csv_path, rows):
        ensure_csv(csv_path)
        append_records(csv_path, rows, set())

    def _base_record(self, date, name):
        return {
            "date": date, "collected_at": f"{date}T22:00:00Z",
            "group_type": "sector", "name": name,
            "stocks": 10, "market_cap": 1.0, "pe": None, "fwd_pe": None,
            "perf_day": 1.0, "perf_week": 1.0, "perf_month": 1.0,
            "perf_quarter": 1.0, "perf_half": 1.0, "perf_year": 1.0, "perf_ytd": 1.0,
            "avg_volume": 1000, "rel_volume": None, "change": 1.0,
        }

    def test_evicts_only_target_date(self, tmp_path):
        csv_path = tmp_path / "snap.csv"
        self._write_rows(csv_path, [
            self._base_record("2026-06-08", "Tech"),
            self._base_record("2026-06-09", "Tech"),
        ])
        evicted = evict_today_rows(csv_path, "2026-06-09")
        assert evicted == 1
        with open(csv_path) as f:
            rows = list(csv.DictReader(f))
        assert len(rows) == 1
        assert rows[0]["date"] == "2026-06-08"

    def test_no_op_when_date_absent(self, tmp_path):
        csv_path = tmp_path / "snap.csv"
        self._write_rows(csv_path, [self._base_record("2026-06-08", "Tech")])
        evicted = evict_today_rows(csv_path, "2026-06-09")
        assert evicted == 0

    def test_no_op_on_missing_file(self, tmp_path):
        evicted = evict_today_rows(tmp_path / "nonexistent.csv", "2026-06-09")
        assert evicted == 0

    def test_second_run_overwrites_first(self, monkeypatch, tmp_path):
        """Re-running collect() on the same day replaces earlier data."""
        import scripts.collect as collect_module
        monkeypatch.setattr(collect_module, "DATA_DIR", tmp_path)
        monkeypatch.setattr(collect_module, "fetch_html", lambda url: "<html/>")

        first_records = [self._base_record("2026-06-09", f"G{i}") for i in range(10)]
        first_records[0]["perf_ytd"] = 99.0  # sentinel value from first run

        second_records = [self._base_record("2026-06-09", f"G{i}") for i in range(10)]
        second_records[0]["perf_ytd"] = 1.0   # different value in second run

        call_count = {"n": 0}
        def fake_parse(html, group_type, snapshot_date, collected_at):
            call_count["n"] += 1
            base = first_records if call_count["n"] == 1 else second_records
            return [{**r, "date": snapshot_date} for r in base]

        monkeypatch.setattr(collect_module, "parse_table", fake_parse)

        collect_module.collect("sector")
        collect_module.collect("sector")  # second run same day

        csv_path = tmp_path / "sectors" / "snapshots.csv"
        with open(csv_path) as f:
            rows = list(csv.DictReader(f))
        g0_rows = [r for r in rows if r["name"] == "G0"]
        assert len(g0_rows) == 1, "should have exactly one row for G0"
        assert float(g0_rows[0]["perf_ytd"]) == pytest.approx(1.0), "second run should win"


# ---------------------------------------------------------------------------
# collect() — row-count guard (T7)
# ---------------------------------------------------------------------------

def _fake_record(name):
    return {
        "date": "2026-06-09", "name": name, "collected_at": "",
        "group_type": "sector", "stocks": 1, "market_cap": 1.0,
        "pe": None, "fwd_pe": None,
        "perf_day": 0.1, "perf_week": 0.1, "perf_month": 0.1,
        "perf_quarter": 0.1, "perf_half": 0.1, "perf_year": 0.1, "perf_ytd": 0.1,
        "avg_volume": 1000, "rel_volume": None, "change": 0.1,
    }


class TestCollectRowCountGuard:
    def test_raises_on_zero_rows(self, monkeypatch, tmp_path):
        monkeypatch.setattr(collect_module, "DATA_DIR", tmp_path)
        monkeypatch.setattr(collect_module, "fetch_html", lambda url: "<html/>")
        monkeypatch.setattr(collect_module, "parse_table", lambda *a, **kw: [])
        with pytest.raises(RuntimeError, match="0 rows"):
            collect_module.collect("sector")

    def test_warns_when_below_floor(self, monkeypatch, tmp_path, capsys):
        monkeypatch.setattr(collect_module, "DATA_DIR", tmp_path)
        monkeypatch.setattr(collect_module, "fetch_html", lambda url: "<html/>")
        # 3 rows: above 0, below sector floor of 8
        monkeypatch.setattr(
            collect_module, "parse_table",
            lambda *a, **kw: [_fake_record(f"G{i}") for i in range(3)],
        )
        collect_module.collect("sector")  # must not raise
        assert "warn" in capsys.readouterr().err.lower()

    def test_no_warning_at_or_above_floor(self, monkeypatch, tmp_path, capsys):
        monkeypatch.setattr(collect_module, "DATA_DIR", tmp_path)
        monkeypatch.setattr(collect_module, "fetch_html", lambda url: "<html/>")
        # 10 rows: meets sector floor of 8
        monkeypatch.setattr(
            collect_module, "parse_table",
            lambda *a, **kw: [_fake_record(f"G{i}") for i in range(10)],
        )
        collect_module.collect("sector")
        assert "warn" not in capsys.readouterr().err.lower()
