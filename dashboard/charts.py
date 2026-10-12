"""Altair charts for the PalmGuard dashboard.

One visual system for every chart: blue = actual, orange = forecast, a pale blue wash for
prediction ranges, hairline solid grid, text in ink colours only.
"""

from __future__ import annotations

import altair as alt
import pandas as pd

BLUE = "#2a78d6"
ORANGE = "#eb6834"
INK = "#0b0b0b"
INK_MUTED = "#52514e"
GRID = "#e6e5e0"
FONT = '"Source Sans", "Source Sans Pro", "Segoe UI", sans-serif'
CHART_HEIGHT = 400


def _style(chart: alt.LayerChart | alt.Chart, height: int = CHART_HEIGHT) -> alt.LayerChart:
    return (
        chart.properties(height=height, background="transparent")
        .configure(font=FONT)
        .configure_view(stroke=None)
        .configure_axis(
            labelFontSize=15,
            titleFontSize=15,
            titleFontWeight="normal",
            labelColor=INK_MUTED,
            titleColor=INK_MUTED,
            gridColor=GRID,
            domainColor=GRID,
            tickColor=GRID,
            labelPadding=6,
            titlePadding=10,
        )
        .configure_legend(
            labelFontSize=15,
            titleFontSize=15,
            labelColor=INK,
            orient="top",
            direction="horizontal",
            title=None,
            symbolStrokeWidth=3,
        )
    )


def _series_scale(domain: list[str]) -> alt.Scale:
    return alt.Scale(domain=domain, range=[BLUE, ORANGE][: len(domain)])


def _holdout_marker(holdout_start: pd.Timestamp | None) -> list[alt.Chart]:
    if holdout_start is None or pd.isna(holdout_start):
        return []
    marker = pd.DataFrame({"date": [holdout_start], "label": ["Holdout starts"]})
    rule = alt.Chart(marker).mark_rule(color=INK_MUTED, strokeWidth=1).encode(x="date:T")
    text = (
        alt.Chart(marker)
        .mark_text(align="left", dx=6, dy=-4, baseline="top", fontSize=13, color=INK_MUTED)
        .encode(x="date:T", y=alt.value(0), text="label:N")
    )
    return [rule, text]


def forecast_chart(
    history: pd.DataFrame, forecasts: list[dict], unit_label: str, value_format: str
) -> alt.LayerChart:
    """Recent actuals, the published forecast path and its 80% / 90% ranges."""
    origin_date = pd.to_datetime(forecasts[0]["origin_month"])
    origin_value = forecasts[0]["y_origin"]

    path = pd.DataFrame(
        [
            {
                "date": origin_date,
                "value": origin_value,
                "q80_lower": origin_value,
                "q80_upper": origin_value,
                "q90_lower": origin_value,
                "q90_upper": origin_value,
            }
        ]
        + [
            {
                "date": pd.to_datetime(f["target_month"]),
                "value": f["y_pred"],
                "q80_lower": f["q80_lower"],
                "q80_upper": f["q80_upper"],
                "q90_lower": f["q90_lower"],
                "q90_upper": f["q90_upper"],
            }
            for f in forecasts
        ]
    )
    path["series"] = "Forecast"
    actual = history.assign(series="Actual")

    x = alt.X("date:T", title=None, axis=alt.Axis(format="%b %Y", tickCount=8))
    y = alt.Y(
        "value:Q", title=unit_label, scale=alt.Scale(zero=False), axis=alt.Axis(format=value_format)
    )
    color = alt.Color("series:N", scale=_series_scale(["Actual", "Forecast"]))

    band90 = (
        alt.Chart(path)
        .mark_area(color=ORANGE, opacity=0.10)
        .encode(
            x=x,
            y=alt.Y(
                "q90_lower:Q",
                title=unit_label,
                scale=alt.Scale(zero=False),
                axis=alt.Axis(format=value_format),
            ),
            y2="q90_upper:Q",
        )
    )
    band80 = (
        alt.Chart(path)
        .mark_area(color=ORANGE, opacity=0.16)
        .encode(x=x, y="q80_lower:Q", y2="q80_upper:Q")
    )
    actual_line = (
        alt.Chart(actual)
        .mark_line(strokeWidth=2, strokeJoin="round", strokeCap="round")
        .encode(x=x, y=y, color=color)
    )
    forecast_line = (
        alt.Chart(path)
        .mark_line(
            strokeWidth=2,
            point=alt.OverlayMarkDef(size=70, filled=True, stroke="#f9f9f7", strokeWidth=2),
        )
        .encode(
            x=x,
            y=y,
            color=color,
            tooltip=[
                alt.Tooltip("date:T", title="Month", format="%B %Y"),
                alt.Tooltip("value:Q", title="Forecast", format=value_format),
                alt.Tooltip("q80_lower:Q", title="80% low", format=value_format),
                alt.Tooltip("q80_upper:Q", title="80% high", format=value_format),
                alt.Tooltip("q90_lower:Q", title="90% low", format=value_format),
                alt.Tooltip("q90_upper:Q", title="90% high", format=value_format),
            ],
        )
    )
    actual_hover = (
        alt.Chart(actual)
        .mark_point(size=120, opacity=0)
        .encode(
            x=x,
            y=y,
            tooltip=[
                alt.Tooltip("date:T", title="Month", format="%B %Y"),
                alt.Tooltip("value:Q", title="Actual", format=value_format),
            ],
        )
    )
    return _style(band90 + band80 + actual_line + forecast_line + actual_hover)


