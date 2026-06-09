"""
Finviz Groups Tracker — Streamlit Dashboard
"""

from pathlib import Path

import pandas as pd
import streamlit as st

try:
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots
    HAS_PLOTLY = True
except ImportError:
    HAS_PLOTLY = False

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).parent.parent
DATA_DIR = BASE_DIR / "data"

SNAPSHOT_COLS = [
    "date", "collected_at", "group_type", "name", "stocks", "market_cap",
    "pe", "fwd_pe", "perf_day", "perf_week", "perf_month", "perf_quarter",
    "perf_half", "perf_year", "perf_ytd", "avg_volume", "rel_volume", "change",
]

DELTA_COLUMNS = [
    "date", "name",
    "rank_week", "rank_month", "rank_quarter", "rank_half", "rank_year", "rank_ytd",
    "rank_week_delta_7d", "rank_week_delta_14d", "rank_week_delta_30d",
    "rank_month_delta_7d", "rank_month_delta_14d", "rank_month_delta_30d",
    "rank_ytd_delta_7d", "rank_ytd_delta_14d", "rank_ytd_delta_30d",
    "perf_week_delta_7d", "perf_week_delta_14d", "perf_week_delta_30d",
    "perf_month_delta_7d",
    "perf_ytd_delta_7d", "perf_ytd_delta_30d",
    "momentum_score",
]


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

@st.cache_data(ttl=300)
def load_snapshots(group_label: str) -> pd.DataFrame:
    subdir = "sectors" if group_label == "Sectors" else "industries"
    path = DATA_DIR / subdir / "snapshots.csv"
    if not path.exists():
        return pd.DataFrame(columns=SNAPSHOT_COLS)
    df = pd.read_csv(path)
    if df.empty:
        return pd.DataFrame(columns=SNAPSHOT_COLS)
    numeric_cols = [
        "stocks", "market_cap", "pe", "fwd_pe", "perf_day", "perf_week",
        "perf_month", "perf_quarter", "perf_half", "perf_year", "perf_ytd",
        "avg_volume", "rel_volume", "change",
    ]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.date
    return df


@st.cache_data(ttl=300)
def load_deltas(group_label: str) -> pd.DataFrame:
    subdir = "sectors" if group_label == "Sectors" else "industries"
    path = DATA_DIR / subdir / "deltas.csv"
    if not path.exists():
        return pd.DataFrame(columns=DELTA_COLUMNS)
    df = pd.read_csv(path)
    if df.empty:
        return pd.DataFrame(columns=DELTA_COLUMNS)
    for col in df.columns:
        if col not in ("date", "name"):
            df[col] = pd.to_numeric(df[col], errors="coerce")
    df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.date
    return df


# ---------------------------------------------------------------------------
# Page setup
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="Finviz Groups Tracker",
    page_icon="📈",
    layout="wide",
)

st.title("Finviz Groups Tracker")

# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

with st.sidebar:
    st.header("Filters")
    group_label = st.selectbox("Group Type", ["Sectors", "Industries"])

    snap_df_full = load_snapshots(group_label)
    delta_df_full = load_deltas(group_label)

    if snap_df_full.empty or "date" not in snap_df_full.columns or snap_df_full["date"].isna().all():
        st.warning("No snapshot data available yet.")
        available_dates = []
        date_range = (None, None)
    else:
        available_dates = sorted(snap_df_full["date"].dropna().unique())
        min_date = available_dates[0]
        max_date = available_dates[-1]

        if len(available_dates) > 1:
            start_date, end_date = st.select_slider(
                "Date range",
                options=available_dates,
                value=(min_date, max_date),
            )
            date_range = (start_date, end_date)
        else:
            st.info(f"Only one date available: {min_date}")
            date_range = (min_date, min_date)

    metric_options = [
        "perf_day", "perf_week", "perf_month", "perf_quarter",
        "perf_half", "perf_year", "perf_ytd",
    ]
    selected_metric = st.selectbox("Rank by metric", metric_options, index=6)

    lookback = st.selectbox("Lookback window (movers)", ["7d", "14d", "30d"])

# ---------------------------------------------------------------------------
# Filter data
# ---------------------------------------------------------------------------

if available_dates:
    start_date, end_date = date_range
    snap_df = snap_df_full[
        (snap_df_full["date"] >= start_date) & (snap_df_full["date"] <= end_date)
    ].copy()
    delta_df = delta_df_full.copy()
    if not delta_df.empty and "date" in delta_df.columns:
        delta_df = delta_df[
            (delta_df["date"] >= start_date) & (delta_df["date"] <= end_date)
        ].copy()
    latest_date = end_date
else:
    snap_df = snap_df_full.copy()
    delta_df = delta_df_full.copy()
    latest_date = None

# ---------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------

tab1, tab2, tab3, tab4 = st.tabs(["Snapshot", "Top Movers", "Time Series", "Momentum"])

# ---- Tab 1: Snapshot -------------------------------------------------------

with tab1:
    st.subheader(f"Latest Snapshot — {latest_date or 'No data'}")

    if snap_df.empty or latest_date is None:
        st.info("No snapshot data available yet. Run `python scripts/collect.py` to collect data.")
    else:
        latest_snap = snap_df[snap_df["date"] == latest_date].copy()
        if latest_snap.empty:
            st.info(f"No data for {latest_date}.")
        else:
            # Sort by selected metric descending
            if selected_metric in latest_snap.columns:
                latest_snap = latest_snap.sort_values(selected_metric, ascending=False)

            display_cols = [
                "name", "stocks", "market_cap", "pe", "fwd_pe",
                "perf_day", "perf_week", "perf_month", "perf_quarter",
                "perf_half", "perf_year", "perf_ytd", "change",
                "avg_volume", "rel_volume",
            ]
            display_cols = [c for c in display_cols if c in latest_snap.columns]
            st.dataframe(
                latest_snap[display_cols].reset_index(drop=True),
                use_container_width=True,
                height=600,
            )

