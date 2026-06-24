"""Pure functions for sector breadth computation — importable and testable."""
import pandas as pd


def compute_sector_breadth(
    industry_delta: pd.DataFrame,
    taxonomy: dict,
    rank_col: str = "rank_week",
) -> pd.DataFrame:
    """For each sector, count how many of its industries rank in the top half of
    the full universe by rank_col (rank 1 = best, lower = better).

    Args:
        industry_delta: latest-date industries deltas DataFrame with rank columns.
        taxonomy: dict mapping sector name → list of industry names.
        rank_col: which rank column to use; defaults to rank_week.

    Returns:
        DataFrame with columns: sector, n_mapped, n_top_half, pct_top_half.
        Sorted descending by pct_top_half. Empty DataFrame when input is empty
        or rank_col is absent.
    """
    if industry_delta.empty or rank_col not in industry_delta.columns:
        return pd.DataFrame(columns=["sector", "n_mapped", "n_top_half", "pct_top_half"])

    n_total = len(industry_delta)
    threshold = n_total / 2  # rank <= threshold → top half

    rows = []
    for sector, industries in sorted(taxonomy.items()):
        if not industries:
            continue
        sector_df = industry_delta[industry_delta["name"].isin(industries)]
        n_mapped = len(sector_df)
        if n_mapped == 0:
            continue
        valid = sector_df[rank_col].dropna()
        n_top_half = int((valid <= threshold).sum())
        n_valid = len(valid)
        pct = n_top_half / n_valid if n_valid > 0 else 0.0
        rows.append({
            "sector": sector,
            "n_mapped": n_mapped,
            "n_top_half": n_top_half,
            "pct_top_half": pct,
        })

    if not rows:
        return pd.DataFrame(columns=["sector", "n_mapped", "n_top_half", "pct_top_half"])

    return (
        pd.DataFrame(rows)
        .sort_values("pct_top_half", ascending=False)
        .reset_index(drop=True)
    )