def backtest_chart(band: pd.DataFrame, unit_label: str, value_format: str) -> alt.LayerChart:
    """Backtest forecast versus actual with the 80% range, validation then holdout."""
    df = band.assign(date=pd.to_datetime(band["target"]))
    holdout_start = df.loc[df["split"] == "holdout", "date"].min()
    long = df.melt(
        id_vars=["date", "lower_bound", "upper_bound"],
        value_vars=["actual", "prediction"],
        var_name="series",
        value_name="value",
    )
    long["series"] = long["series"].map({"actual": "Actual", "prediction": "Forecast"})

    x = alt.X("date:T", title=None, axis=alt.Axis(format="%Y", tickCount=8))
    y = alt.Y(
        "value:Q", title=unit_label, scale=alt.Scale(zero=False), axis=alt.Axis(format=value_format)
    )

    range_area = (
        alt.Chart(df)
        .mark_area(color=ORANGE, opacity=0.14)
        .encode(
            x=x,
            y=alt.Y(
                "lower_bound:Q",
                title=unit_label,
                scale=alt.Scale(zero=False),
                axis=alt.Axis(format=value_format),
            ),
            y2="upper_bound:Q",
        )
    )
    lines = (
        alt.Chart(long)
        .mark_line(strokeWidth=2, strokeJoin="round")
        .encode(x=x, y=y, color=alt.Color("series:N", scale=_series_scale(["Actual", "Forecast"])))
    )
    hover = (
        alt.Chart(df)
        .mark_point(size=120, opacity=0)
        .encode(
            x=x,
            y=alt.Y("actual:Q"),
            tooltip=[
                alt.Tooltip("date:T", title="Month", format="%B %Y"),
                alt.Tooltip("actual:Q", title="Actual", format=value_format),
                alt.Tooltip("prediction:Q", title="Forecast", format=value_format),
                alt.Tooltip("lower_bound:Q", title="80% low", format=value_format),
                alt.Tooltip("upper_bound:Q", title="80% high", format=value_format),
            ],
        )
    )
    return _style(alt.layer(range_area, lines, hover, *_holdout_marker(holdout_start)))


