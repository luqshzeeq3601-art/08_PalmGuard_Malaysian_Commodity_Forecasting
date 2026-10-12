"""PalmGuard Streamlit Dashboard (Task T22).

Light, desktop-first interface for the published palm oil and oils/fats PPI forecasts:
the current forecast with its ranges, backtest and live accuracy, data health, and sources.
"""

from __future__ import annotations

import json
from pathlib import Path

import charts
import pandas as pd
import streamlit as st

st.set_page_config(
    page_title="PalmGuard | Malaysian Commodity Forecasting",
    page_icon="🌴",
    layout="wide",
    initial_sidebar_state="collapsed",
)

PUBLISHED_DIR = Path("reports/published")
REPORTS_DIR = Path("reports")
ARTIFACTS_DIR = Path("artifacts/champion")
ROLLING_ORIGINS = 12
HISTORY_MONTHS = 36

SERIES = {
    "palm_wb_myr": {
        "label": "Palm oil price",
        "long": "Malaysian palm oil price (World Bank Pink Sheet, RM per tonne)",
        "unit": "RM per tonne",
        "fmt": "RM {:,.0f}",
        "d3": ",.0f",
    },
    "ppi_oilsfats_my": {
        "label": "Oils & fats producer price index",
        "long": "DOSM Producer Price Index, oils and fats (2010 = 100)",
        "unit": "Index (2010 = 100)",
        "fmt": "{:,.1f}",
        "d3": ",.1f",
    },
}
MODEL_NAMES = {
    "B1": "Naive (last value carried forward)",
    "B2": "Seasonal naive (same month last year)",
    "B3": "Exponential smoothing (ETS)",
    "B4": "ARIMA",
    "M1": "LightGBM, own history",
    "M2": "LightGBM with market drivers",
}
INTERVAL_NAMES = {"C1": "rolling conformal", "C2": "adaptive conformal"}

# Page width tuned for 1920px screens: wide enough for charts, short enough to read.
st.markdown(
    """
    <style>
      .block-container {max-width: 1480px; padding-top: 2.5rem; padding-bottom: 3rem;}
      [data-testid="stMetricValue"] {font-size: 2rem;}
      [data-testid="stCaptionContainer"] {font-size: 0.9rem;}
      [data-testid="stTab"] p {font-size: 1.05rem;}
    </style>
    """,
    unsafe_allow_html=True,
)


def load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_csv(name: str) -> pd.DataFrame:
    path = REPORTS_DIR / name
    return pd.read_csv(path) if path.exists() else pd.DataFrame()


def load_history() -> pd.DataFrame:
    hpath = PUBLISHED_DIR / "history.parquet"
    return pd.read_parquet(hpath) if hpath.exists() else pd.DataFrame()


def load_backtest_intervals() -> pd.DataFrame:
    """Per-forecast backtest intervals of the selected method, validation then holdout."""
    frames = [load_csv("validation_intervals.csv"), load_csv("holdout_intervals.csv")]
    frames = [f for f in frames if not f.empty]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def month_label(value: str) -> str:
    return pd.to_datetime(value).strftime("%b %Y")