# ---- Tab 2: Top Movers -----------------------------------------------------

with tab2:
    st.subheader(f"Top Movers — {lookback} lookback")

    if delta_df.empty or latest_date is None:
        st.info("No delta data available yet. Run `python scripts/compute_deltas.py` after collecting snapshots.")
    else:
        latest_delta = delta_df[delta_df["date"] == latest_date].copy() if "date" in delta_df.columns else pd.DataFrame()

        if latest_delta.empty:
            st.info(f"No delta rows for {latest_date}.")
        else:
            delta_col = f"rank_ytd_delta_{lookback}"
            if delta_col not in latest_delta.columns:
                st.warning(f"Column {delta_col} not found in deltas.")
            else:
                latest_delta[delta_col] = pd.to_numeric(latest_delta[delta_col], errors="coerce")
                valid = latest_delta.dropna(subset=[delta_col])

                col1, col2 = st.columns(2)
                with col1:
                    st.markdown("**Top 10 Rank Gainers** (most improved)")
                    gainers = valid.nlargest(10, delta_col)[["name", delta_col, "rank_ytd", "momentum_score"]]
                    st.dataframe(gainers.reset_index(drop=True), use_container_width=True)

                with col2:
                    st.markdown("**Top 10 Rank Losers** (most declined)")
                    losers = valid.nsmallest(10, delta_col)[["name", delta_col, "rank_ytd", "momentum_score"]]
                    st.dataframe(losers.reset_index(drop=True), use_container_width=True)

# ---- Tab 3: Time Series ----------------------------------------------------

with tab3:
    st.subheader("Time Series")

    if snap_df.empty or not available_dates:
        st.info("No data available yet.")
    else:
        all_names = sorted(snap_df_full["name"].dropna().unique().tolist())
        if not all_names:
            st.info("No group names found in snapshot data.")
        else:
            selected_name = st.selectbox("Select group", all_names)

            ts_df = snap_df_full[snap_df_full["name"] == selected_name].sort_values("date")
            ts_delta = (
                delta_df_full[delta_df_full["name"] == selected_name].sort_values("date")
                if not delta_df_full.empty and "name" in delta_df_full.columns
                else pd.DataFrame()
            )

            if ts_df.empty:
                st.info(f"No time series data for {selected_name}.")
            elif not HAS_PLOTLY:
                st.warning("plotly is not installed. Install with: pip install plotly")
                st.dataframe(ts_df[["date", "perf_ytd", "perf_week"]].reset_index(drop=True))
            else:
                fig = make_subplots(specs=[[{"secondary_y": True}]])

                fig.add_trace(
                    go.Scatter(
                        x=ts_df["date"].astype(str),
                        y=ts_df["perf_ytd"],
                        name="perf_ytd (%)",
                        line=dict(color="royalblue"),
                    ),
                    secondary_y=False,
                )

                if not ts_delta.empty and "rank_ytd" in ts_delta.columns:
                    fig.add_trace(
                        go.Scatter(
                            x=ts_delta["date"].astype(str),
                            y=ts_delta["rank_ytd"],
                            name="rank_ytd",
                            line=dict(color="firebrick", dash="dot"),
                        ),
                        secondary_y=True,
                    )

                fig.update_layout(
                    title=f"{selected_name} — YTD Perf & Rank over Time",
                    xaxis_title="Date",
                    hovermode="x unified",
                    height=500,
                )
                fig.update_yaxes(title_text="perf_ytd (%)", secondary_y=False)
                fig.update_yaxes(title_text="rank_ytd (1=best)", secondary_y=True, autorange="reversed")

                st.plotly_chart(fig, use_container_width=True)

# ---- Tab 4: Momentum -------------------------------------------------------

with tab4:
    st.subheader(f"Momentum Leaderboard — {latest_date or 'No data'}")

    if delta_df.empty or latest_date is None:
        st.info("No delta data available yet.")
    else:
        latest_delta = (
            delta_df[delta_df["date"] == latest_date].copy()
            if "date" in delta_df.columns
            else pd.DataFrame()
        )

        if latest_delta.empty:
            st.info(f"No delta rows for {latest_date}.")
        elif "momentum_score" not in latest_delta.columns:
            st.warning("momentum_score column not found.")
        else:
            latest_delta["momentum_score"] = pd.to_numeric(latest_delta["momentum_score"], errors="coerce")
            momentum_df = latest_delta.dropna(subset=["momentum_score"]).sort_values(
                "momentum_score", ascending=False
            )

            st.dataframe(
                momentum_df[["name", "momentum_score", "rank_ytd", "rank_week"]].reset_index(drop=True),
                use_container_width=True,
                height=500,
            )

            if HAS_PLOTLY and not momentum_df.empty:
                fig = go.Figure(
                    go.Bar(
                        x=momentum_df["name"],
                        y=momentum_df["momentum_score"],
                        marker_color="steelblue",
                    )
                )
                fig.update_layout(
                    title="Momentum Score by Group",
                    xaxis_title="Group",
                    yaxis_title="Momentum Score (0–1)",
                    xaxis_tickangle=-45,
                    height=450,
                )
                st.plotly_chart(fig, use_container_width=True)
            elif not HAS_PLOTLY:
                st.warning("Install plotly for charts: pip install plotly")
