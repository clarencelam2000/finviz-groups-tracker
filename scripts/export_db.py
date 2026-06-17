"""
export_db.py — Export snapshot and delta CSVs to SQLite and Parquet files
in ./exports/ directory.
"""

import sqlite3
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from delta_config import delta_columns

BASE_DIR = Path(__file__).parent.parent
DATA_DIR = BASE_DIR / "data"
EXPORTS_DIR = BASE_DIR / "exports"

SNAPSHOT_COLS = [
    "date", "collected_at", "group_type", "name", "stocks", "market_cap",
    "pe", "fwd_pe", "perf_day", "perf_week", "perf_month", "perf_quarter",
    "perf_half", "perf_year", "perf_ytd", "avg_volume", "rel_volume", "change",
]

DELTA_COLUMNS = delta_columns()


def load_csv(path: Path, expected_cols: list) -> pd.DataFrame:
    if not path.exists():
        print(f"  File not found: {path}. Returning empty DataFrame.")
        return pd.DataFrame(columns=expected_cols)
    df = pd.read_csv(path)
    if df.empty:
        return pd.DataFrame(columns=expected_cols)
    return df


def export_all():
    EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
    db_path = BASE_DIR / "finviz_groups.db"

    print(f"Exporting to SQLite: {db_path}")
    conn = sqlite3.connect(db_path)

    for group_type, subdir in [("sector", "sectors"), ("industry", "industries")]:
        snap_path = DATA_DIR / subdir / "snapshots.csv"
        delta_path = DATA_DIR / subdir / "deltas.csv"

        snap_df = load_csv(snap_path, SNAPSHOT_COLS)
        delta_df = load_csv(delta_path, DELTA_COLUMNS)

        # SQLite
        snap_table = f"{subdir}_snapshots"
        delta_table = f"{subdir}_deltas"
        snap_df.to_sql(snap_table, conn, if_exists="replace", index=False)
        delta_df.to_sql(delta_table, conn, if_exists="replace", index=False)
        print(f"  Written tables: {snap_table} ({len(snap_df)} rows), {delta_table} ({len(delta_df)} rows)")

        # Parquet
        snap_parquet = EXPORTS_DIR / f"{subdir}_snapshots.parquet"
        delta_parquet = EXPORTS_DIR / f"{subdir}_deltas.parquet"

        if not snap_df.empty:
            snap_df.to_parquet(snap_parquet, index=False)
            print(f"  Written {snap_parquet}")
        else:
            print(f"  Skipping empty snapshot parquet for {subdir}")

        if not delta_df.empty:
            delta_df.to_parquet(delta_parquet, index=False)
            print(f"  Written {delta_parquet}")
        else:
            print(f"  Skipping empty delta parquet for {subdir}")

    conn.close()
    print("\nExport complete.")


if __name__ == "__main__":
    export_all()