def render_forecast_tab(
    series_id: str, forecasts: list[dict], backtest: pd.DataFrame, published: str
) -> None:
    meta = SERIES[series_id]
    fmt = meta["fmt"]
    if not forecasts:
        st.info("No forecast has been published for this series yet.")
        return

    first = forecasts[0]
    st.subheader(f"Forecast for the next {len(forecasts)} months")
    st.markdown(
        f"Latest actual: **{fmt.format(first['y_origin'])}** in {month_label(first['origin_month'])}. "
        f"Next month ({month_label(first['target_month'])}) is forecast at "
        f"**{fmt.format(first['y_pred'])}**, with an 80% chance of landing between "
        f"{fmt.format(first['q80_lower'])} and {fmt.format(first['q80_upper'])}."
    )

    for col, fc in zip(st.columns(len(forecasts)), forecasts):
        change = (fc["y_pred"] - fc["y_origin"]) / fc["y_origin"] * 100
        with col:
            st.metric(
                label=f"{month_label(fc['target_month'])} · {fc['horizon']} month"
                f"{'s' if fc['horizon'] > 1 else ''} ahead",
                value=fmt.format(fc["y_pred"]),
                delta="No change vs latest actual"
                if abs(change) < 0.05
                else f"{change:+.1f}% vs latest actual",
                delta_color="off",
                delta_arrow="off" if abs(change) < 0.05 else "auto",
                border=True,
            )
            st.caption(
                f"80% range: {fmt.format(fc['q80_lower'])} to {fmt.format(fc['q80_upper'])}  \n"
                f"90% range: {fmt.format(fc['q90_lower'])} to {fmt.format(fc['q90_upper'])}"
            )

    history = pd.DataFrame(columns=["date", "value"])
    if not backtest.empty:
        h1 = backtest[(backtest["horizon"] == 1) & (backtest["nominal_level"] == 0.8)]
        history = (
            pd.DataFrame({"date": pd.to_datetime(h1["target"]), "value": h1["actual"]})
            .drop_duplicates("date")
            .sort_values("date")
            .tail(HISTORY_MONTHS)
        )
    origin_point = pd.DataFrame(
        {"date": [pd.to_datetime(first["origin_month"])], "value": [first["y_origin"]]}
    )
    history = pd.concat([history, origin_point]).drop_duplicates("date").sort_values("date")

    st.markdown("#### Recent history and forecast")
    st.altair_chart(
        charts.forecast_chart(history, forecasts, meta["unit"], meta["d3"]),
        width="stretch",
        theme=None,
    )
    st.caption(
        "Shaded areas are the 80% range (darker) and 90% range (lighter). "
        "A forecast that repeats the latest value means no model beat that simple rule in testing."
    )

    with st.expander("Show forecast as a table"):
        table = pd.DataFrame(forecasts)[
            [
                "target_month",
                "horizon",
                "y_pred",
                "q80_lower",
                "q80_upper",
                "q90_lower",
                "q90_upper",
            ]
        ].rename(
            columns={
                "target_month": "Month",
                "horizon": "Months ahead",
                "y_pred": "Forecast",
                "q80_lower": "80% low",
                "q80_upper": "80% high",
                "q90_lower": "90% low",
                "q90_upper": "90% high",
            }
        )
        st.dataframe(table, hide_index=True, width="stretch")
    if published:
        st.caption(f"Published {pd.to_datetime(published).strftime('%d %b %Y, %H:%M UTC')}.")


