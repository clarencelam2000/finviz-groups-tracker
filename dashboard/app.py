"""
Finviz Groups Tracker — Streamlit Dashboard
"""

import datetime
import html as html_lib
import json
import os
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
from delta_config import LOOKBACK_WINDOWS, delta_columns

try:
    from dashboard.worker_client import lookup_ticker
except ModuleNotFoundError:  # `streamlit run dashboard/app.py` puts dashboard/ on sys.path
    from worker_client import lookup_ticker

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

DELTA_COLUMNS = delta_columns()


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

        today = datetime.date.today()
        days_old = (today - max_date).days
        dow = today.weekday()  # 0=Mon … 6=Sun
        weekend_gap = dow in (5, 6, 0) and days_old <= 3
        if days_old == 0:
            st.success(f"✅ Data current — {max_date}")
        elif weekend_gap:
            st.info(f"📅 Weekend — last data {max_date}")
        elif days_old == 1:
            st.warning(f"⚠️ Data from yesterday — {max_date}")
        else:
            st.error(f"🚨 Data stale — {max_date} ({days_old}d ago)")

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

    lookback = st.selectbox(
        "Lookback window (movers)", [f"{w}d" for w in LOOKBACK_WINDOWS]
    )

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
# Ticker lookup helpers (Worker join)
# ---------------------------------------------------------------------------

WORKER_URL = (
    st.secrets.get("WORKER_URL", None) if hasattr(st, "secrets") else None
) or os.getenv("WORKER_URL", "https://finviz-ticker-lookup.salmonbaby8.workers.dev")


def _group_row(name: str, snap_df_g: pd.DataFrame, delta_df_g: pd.DataFrame):
    """Merge the latest snapshot + delta row for a Finviz group ``name``.

    Returns a dict of combined fields, or ``None`` if the name is in neither frame.
    """
    if not name:
        return None
    snap = snap_df_g[snap_df_g["name"] == name] if not snap_df_g.empty else snap_df_g
    delta = delta_df_g[delta_df_g["name"] == name] if not delta_df_g.empty else delta_df_g
    if (snap is None or snap.empty) and (delta is None or delta.empty):
        return None
    row: dict = {}
    if snap is not None and not snap.empty:
        row.update(snap.iloc[-1].to_dict())
    if delta is not None and not delta.empty:
        row.update(delta.iloc[-1].to_dict())
    return row


def _render_group_card(name: str, group_type: str, label: str):
    """Render a rank / momentum / perf card for a Finviz group name."""
    snap_full = load_snapshots(group_type)
    delta_full = load_deltas(group_type)
    # restrict to the latest available date so the join matches "now"
    if not snap_full.empty and snap_full["date"].notna().any():
        latest = snap_full["date"].dropna().max()
        snap_full = snap_full[snap_full["date"] == latest]
    if not delta_full.empty and "date" in delta_full.columns and delta_full["date"].notna().any():
        dlatest = delta_full["date"].dropna().max()
        delta_full = delta_full[delta_full["date"] == dlatest]

    n = 11 if group_type == "Sectors" else len(delta_full)
    row = _group_row(name, snap_full, delta_full)
    st.markdown(f"**{label}: {name}**")
    if row is None:
        st.caption("Not separately tracked in the Finviz data yet.")
        return

    rank = row.get("rank_week")
    delta7 = row.get("rank_week_delta_7d")
    momentum = row.get("momentum_score")
    perf_week, perf_month, perf_ytd = row.get("perf_week"), row.get("perf_month"), row.get("perf_ytd")

    c1, c2, c3 = st.columns(3)
    with c1:
        rank_str = f"#{int(rank)} of {n}" if pd.notna(rank) else "–"
        if pd.notna(delta7) and delta7 > 0:
            delta_str = f"▲ +{int(delta7)} this week"
        elif pd.notna(delta7) and delta7 < 0:
            delta_str = f"▼ {int(delta7)} this week"
        else:
            delta_str = None
        st.metric("Rank (week)", rank_str, delta=delta_str)
    with c2:
        mom_str = f"{momentum:.2f}" if pd.notna(momentum) else "–"
        pct = f"top {int((1 - momentum) * 100)}%" if pd.notna(momentum) else None
        st.metric("Momentum", mom_str, delta=pct, delta_color="off")
    with c3:
        if all(pd.notna(v) for v in (perf_week, perf_month, perf_ytd)):
            st.metric("Perf Wk / Mo / YTD", f"{perf_week:+.1f}%",
                      delta=f"Mo {perf_month:+.1f}% · YTD {perf_ytd:+.1f}%", delta_color="off")
        else:
            st.metric("Perf (week)", f"{perf_week:+.1f}%" if pd.notna(perf_week) else "–")


