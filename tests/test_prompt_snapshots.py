"""
Prompt snapshot tests.

Each task × group combination is rendered against fixture CSVs and asserted
against a golden .txt file in tests/fixtures/ai/prompts/. A prompt builder
change fails CI so the edit surfaces as a reviewable diff in the PR.

To update golden files after an intentional change:
    pytest tests/test_prompt_snapshots.py --update-snapshots

Or set UPDATE_SNAPSHOTS=1 env var. The test then writes the new golden file
and skips (so it shows as skipped, not passed, making the update intentional).
"""

import os
from pathlib import Path

import pandas as pd
import pytest

import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
from generate_ai import TASK_SPECS, _build_prompt

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "ai"
GOLDEN_DIR = FIXTURE_DIR / "prompts"
# Pinned date — must not change; determinism depends on it.
FIXTURE_DATE = "2026-06-22"


def _load_snap(group_type: str) -> pd.DataFrame:
    fname = "sectors_snapshots.csv" if group_type == "sector" else "industries_snapshots.csv"
    df = pd.read_csv(FIXTURE_DIR / fname)
    for col in ["perf_day", "perf_week", "perf_month", "perf_quarter",
                "perf_half", "perf_year", "perf_ytd", "market_cap", "pe", "fwd_pe"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.date
    latest = df["date"].max()
    return df[df["date"] == latest].copy()


def _load_delta(group_type: str) -> pd.DataFrame:
    fname = "sectors_deltas.csv" if group_type == "sector" else "industries_deltas.csv"
    df = pd.read_csv(FIXTURE_DIR / fname)
    for col in df.columns:
        if col not in ("date", "name"):
            df[col] = pd.to_numeric(df[col], errors="coerce")
    df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.date
    latest = df["date"].max()
    return df[df["date"] == latest].copy()


# One test case per task × group_type combination (mirrors TASK_SPECS)
CASES = [
    (spec["name"], gtype)
    for spec in TASK_SPECS
    for gtype in spec["group_types"]
]
CASE_IDS = [f"{t}.{g}" for t, g in CASES]


@pytest.mark.parametrize("task_name,group_type", CASES, ids=CASE_IDS)
def test_prompt_snapshot(task_name, group_type, request):
    """Rendered prompt must equal the golden file; fail CI when a builder changes."""
    spec = next(s for s in TASK_SPECS if s["name"] == task_name)
    snap_df = _load_snap(group_type)
    delta_df = _load_delta(group_type)

    prompt = _build_prompt(spec, group_type, snap_df, delta_df, FIXTURE_DATE)

    update = (
        request.config.getoption("--update-snapshots", default=False)
        or bool(os.getenv("UPDATE_SNAPSHOTS"))
    )
    golden_path = GOLDEN_DIR / f"{task_name}_{group_type}.txt"

    if update:
        GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
        golden_path.write_text(prompt, encoding="utf-8")
        pytest.skip(f"Updated: {golden_path.name}")
    else:
        assert golden_path.exists(), (
            f"Golden file missing: {golden_path.relative_to(Path(__file__).parent.parent)}. "
            "Run: pytest tests/test_prompt_snapshots.py --update-snapshots"
        )
        expected = golden_path.read_text(encoding="utf-8")
        assert prompt == expected, (
            f"Prompt changed for {task_name}×{group_type}. "
            "If intentional, rerun with --update-snapshots to commit the new golden file."
        )
