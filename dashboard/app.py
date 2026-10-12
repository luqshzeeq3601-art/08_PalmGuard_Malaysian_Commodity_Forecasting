"""PalmGuard Streamlit Dashboard (Task T22).

Production web interface for monitoring Malaysian palm oil price forecasts,
conformal prediction bands, error analysis, feature drift, and data licensing.
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st

st.set_page_config(
    page_title="PalmGuard | Malaysian Commodity Forecasting",
    page_icon="🌴",
    layout="wide",
)

PUBLISHED_DIR = Path("reports/published")
REPORTS_DIR = Path("reports")
ARTIFACTS_DIR = Path("artifacts/champion")
ROLLING_ORIGINS = 12


def load_forecasts() -> dict:
    fpath = PUBLISHED_DIR / "forecast.json"
    if not fpath.exists():
        return {}
    with open(fpath, encoding="utf-8") as f:
        return json.load(f)


def load_monitoring() -> dict:
    mpath = PUBLISHED_DIR / "monitoring.json"
    if not mpath.exists():
        return {}
    with open(mpath, encoding="utf-8") as f:
        return json.load(f)


def load_history() -> pd.DataFrame:
    hpath = PUBLISHED_DIR / "history.parquet"
    if not hpath.exists():
        return pd.DataFrame()
    return pd.read_parquet(hpath)


def load_csv(name: str) -> pd.DataFrame:
    path = REPORTS_DIR / name
    return pd.read_csv(path) if path.exists() else pd.DataFrame()


def load_backtest_intervals() -> pd.DataFrame:
    """Per-forecast backtest intervals of the selected method, validation then holdout."""
    frames = [load_csv("validation_intervals.csv"), load_csv("holdout_intervals.csv")]
    frames = [f for f in frames if not f.empty]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def load_champions() -> dict:
    mpath = ARTIFACTS_DIR / "metadata.json"
    if not mpath.exists():
        return {}
    with open(mpath, encoding="utf-8") as f:
        return json.load(f).get("selected_champions", {})


# Title and Header
st.title("🌴 PalmGuard: Malaysian Commodity Forecasting Engine")
st.markdown(
    "**Open-Licence Forecasting Demonstrator for Malaysian Palm Oil Benchmarks & PPI Series**"
)

# Mandatory Disclaimer Alert
st.warning(
    "**Notice & Disclaimer:** PalmGuard is a research and forecasting demonstrator. "
    "It is NOT trading, investment or procurement advice. No financial benefit was measured. "
    "Prediction interval coverage is empirical on historical data and is NOT guaranteed."
)

forecast_data = load_forecasts()
monitoring_data = load_monitoring()
history_df = load_history()

if not forecast_data:
    st.error("No published forecast artifacts found. Please run `palmguard pipeline run` first.")
    st.stop()

# Sidebar: Series selection
st.sidebar.header("Configuration")
series_options = {
    "palm_wb_myr": "Palm Oil Benchmark (World Bank Pink Sheet, MYR/mt)",
    "ppi_oilsfats_my": "DOSM Producer Price Index — Oils & Fats (2010=100)",
}
selected_series = st.sidebar.selectbox(
    "Select Target Series",
    options=list(series_options.keys()),
    format_func=lambda x: series_options[x],
)

# Tabs
tab_forecast, tab_eval, tab_drift, tab_sources = st.tabs(
    [
        "📈 Live Forecast & Bands",
        "📊 Backtest & Live Performance",
        "🔍 Drift & Monitoring",
        "ℹ️ Data & Licences",
    ]
)

with tab_forecast:
    st.subheader(f"Current Published Forecast: {series_options[selected_series]}")
    fcs = [f for f in forecast_data.get("forecasts", []) if f.get("series_id") == selected_series]
    if fcs:
        cols = st.columns(len(fcs))
        for idx, fc in enumerate(fcs):
            with cols[idx]:
                st.metric(
                    label=f"Horizon {fc['horizon']} ({fc['target_month']})",
                    value=f"{fc['y_pred']:,.2f}",
                    delta=f"{((fc['y_pred'] - fc['y_origin']) / fc['y_origin'] * 100):+.2f}%",
                )
                st.caption(f"80% Band: [{fc['q80_lower']:,.2f}, {fc['q80_upper']:,.2f}]")
                st.caption(f"90% Band: [{fc['q90_lower']:,.2f}, {fc['q90_upper']:,.2f}]")

        # Visualization of Forecast with Bands
        fig, ax = plt.subplots(figsize=(10, 4.5))
        horizons = [f["horizon"] for f in fcs]
        targets = [f["target_month"] for f in fcs]
        preds = [f["y_pred"] for f in fcs]
        q80_low = [f["q80_lower"] for f in fcs]
        q80_high = [f["q80_upper"] for f in fcs]
        q90_low = [f["q90_lower"] for f in fcs]
        q90_high = [f["q90_upper"] for f in fcs]

        # Plot origin point
        origin_val = fcs[0]["y_origin"]
        origin_date = fcs[0]["origin_month"]
        plot_dates = [origin_date] + targets
        plot_preds = [origin_val] + preds

        ax.fill_between(
            targets, q90_low, q90_high, color="orange", alpha=0.2, label="90% Conformal Band"
        )
        ax.fill_between(
            targets, q80_low, q80_high, color="teal", alpha=0.3, label="80% Conformal Band"
        )
        ax.plot(
            plot_dates, plot_preds, marker="o", color="navy", lw=2, label="Champion Forecast Path"
        )
        ax.axvline(origin_date, color="grey", linestyle="--", label="Forecast Origin")

        ax.set_title(f"Rolling Forecast with Adaptive Conformal Bands ({selected_series})")
        ax.set_ylabel("Price / Index Value")
        ax.grid(True, linestyle=":", alpha=0.6)
        ax.legend(loc="upper left")
        st.pyplot(fig)
        plt.close(fig)
    else:
        st.info("No forecast rows found for this series.")

with tab_eval:
    st.subheader("Backtest: Validation & Holdout")
    st.caption(
        "BACKTEST. Rolling-origin forecasts on historical data. The holdout (24 origins) was "
        "scored once behind Checkpoint Gate G4. These are not live forecasts."
    )

    champion = load_champions().get(selected_series, "")
    bt = load_backtest_intervals()
    s_bt = bt[bt["series_id"] == selected_series] if not bt.empty else bt

    if not s_bt.empty:
        horizon = st.selectbox("Horizon (months ahead)", sorted(s_bt["horizon"].unique()))
        h_bt = s_bt[s_bt["horizon"] == horizon].sort_values("target")
        method = h_bt["interval_method"].iloc[0]
        band = h_bt[h_bt["nominal_level"] == 0.8]
        dates = pd.to_datetime(band["target"])
        holdout_start = pd.to_datetime(h_bt.loc[h_bt["split"] == "holdout", "target"]).min()

        # Forecast versus actual
        st.markdown(f"### Forecast versus actual (champion {champion}, h={horizon})")
        fig, ax = plt.subplots(figsize=(10, 4))
        ax.fill_between(
            dates,
            band["lower_bound"],
            band["upper_bound"],
            color="teal",
            alpha=0.25,
            label=f"80% band ({method})",
        )
        ax.plot(dates, band["actual"], color="black", lw=1.5, label="Actual")
        ax.plot(dates, band["prediction"], color="navy", lw=1.5, linestyle="--", label="Forecast")
        if pd.notna(holdout_start):
            ax.axvline(holdout_start, color="grey", linestyle=":", label="Holdout starts")
        ax.set_ylabel("Price / Index Value")
        ax.grid(True, linestyle=":", alpha=0.6)
        ax.legend(loc="upper left")
        st.pyplot(fig)
        plt.close(fig)

        # Coverage over time
        st.markdown(f"### Interval coverage over time (rolling {ROLLING_ORIGINS} origins)")
        fig, ax = plt.subplots(figsize=(10, 3.5))
        for level, color in [(0.8, "teal"), (0.9, "darkorange")]:
            lvl = h_bt[h_bt["nominal_level"] == level]
            rolling = lvl["hit"].astype(float).rolling(ROLLING_ORIGINS).mean()
            ax.plot(pd.to_datetime(lvl["target"]), rolling, color=color, label=f"{level:.0%} band")
            ax.axhline(level, color=color, linestyle="--", lw=1, alpha=0.7)
        if pd.notna(holdout_start):
            ax.axvline(holdout_start, color="grey", linestyle=":", label="Holdout starts")
        ax.set_ylim(0, 1.05)
        ax.set_ylabel("Share of actuals inside band")
        ax.grid(True, linestyle=":", alpha=0.6)
        ax.legend(loc="lower left")
        st.pyplot(fig)
        plt.close(fig)
        st.caption("Dashed lines are the nominal levels. Coverage is empirical, not guaranteed.")
    else:
        st.info("No backtest interval files found. Run `palmguard select` and `palmguard holdout`.")

    # Error by horizon
    metrics = pd.concat(
        [load_csv("validation_metrics.csv"), load_csv("holdout_metrics.csv")], ignore_index=True
    )
    if not metrics.empty and champion:
        champ_m = metrics[
            (metrics["series_id"] == selected_series)
            & (metrics["model"] == champion)
            & (metrics["horizon"].astype(str) != "pooled")
        ]
        if not champ_m.empty:
            st.markdown(f"### Error by horizon (champion {champion})")
            pivot = champ_m.assign(horizon=champ_m["horizon"].astype(int)).pivot(
                index="horizon", columns="split", values="mase"
            )
            fig, ax = plt.subplots(figsize=(6, 3.5))
            pivot.plot(kind="bar", ax=ax, color=["navy", "teal"][: len(pivot.columns)], rot=0)
            ax.axhline(1.0, color="grey", linestyle="--", lw=1)
            ax.set_xlabel("Horizon (months ahead)")
            ax.set_ylabel("MASE")
            ax.grid(True, axis="y", linestyle=":", alpha=0.6)
            st.pyplot(fig)
            plt.close(fig)

    h_df = load_csv("holdout_metrics.csv")
    if not h_df.empty:
        st.markdown("### Holdout metrics, all candidates")
        s_hdf = h_df[h_df["series_id"] == selected_series]
        show_cols = [
            c
            for c in ["model", "horizon", "mase", "wape", "rmse", "mae", "bias", "fit_failures"]
            if c in s_hdf.columns
        ]
        st.dataframe(s_hdf[show_cols], use_container_width=True)

        st.markdown("### Key Scientific Finding")
        if selected_series == "palm_wb_myr":
            st.info(
                "**Palm Oil Commodity Price**: Spot prices behave as a near-martingale. "
                "Naive baseline (B1) won champion status on validation and holds robust performance on holdout. "
                "More complex tree and exogenous models showed overfitting on small monthly macro samples."
            )
        else:
            st.info(
                "**PPI Oils & Fats Index**: Exponential Smoothing (B3 ETS) won on validation. "
                "On the holdout it only narrowly beat the naive forecast."
            )

    st.divider()
    st.subheader("Live: Published Forecasts Scored Against Actuals")
    st.caption(
        "LIVE. Forecasts issued by the scheduled pipeline, scored once the actual is published."
    )
    live = history_df
    if not live.empty and "series_id" in live.columns:
        live = live[live["series_id"] == selected_series]
    if not live.empty and "y_actual" in live.columns:
        live_cols = [
            c
            for c in [
                "origin_month",
                "target_month",
                "horizon",
                "y_pred",
                "y_actual",
                "abs_pct_error",
                "mase",
                "interval_hit_80",
                "interval_hit_90",
            ]
            if c in live.columns
        ]
        st.dataframe(live[live_cols], use_container_width=True)
    else:
        st.info(
            "No live forecast has been scored yet. The first scores appear after the next "
            "monthly actuals are published."
        )

with tab_drift:
    st.subheader("Feature Drift & Monitoring (PSI / KS Test)")
    s_mon = monitoring_data.get(selected_series, {})
    drift_dict = s_mon.get("drift_summary", {})

    if drift_dict:
        drift_rows = []
        for feat, dres in drift_dict.items():
            drift_rows.append(
                {
                    "Feature": feat,
                    "PSI": dres["psi"],
                    "PSI Alert (>=0.25)": "⚠️ DRIFT" if dres["psi_drift_flag"] else "OK",
                    "KS Stat": dres["ks_statistic"],
                    "KS p-value": dres["ks_pvalue"],
                    "KS Alert (p<0.05)": "⚠️ DRIFT" if dres["ks_drift_flag"] else "OK",
                    "Historical Mean": dres["ref_mean"],
                    "Recent Mean (24m)": dres["recent_mean"],
                }
            )
        st.dataframe(pd.DataFrame(drift_rows), use_container_width=True)
    else:
        st.write("No drift statistics currently logged.")

with tab_sources:
    st.subheader("Data Licensing & Mandatory Attributions")
    st.markdown("""
    PalmGuard exclusively consumes **CC BY 4.0** open-data sources:
    - **World Bank Commodity Price Data (The Pink Sheet)**: `https://www.worldbank.org/en/research/commodity-markets`
    - **Bank Negara Malaysia (BNM)** Daily USD/MYR middle exchange rates: `https://data.gov.my`
    - **Department of Statistics Malaysia (DOSM)** Producer Price Index (PPI SITC 4) & Trade Statistics: `https://data.gov.my`

    **Benchmark Specifications**:
    - Palm Oil series is predominantly refined (RBD) Malaysian palm oil FOB export price, converted to RM/mt using BNM trading-day averages.
    - **Not an MPOB price**: This project does not use or claim to use copyright-reserved MPOB physical delivered CPO prices.
    """)