def coverage_chart(intervals: pd.DataFrame, window: int) -> alt.LayerChart:
    """Rolling share of actuals that landed inside the 80% and 90% ranges."""
    frames = []
    for level, name in [(0.8, "80% range"), (0.9, "90% range")]:
        lvl = intervals[intervals["nominal_level"] == level].sort_values("target")
        frames.append(
            pd.DataFrame(
                {
                    "date": pd.to_datetime(lvl["target"]),
                    "coverage": lvl["hit"].astype(float).rolling(window).mean(),
                    "series": name,
                    "target_level": level,
                }
            )
        )
    df = pd.concat(frames, ignore_index=True).dropna(subset=["coverage"])
    holdout_rows = intervals[intervals["split"] == "holdout"]
    holdout_start = pd.to_datetime(holdout_rows["target"]).min() if len(holdout_rows) else None

    color = alt.Color("series:N", scale=_series_scale(["80% range", "90% range"]))
    x = alt.X("date:T", title=None, axis=alt.Axis(format="%Y", tickCount=8))
    line = (
        alt.Chart(df)
        .mark_line(strokeWidth=2, strokeJoin="round")
        .encode(
            x=x,
            y=alt.Y(
                "coverage:Q",
                title="Share of actuals inside the range",
                scale=alt.Scale(domain=[0.4, 1.0]),
                axis=alt.Axis(format="%"),
            ),
            color=color,
        )
    )
    hover = (
        alt.Chart(df)
        .mark_point(size=120, opacity=0)
        .encode(
            x=x,
            y="coverage:Q",
            tooltip=[
                alt.Tooltip("date:T", title="Month", format="%B %Y"),
                alt.Tooltip("series:N", title="Range"),
                alt.Tooltip("coverage:Q", title="Coverage", format=".0%"),
                alt.Tooltip("target_level:Q", title="Target", format=".0%"),
            ],
        )
    )
    targets = pd.DataFrame({"level": [0.8, 0.9], "series": ["80% range", "90% range"]})
    target_rules = (
        alt.Chart(targets)
        .mark_rule(strokeWidth=1, opacity=0.6)
        .encode(y=alt.Y("level:Q", scale=alt.Scale(domain=[0.4, 1.0])), color=color)
    )
    return _style(
        alt.layer(target_rules, line, hover, *_holdout_marker(holdout_start)),
        height=300,
    )


def error_by_horizon_chart(metrics: pd.DataFrame) -> alt.LayerChart:
    """Champion error by horizon, validation beside holdout."""
    df = metrics.assign(
        horizon_label=metrics["horizon"].astype(int).astype(str) + " mo ahead",
        period=metrics["split"].str.capitalize(),
        error_pct=metrics["wape"],
    )
    bars = (
        alt.Chart(df)
        .mark_bar(size=24, cornerRadiusEnd=4)
        .encode(
            x=alt.X(
                "horizon_label:N",
                title=None,
                axis=alt.Axis(labelAngle=0),
                scale=alt.Scale(paddingInner=0.6, paddingOuter=0.3),
            ),
            xOffset=alt.XOffset("period:N", sort=["Validation", "Holdout"]),
            y=alt.Y("error_pct:Q", title="Average error", axis=alt.Axis(format=".0%")),
            color=alt.Color("period:N", scale=_series_scale(["Validation", "Holdout"])),
            tooltip=[
                alt.Tooltip("horizon_label:N", title="Horizon"),
                alt.Tooltip("period:N", title="Period"),
                alt.Tooltip("error_pct:Q", title="Average error (WAPE)", format=".1%"),
                alt.Tooltip("mase:Q", title="MASE", format=".2f"),
                alt.Tooltip("n_eval:Q", title="Forecasts scored"),
            ],
        )
    )
    labels = (
        alt.Chart(df)
        .mark_text(dy=-8, fontSize=13, color=INK)
        .encode(
            x=alt.X("horizon_label:N"),
            xOffset=alt.XOffset("period:N", sort=["Validation", "Holdout"]),
            y="error_pct:Q",
            text=alt.Text("error_pct:Q", format=".1%"),
        )
    )
    return _style(bars + labels, height=300)