# ---------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------

tab1, tab2, tab3, tab4, tab5, tab6, tab7, tab8 = st.tabs(
    ["Snapshot", "Top Movers", "Time Series", "Momentum", "Heatmap", "Strength", "AI Insights", "Ticker Lookup"]
)

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
            # Join rank columns from latest deltas
            rank_cols = ["rank_day", "rank_week", "rank_month", "rank_ytd"]
            if not delta_df.empty and "date" in delta_df.columns:
                latest_delta_for_join = delta_df[delta_df["date"] == latest_date][
                    ["name"] + [c for c in rank_cols if c in delta_df.columns]
                ]
                latest_snap = latest_snap.merge(latest_delta_for_join, on="name", how="left")

            # Sort by selected metric descending
            if selected_metric in latest_snap.columns:
                latest_snap = latest_snap.sort_values(selected_metric, ascending=False)

            display_cols = [
                "name", "rank_day", "rank_week", "rank_month", "rank_ytd",
                "stocks", "market_cap", "pe", "fwd_pe",
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
            st.download_button(
                label="Download as CSV",
                data=latest_snap[display_cols].to_csv(index=False).encode("utf-8"),
                file_name=f"finviz_{group_label.lower()}_snapshot_{latest_date}.csv",
                mime="text/csv",
                key="snapshot_download",
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
                    st.download_button(
                        label="Download gainers CSV",
                        data=gainers.to_csv(index=False).encode("utf-8"),
                        file_name=f"finviz_{group_label.lower()}_gainers_{latest_date}.csv",
                        mime="text/csv",
                        key="gainers_download",
                    )

                with col2:
                    st.markdown("**Top 10 Rank Losers** (most declined)")
                    losers = valid.nsmallest(10, delta_col)[["name", delta_col, "rank_ytd", "momentum_score"]]
                    st.dataframe(losers.reset_index(drop=True), use_container_width=True)
                    st.download_button(
                        label="Download losers CSV",
                        data=losers.to_csv(index=False).encode("utf-8"),
                        file_name=f"finviz_{group_label.lower()}_losers_{latest_date}.csv",
                        mime="text/csv",
                        key="losers_download",
                    )

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
            PALETTE = ["royalblue", "firebrick", "green"]

            selected_names = st.multiselect(
                "Select groups (up to 3 for comparison)",
                all_names,
                default=all_names[:1],
                max_selections=3,
            )

            if not selected_names:
                st.info("Select at least one group.")
            elif not HAS_PLOTLY:
                st.warning("plotly is not installed. Install with: pip install plotly")
                for name in selected_names:
                    ts_df = snap_df_full[snap_df_full["name"] == name].sort_values("date")
                    st.caption(name)
                    st.dataframe(ts_df[["date", "perf_ytd", "perf_week"]].reset_index(drop=True))
            else:
                fig = make_subplots(specs=[[{"secondary_y": True}]])

                for i, name in enumerate(selected_names):
                    color = PALETTE[i % len(PALETTE)]
                    ts_df = snap_df_full[snap_df_full["name"] == name].sort_values("date")
                    ts_delta = (
                        delta_df_full[delta_df_full["name"] == name].sort_values("date")
                        if not delta_df_full.empty and "name" in delta_df_full.columns
                        else pd.DataFrame()
                    )

                    if ts_df.empty:
                        continue

                    fig.add_trace(
                        go.Scatter(
                            x=ts_df["date"].astype(str),
                            y=ts_df["perf_ytd"],
                            name=f"{name} — perf_ytd",
                            line=dict(color=color),
                        ),
                        secondary_y=False,
                    )

                    if not ts_delta.empty and "rank_ytd" in ts_delta.columns:
                        fig.add_trace(
                            go.Scatter(
                                x=ts_delta["date"].astype(str),
                                y=ts_delta["rank_ytd"],
                                name=f"{name} — rank_ytd",
                                line=dict(color=color, dash="dot"),
                            ),
                            secondary_y=True,
                        )

                fig.update_layout(
                    title=", ".join(selected_names) + " — YTD Perf & Rank",
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

            momentum_display = momentum_df[["name", "momentum_score", "rank_ytd", "rank_week"]]
            st.dataframe(
                momentum_display.reset_index(drop=True),
                use_container_width=True,
                height=500,
            )
            st.download_button(
                label="Download as CSV",
                data=momentum_display.to_csv(index=False).encode("utf-8"),
                file_name=f"finviz_{group_label.lower()}_momentum_{latest_date}.csv",
                mime="text/csv",
                key="momentum_download",
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

# ---- Tab 5: Heatmap --------------------------------------------------------

with tab5:
    st.subheader("Rank Delta Heatmap")

    n_dates = delta_df["date"].nunique() if not delta_df.empty and "date" in delta_df.columns else 0
    if n_dates < 7:
        days_remaining = max(0, 7 - n_dates)
        st.info(
            f"Heatmap needs at least 7 days of data. "
            f"Currently have {n_dates} day(s). "
            f"Check back after {days_remaining} more trading day(s)."
        )
    elif not HAS_PLOTLY:
        st.warning("Install plotly for charts: pip install plotly")
    else:
        heatmap_delta_cols = sorted([c for c in delta_df.columns if "delta" in c])
        if not heatmap_delta_cols:
            st.info("No delta columns available yet.")
        else:
            default_col = "rank_ytd_delta_7d" if "rank_ytd_delta_7d" in heatmap_delta_cols else heatmap_delta_cols[0]
            selected_delta = st.selectbox(
                "Delta metric", heatmap_delta_cols,
                index=heatmap_delta_cols.index(default_col),
            )

            pivot = delta_df.pivot_table(
                index="name", columns="date", values=selected_delta, aggfunc="first"
            )
            # Sort rows: best average delta at top; sort columns: ascending date
            row_means = pivot.mean(axis=1, skipna=True)
            pivot = pivot.loc[row_means.sort_values(ascending=False).index]
            pivot = pivot[sorted(pivot.columns)]

            fig = go.Figure(go.Heatmap(
                z=pivot.values,
                x=[str(d) for d in pivot.columns],
                y=pivot.index.tolist(),
                colorscale="RdYlGn",
                zmid=0,
                hoverongaps=False,
            ))
            fig.update_layout(
                title=f"Rank Delta Heatmap — {selected_delta}",
                xaxis_title="Date",
                height=max(400, len(pivot) * 18),
            )
            st.plotly_chart(fig, use_container_width=True)

# ---- Tab 6: Strength -------------------------------------------------------

with tab6:
    st.subheader(f"Strength Screens — {latest_date or 'No data'}")

    if delta_df.empty or snap_df.empty or latest_date is None:
        st.info("No data available yet.")
    else:
        latest_delta = (
            delta_df[delta_df["date"] == latest_date].copy()
            if "date" in delta_df.columns else pd.DataFrame()
        )
        latest_snap = (
            snap_df[snap_df["date"] == latest_date].copy()
            if "date" in snap_df.columns else pd.DataFrame()
        )

        if latest_delta.empty or latest_snap.empty:
            st.info(f"No data for {latest_date}.")
        else:
            # ---- Section 1: Sustained Strength --------------------------------
            st.markdown("### Sustained Strength")
            st.caption(
                "Groups that are top-N in rank_month, rank_quarter, AND rank_half simultaneously. "
                "Confirms a trend is not a recent flash — it's sustained across 1, 3, and 6 months."
            )

            n_total = len(latest_delta)
            top_n_min = 5
            top_n_max = max(top_n_min, n_total // 3)
            top_n_default = min(top_n_max, max(top_n_min, n_total // 4))
            top_n = st.slider(
                "Top N threshold", min_value=top_n_min, max_value=top_n_max,
                value=top_n_default,
                step=5,
                key="strength_top_n",
            )

            rank_cols_needed = ["rank_month", "rank_quarter", "rank_half"]
            has_rank_cols = all(c in latest_delta.columns for c in rank_cols_needed)

            if not has_rank_cols:
                st.warning("rank_quarter / rank_half columns not yet computed. Run compute_deltas.py.")
            else:
                sustained = latest_delta[
                    (latest_delta["rank_month"] <= top_n) &
                    (latest_delta["rank_quarter"] <= top_n) &
                    (latest_delta["rank_half"] <= top_n)
                ].copy()

                weak = latest_delta[
                    (latest_delta["rank_month"] > n_total - top_n) &
                    (latest_delta["rank_quarter"] > n_total - top_n) &
                    (latest_delta["rank_half"] > n_total - top_n)
                ].copy()

                col_a, col_b = st.columns(2)

                with col_a:
                    st.markdown(f"**Consistently Strong** ({len(sustained)} groups)")
                    if sustained.empty:
                        st.info(f"No groups in top {top_n} across all three timeframes.")
                    else:
                        display_cols = [c for c in [
                            "name", "rank_month", "rank_quarter", "rank_half",
                            "momentum_score", "rank_agreement",
                        ] if c in sustained.columns]
                        sustained_sorted = sustained.sort_values("momentum_score", ascending=False)
                        st.dataframe(sustained_sorted[display_cols].reset_index(drop=True), use_container_width=True)
                        st.download_button(
                            label="Download CSV",
                            data=sustained_sorted[display_cols].to_csv(index=False).encode("utf-8"),
                            file_name=f"finviz_{group_label.lower()}_sustained_strong_{latest_date}.csv",
                            mime="text/csv",
                            key="sustained_strong_download",
                        )

                with col_b:
                    st.markdown(f"**Consistently Weak** (bottom {top_n})")
                    if weak.empty:
                        st.info(f"No groups in bottom {top_n} across all three timeframes.")
                    else:
                        display_cols = [c for c in [
                            "name", "rank_month", "rank_quarter", "rank_half",
                            "momentum_score", "rank_agreement",
                        ] if c in weak.columns]
                        weak_sorted = weak.sort_values("momentum_score", ascending=True)
                        st.dataframe(weak_sorted[display_cols].reset_index(drop=True), use_container_width=True)
                        st.download_button(
                            label="Download CSV",
                            data=weak_sorted[display_cols].to_csv(index=False).encode("utf-8"),
                            file_name=f"finviz_{group_label.lower()}_sustained_weak_{latest_date}.csv",
                            mime="text/csv",
                            key="sustained_weak_download",
                        )

            # ---- Section 2: All Green -----------------------------------------
            st.markdown("---")
            st.markdown("### All Green")
            st.caption(
                "Groups where performance is positive across every timeframe checked. "
                "Everything trending up — no mixed signals."
            )

            perf_timeframes = ["perf_week", "perf_month", "perf_quarter", "perf_half", "perf_ytd"]
            available_tf = [c for c in perf_timeframes if c in latest_snap.columns]

            if not available_tf:
                st.warning("No perf columns found in snapshot data.")
            else:
                snap_with_delta = latest_snap.merge(
                    latest_delta[["name", "momentum_score", "rank_agreement"]].dropna(subset=["momentum_score"]),
                    on="name", how="left",
                )

                mask = pd.Series(True, index=snap_with_delta.index)
                for tf in available_tf:
                    mask = mask & (snap_with_delta[tf].fillna(0) > 0)
                all_green = snap_with_delta[mask].copy()

                st.markdown(
                    f"**{len(all_green)} of {len(snap_with_delta)} groups are all-green** "
                    f"({', '.join(available_tf)})"
                )

                if all_green.empty:
                    st.info("No groups are positive across all timeframes right now.")
                else:
                    all_green_sorted = all_green.sort_values("momentum_score", ascending=False)

                    def dot(val):
                        if pd.isna(val):
                            return "⬜"
                        return "🟢" if val > 0 else "🔴"

                    rows_html = []
                    for _, r in all_green_sorted.iterrows():
                        dots = "".join(dot(r.get(tf)) for tf in available_tf)
                        ms = f"{r['momentum_score']:.2f}" if pd.notna(r.get("momentum_score")) else "—"
                        ra = f"{r['rank_agreement']:.2f}" if pd.notna(r.get("rank_agreement")) else "—"
                        rows_html.append(
                            f"<tr><td><b>{html_lib.escape(str(r['name']))}</b></td><td>{dots}</td>"
                            f"<td style='text-align:center'>{ms}</td>"
                            f"<td style='text-align:center'>{ra}</td></tr>"
                        )

                    header_tfs = [tf.replace("perf_", "") for tf in available_tf]
                    header = (
                        "<tr><th>Group</th>"
                        f"<th title='{', '.join(header_tfs)}'>wk&nbsp;mo&nbsp;qtr&nbsp;half&nbsp;ytd</th>"
                        "<th>Momentum</th><th>Agreement</th></tr>"
                    )
                    table_html = (
                        "<table style='border-collapse:collapse;width:100%'>"
                        + header + "".join(rows_html) + "</table>"
                    )
                    st.markdown(table_html, unsafe_allow_html=True)

                    st.download_button(
                        label="Download All Green CSV",
                        data=all_green_sorted[
                            ["name"] + available_tf + ["momentum_score", "rank_agreement"]
                        ].to_csv(index=False).encode("utf-8"),
                        file_name=f"finviz_{group_label.lower()}_all_green_{latest_date}.csv",
                        mime="text/csv",
                        key="all_green_download",
                    )

# ---- Tab 7: AI Insights ----------------------------------------------------

with tab7:
    st.subheader("AI Insights")

    ai_dir = DATA_DIR / "ai"
    ai_file = None

    # Prefer index.json: find the most recent entry with status "complete".
    index_path = ai_dir / "index.json"
    if index_path.exists():
        try:
            idx = json.loads(index_path.read_text(encoding="utf-8"))
            for entry in idx.get("entries", []):
                if entry.get("status") == "complete":
                    candidate = ai_dir / f"{entry['date']}.json"
                    if candidate.exists():
                        ai_file = candidate
                        break
        except (json.JSONDecodeError, OSError):
            pass

    # Glob fallback for repos that predate index.json.
    if ai_file is None and ai_dir.exists():
        existing = [p for p in sorted(ai_dir.glob("*.json")) if p.stem != "index"]
        if existing:
            ai_file = existing[-1]

    if ai_file is None:
        st.info(
            "AI analysis not yet available. "
            "It is generated automatically after each evening data collection "
            "(requires GEMINI_API_KEY in GitHub Actions secrets)."
        )
    else:
        try:
            ai_data = json.loads(ai_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            st.warning("Could not read AI analysis file.")
            ai_data = None

        if ai_data:
            gen_at = ai_data.get("generated_at", "")
            model_name = ai_data.get("model", "")
            caption = f"Generated {gen_at} · {model_name}" if gen_at else ""
            if caption:
                st.caption(caption)

            # --- Rotation phase (sectors only) ---
            sector_data = ai_data.get("sectors", {})
            phase = sector_data.get("rotation_phase")
            if phase:
                label = phase.get("label", "")
                reasoning = phase.get("reasoning", "")
                phase_colors = {
                    "Early Cycle": "🟢",
                    "Mid Cycle": "🟡",
                    "Late Cycle": "🟠",
                    "Defensive": "🔵",
                }
                icon = phase_colors.get(label, "⚪")
                st.markdown(f"### {icon} Rotation Phase: {label}")
                if reasoning:
                    st.markdown(f"*{reasoning}*")
                st.divider()

            # --- Watchlist (sectors only) ---
            watchlist = sector_data.get("watchlist", [])
            if watchlist:
                st.markdown("### Watchlist — Top Setups")
                for i, item in enumerate(watchlist, 1):
                    name = item.get("name", "")
                    thesis = item.get("thesis", "")
                    st.markdown(f"**{i}. {name}** — {thesis}")
                st.divider()

            # --- Briefings ---
            group_key = "sectors" if group_label == "Sectors" else "industries"
            briefing = ai_data.get(group_key, {}).get("briefing", "")
            if briefing:
                st.markdown(f"### Daily Briefing — {group_label}")
                st.markdown(briefing)
            else:
                st.info(f"No briefing available for {group_label.lower()} yet.")

# ---- Tab 8: Ticker Lookup --------------------------------------------------

with tab8:
    st.subheader("Ticker Lookup")
    st.caption(
        "Enter a ticker to see its Finviz sector/industry and how those groups "
        "are tracking right now."
    )
    symbol = st.text_input("Ticker symbol", placeholder="e.g. AAPL", max_chars=10).strip().upper()

    if symbol:
        with st.spinner(f"Looking up {symbol}…"):
            result = lookup_ticker(symbol, f"{WORKER_URL.rstrip('/')}/lookup")

        err = result.get("error")
        if err:
            if err == "ticker_not_found":
                st.warning(f"'{symbol}' not found. Verify it is a US-listed symbol.")
            elif err == "rate_limited":
                st.warning("Lookup service is rate-limited. Try again in a moment.")
            elif err in ("timeout", "fmp_timeout", "fmp_unavailable", "network_error"):
                st.warning("Lookup service unavailable. Try again shortly.")
            else:
                st.warning(f"Lookup error: {err}")
        else:
            mktcap = result.get("market_cap_b")
            mkt_str = ""
            if isinstance(mktcap, (int, float)):
                mkt_str = f"${mktcap / 1000:.2f}T" if mktcap >= 1000 else f"${mktcap:.0f}B"
            header = result.get("company_name") or symbol
            st.markdown(f"## {header} `{symbol}`")
            meta = " · ".join(x for x in (result.get("exchange", ""), mkt_str) if x)
            if meta:
                st.caption(meta)
            if result.get("description"):
                with st.expander("Company description"):
                    st.write(result["description"])

            finviz_sector = result.get("finviz_sector")
            finviz_industry = result.get("finviz_industry")
            confidence = result.get("industry_confidence")

            classified = f"**Finviz Classification:** {finviz_sector or '—'} › {finviz_industry or '(no industry match)'}"
            st.markdown(classified)
            if finviz_industry and isinstance(confidence, (int, float)):
                if confidence < 0.5:
                    st.caption(f"⚠️ Low confidence match ({confidence:.0%}) — verify manually")
                else:
                    st.caption(f"Industry match: {confidence:.0%} confidence")

            if finviz_industry:
                st.divider()
                _render_group_card(finviz_industry, "Industries", "Industry")
            if finviz_sector:
                st.divider()
                _render_group_card(finviz_sector, "Sectors", "Sector")