def render_accuracy_tab(
    series_id: str, champion: str, backtest: pd.DataFrame, history_df: pd.DataFrame
) -> None:
    meta = SERIES[series_id]
    st.subheader("How accurate has it been?")
    st.info(
        "**Backtest.** These results replay the model on past data it had not seen. "
        "The final 24 months (the holdout) were scored once and never used for tuning. "
        "They are not live forecasts.",
        icon=":material/history:",
    )

    val_m, hold_m = load_csv("validation_metrics.csv"), load_csv("holdout_metrics.csv")
    metrics = pd.concat([val_m, hold_m], ignore_index=True)
    champ_m = pd.DataFrame()
    if not metrics.empty and champion:
        champ_m = metrics[
            (metrics["series_id"] == series_id)
            & (metrics["model"] == champion)
            & (metrics["horizon"].astype(str) != "pooled")
        ]
    hold_cov = load_csv("holdout_coverage.csv")
    if not hold_cov.empty:
        hold_cov = hold_cov[(hold_cov["series_id"] == series_id) & hold_cov["selected"]]

    k1, k2, k3 = st.columns(3)
    h1 = champ_m[(champ_m["split"] == "holdout") & (champ_m["horizon"].astype(str) == "1")]
    k1.metric(
        "Average error, 1 month ahead",
        f"{h1['wape'].iloc[0]:.1%}" if not h1.empty else "n/a",
        help="Holdout WAPE: total absolute error divided by total actual value.",
        border=True,
    )
    cov80 = hold_cov[(hold_cov["horizon"] == 1) & (hold_cov["nominal_level"] == 0.8)]
    k2.metric(
        "Actuals inside the 80% range",
        f"{cov80['coverage'].iloc[0]:.0%}" if not cov80.empty else "n/a",
        help="Holdout, 1 month ahead. A well-calibrated 80% range should be close to 80%.",
        border=True,
    )
    k3.metric(
        "Model in use",
        champion or "n/a",
        help=MODEL_NAMES.get(champion, ""),
        border=True,
    )
    if champion:
        st.caption(f"{champion} = {MODEL_NAMES.get(champion, champion)}.")

    s_bt = backtest[backtest["series_id"] == series_id] if not backtest.empty else backtest
    if s_bt.empty:
        st.warning("Backtest files are missing. Run `palmguard select` and `palmguard holdout`.")
    else:
        horizon = st.segmented_control(
            "Forecast horizon",
            options=sorted(int(h) for h in s_bt["horizon"].unique()),
            format_func=lambda h: f"{h} month{'s' if h > 1 else ''} ahead",
            default=1,
            key=f"horizon_{series_id}",
        )
        h_bt = s_bt[s_bt["horizon"] == (horizon or 1)]
        method = INTERVAL_NAMES.get(h_bt["interval_method"].iloc[0], "conformal")

        st.markdown("#### Forecast versus what actually happened")
        st.altair_chart(
            charts.backtest_chart(h_bt[h_bt["nominal_level"] == 0.8], meta["unit"], meta["d3"]),
            width="stretch",
            theme=None,
        )
        st.caption(f"Shaded area is the 80% range ({method} intervals).")

        left, right = st.columns([3, 2], gap="large")
        with left:
            st.markdown("#### Did the ranges hold up over time?")
            st.altair_chart(
                charts.coverage_chart(h_bt, ROLLING_ORIGINS), width="stretch", theme=None
            )
            st.caption(
                f"Rolling share over the last {ROLLING_ORIGINS} forecasts. The thin horizontal lines "
                "are the 80% and 90% targets: above target means the range was wider than "
                "needed, below means it was too narrow."
            )
        with right:
            st.markdown("#### Error grows with the horizon")
            if champ_m.empty:
                st.info("No metrics found for the model in use.")
            else:
                st.altair_chart(charts.error_by_horizon_chart(champ_m), width="stretch", theme=None)
                st.caption("Average error as a share of the actual value (WAPE).")

    if not hold_m.empty:
        with st.expander("Compare all candidate models on the holdout"):
            table = hold_m[hold_m["series_id"] == series_id].assign(
                model=lambda d: d["model"] + " · " + d["model"].map(MODEL_NAMES)
            )
            st.dataframe(
                table[["model", "horizon", "n_eval", "wape", "mase", "mae", "rmse", "bias"]],
                hide_index=True,
                width="stretch",
                column_config={
                    "model": "Model",
                    "horizon": "Months ahead",
                    "n_eval": "Forecasts scored",
                    "wape": st.column_config.NumberColumn("Average error (WAPE)", format="percent"),
                    "mase": st.column_config.NumberColumn("MASE", format="%.2f"),
                    "mae": st.column_config.NumberColumn("MAE", format="%.2f"),
                    "rmse": st.column_config.NumberColumn("RMSE", format="%.2f"),
                    "bias": st.column_config.NumberColumn("Bias", format="%.2f"),
                },
            )

    st.divider()
    st.subheader("Live track record")
    live = history_df
    if not live.empty and "series_id" in live.columns:
        live = live[live["series_id"] == series_id]
    if not live.empty and "y_actual" in live.columns:
        st.caption(
            "Forecasts issued by the monthly pipeline, scored once the actual was published."
        )
        cols = [
            c
            for c in [
                "origin_month",
                "target_month",
                "horizon",
                "y_pred",
                "y_actual",
                "abs_pct_error",
                "interval_hit_80",
                "interval_hit_90",
            ]
            if c in live.columns
        ]
        st.dataframe(live[cols], hide_index=True, width="stretch")
    else:
        st.info(
            "No live forecast has been scored yet. The first result appears after next month's "
            "actual figures are published.",
            icon=":material/schedule:",
        )


def render_health_tab(series_id: str, monitoring: dict) -> None:
    st.subheader("Is recent data behaving like the past?")
    st.markdown(
        "Each input is compared over the last 24 months against its earlier history. "
        "A flag means the input has shifted, so forecasts deserve extra caution. "
        "It does not mean the forecast is wrong."
    )
    drift = monitoring.get(series_id, {}).get("drift_summary", {})
    if not drift:
        st.info("No data health statistics have been published yet.")
        return

    rows = pd.DataFrame(
        [
            {
                "Input": name,
                "Status": "Shifted" if d["overall_drift_flag"] else "Stable",
                "PSI": d["psi"],
                "KS p-value": d["ks_pvalue"],
                "Earlier average": d["ref_mean"],
                "Recent average": d["recent_mean"],
            }
            for name, d in drift.items()
        ]
    ).sort_values(["Status", "PSI"], ascending=[True, False])
    shifted = int((rows["Status"] == "Shifted").sum())

    c1, c2 = st.columns([1, 3])
    c1.metric("Inputs flagged as shifted", f"{shifted} of {len(rows)}", border=True)
    with c2:
        if shifted:
            st.warning(
                f"{shifted} input{'s have' if shifted > 1 else ' has'} shifted compared with history.",
                icon=":material/warning:",
            )
        else:
            st.success("All inputs look consistent with history.", icon=":material/check_circle:")

    st.dataframe(
        rows,
        hide_index=True,
        width="stretch",
        column_config={
            "PSI": st.column_config.NumberColumn(
                "PSI", format="%.3f", help="Population Stability Index. 0.25 or more is flagged."
            ),
            "KS p-value": st.column_config.NumberColumn(
                "KS p-value", format="%.3f", help="Kolmogorov-Smirnov test. Below 0.05 is flagged."
            ),
            "Earlier average": st.column_config.NumberColumn(format="%.4f"),
            "Recent average": st.column_config.NumberColumn(format="%.4f"),
        },
    )


def render_about_tab() -> None:
    left, right = st.columns(2, gap="large")
    with left:
        st.subheader("What is being forecast")
        st.markdown(
            """
- **Palm oil price**: the World Bank Pink Sheet palm oil benchmark, converted from US dollars
  to ringgit with the monthly average Bank Negara Malaysia rate. It is mostly refined (RBD)
  Malaysian palm oil and its delivery basis has changed over time.
- **Oils & fats producer price index**: DOSM Producer Price Index, SITC section 4
  (2010 = 100).

**This is not the MPOB crude palm oil price.** MPOB prices are copyright-reserved and are
not used here.
"""
        )
        st.subheader("How to read the ranges")
        st.markdown(
            "An 80% range is built so that about 8 in 10 actual values fall inside it, judged on "
            "past forecast errors. Past coverage is measured, not guaranteed."
        )
    with right:
        st.subheader("Data sources")
        st.markdown(
            """
All sources are open data under **CC BY 4.0**:

- [World Bank Commodity Price Data (Pink Sheet)](https://www.worldbank.org/en/research/commodity-markets)
- Bank Negara Malaysia daily USD/MYR rates, via [data.gov.my](https://data.gov.my)
- Department of Statistics Malaysia producer prices and trade, via [data.gov.my](https://data.gov.my)

Values are transformed: monthly averages, currency conversion and monthly returns.
"""
        )
        st.subheader("Models compared")
        st.markdown("\n".join(f"- **{k}**: {v}" for k, v in MODEL_NAMES.items()))


# ---- Page ------------------------------------------------------------------------
st.title("PalmGuard")
st.markdown(
    "Monthly forecasts for Malaysian palm oil prices, one to three months ahead, "
    "with a measured range of uncertainty."
)
st.warning(
    "**Notice & Disclaimer:** PalmGuard is a forecasting demonstrator. It is not trading, "
    "investment or procurement advice. No financial benefit was measured, and the accuracy of "
    "the ranges on past data is not guaranteed for the future.",
    icon=":material/info:",
)

forecast_data = load_json(PUBLISHED_DIR / "forecast.json")
if not forecast_data:
    st.error("No published forecast found. Run `palmguard pipeline run` first.")
    st.stop()

monitoring_data = load_json(PUBLISHED_DIR / "monitoring.json")
champions = load_json(ARTIFACTS_DIR / "metadata.json").get("selected_champions", {})
history_df = load_history()
backtest_df = load_backtest_intervals()

selected_series = st.segmented_control(
    "Series",
    options=list(SERIES),
    format_func=lambda s: SERIES[s]["label"],
    default="palm_wb_myr",
    label_visibility="collapsed",
)
selected_series = selected_series or "palm_wb_myr"
st.caption(SERIES[selected_series]["long"])

series_forecasts = sorted(
    (f for f in forecast_data.get("forecasts", []) if f.get("series_id") == selected_series),
    key=lambda f: f["horizon"],
)
series_backtest = (
    backtest_df[backtest_df["series_id"] == selected_series]
    if not backtest_df.empty
    else backtest_df
)

tab_forecast, tab_accuracy, tab_health, tab_about = st.tabs(
    ["Forecast", "Accuracy", "Data health", "About the data"]
)
with tab_forecast:
    render_forecast_tab(
        selected_series,
        series_forecasts,
        series_backtest,
        forecast_data.get("published_at_utc", ""),
    )
with tab_accuracy:
    render_accuracy_tab(
        selected_series, champions.get(selected_series, ""), backtest_df, history_df
    )
with tab_health:
    render_health_tab(selected_series, monitoring_data)
with tab_about:
    render_about_tab()
