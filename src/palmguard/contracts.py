"""Data contracts, revision tracking across snapshots, and Gate G1 data quality audit."""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, field_validator

from palmguard.config import ProjectConfig
from palmguard.ingest.datagovmy import (
    parse_exchangerates,
    parse_ppi_sitc,
    parse_sitc_lookup,
    parse_trade_sitc,
)
from palmguard.ingest.snapshots import (
    SnapshotManifest,
    SnapshotValidationError,
    append_revisions,
    diff_revisions,
    get_snapshot_dir,
    latest_snapshot,
    list_snapshots,
)
from palmguard.ingest.worldbank import parse_pink_sheet_xlsx

ALLOWED_SERIES_IDS = frozenset(
    {
        "palm_wb_usd",
        "palm_wb_myr",
        "ppi_oilsfats_my",
        "brent_wb_usd",
        "soyoil_wb_usd",
        "usdmyr_avg",
        "exports_sitc4",
    }
)

PANEL_REQUIRED_COLUMNS = (
    "series_id",
    "month",
    "value",
    "available_from",
    "snapshot_id",
    "is_provisional",
)

_MONTH_DATE_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])-01$")


class MonthlyPanelRow(BaseModel):
    """Pydantic row contract for canonical `monthly_panel` (03_DATA_SPEC.md section 4)."""

    model_config = ConfigDict(frozen=True)

    series_id: str
    month: str = Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])-01$")
    value: float = Field(gt=0.0)
    available_from: str = Field(min_length=10)
    snapshot_id: str = Field(min_length=1)
    is_provisional: bool = False

    @field_validator("series_id")
    @classmethod
    def _check_series_id(cls, v: str) -> str:
        if v not in ALLOWED_SERIES_IDS:
            raise ValueError(f"Unknown series_id: {v!r}")
        return v

    @field_validator("value")
    @classmethod
    def _check_finite(cls, v: float) -> float:
        if not np.isfinite(v):
            raise ValueError("value must be finite")
        return float(v)


class SeriesSummary(BaseModel):
    """Validated summary metrics for a canonical monthly series."""

    model_config = ConfigDict(frozen=True)

    series_id: str
    snapshot_id: str
    row_count: int
    start_month: str
    end_month: str
    min_value: float
    max_value: float
    is_contiguous: bool
    has_duplicates: bool
    has_nonpositive: bool


class DataQualityAudit(BaseModel):
    """Machine-readable output of Gate G1 (`reports/data_quality_audit.json`)."""

    model_config = ConfigDict(frozen=True)

    generated_at_utc: str
    gate_g1_passed: bool
    o1_passed: bool
    selected_primary_target: str
    selected_secondary_target: str
    palm_wb_myr_months: int
    ppi_oilsfats_my_months: int
    palm_ppi_return_correlation: float
    palm_ppi_overlap_months: int
    revisions_count: int
    series_summaries: dict[str, SeriesSummary]
    definition_breaks: list[dict[str, str]]
    reasons: list[str]


def check_monthly_continuity(months: Sequence[str]) -> tuple[bool, list[str]]:
    """Return `(is_contiguous, missing_months)` for a sequence of `YYYY-MM-01` strings."""
    if not months:
        return False, []
    ordered = sorted(set(months))
    start_y, start_m = int(ordered[0][:4]), int(ordered[0][5:7])
    end_y, end_m = int(ordered[-1][:4]), int(ordered[-1][5:7])

    expected: list[str] = []
    y, m = start_y, start_m
    while (y, m) <= (end_y, end_m):
        expected.append(f"{y:04d}-{m:02d}-01")
        if m == 12:
            y += 1
            m = 1
        else:
            m += 1

    observed_set = set(ordered)
    missing = [dt for dt in expected if dt not in observed_set]
    return len(missing) == 0, missing


def validate_monthly_series_df(
    df: pd.DataFrame,
    *,
    expected_series_id: str | None = None,
    min_rows: int = 1,
    require_contiguous: bool = True,
) -> SeriesSummary:
    """Validate a canonical monthly series DataFrame against 03_DATA_SPEC.md contracts."""
    if df.empty:
        raise SnapshotValidationError("Series DataFrame is empty")

    missing_cols = [c for c in PANEL_REQUIRED_COLUMNS if c not in df.columns]
    if missing_cols:
        raise SnapshotValidationError(f"Missing required panel columns: {missing_cols}")

    series_ids = df["series_id"].astype(str).unique().tolist()
    if len(series_ids) != 1:
        raise SnapshotValidationError(f"Expected single series_id, got {series_ids}")
    s_id = series_ids[0]
    if s_id not in ALLOWED_SERIES_IDS:
        raise SnapshotValidationError(f"Disallowed series_id: {s_id!r}")
    if expected_series_id is not None and s_id != expected_series_id:
        raise SnapshotValidationError(f"Expected series_id {expected_series_id!r}, got {s_id!r}")

    months = df["month"].astype(str).tolist()
    bad_months = [m for m in months if not _MONTH_DATE_RE.match(m)]
    if bad_months:
        raise SnapshotValidationError(
            f"Invalid month format in {s_id} (expected YYYY-MM-01): {bad_months[:3]}"
        )

    has_duplicates = bool(df["month"].duplicated().any())
    if has_duplicates:
        raise SnapshotValidationError(f"Duplicate months detected in {s_id}")

    vals = pd.to_numeric(df["value"], errors="coerce").to_numpy(dtype=float)
    if np.isnan(vals).any() or np.isinf(vals).any():
        raise SnapshotValidationError(f"NaN or infinite values detected in {s_id}")

    has_nonpositive = bool((vals <= 0.0).any())
    if has_nonpositive:
        raise SnapshotValidationError(f"Non-positive values detected in {s_id}")

    if (df["snapshot_id"].astype(str).str.strip() == "").any():
        raise SnapshotValidationError(f"Empty snapshot_id in {s_id}")

    is_contiguous, missing_months = check_monthly_continuity(months)
    if require_contiguous and not is_contiguous:
        raise SnapshotValidationError(
            f"Monthly series {s_id} has {len(missing_months)} gap(s), e.g. {missing_months[:3]}"
        )

    if len(df) < min_rows:
        raise SnapshotValidationError(
            f"Series {s_id} has {len(df)} rows, fewer than required min_rows={min_rows}"
        )

    ordered_months = sorted(months)
    snap_id = str(df["snapshot_id"].iloc[-1])
    return SeriesSummary(
        series_id=s_id,
        snapshot_id=snap_id,
        row_count=len(df),
        start_month=ordered_months[0],
        end_month=ordered_months[-1],
        min_value=float(np.min(vals)),
        max_value=float(np.max(vals)),
        is_contiguous=is_contiguous,
        has_duplicates=has_duplicates,
        has_nonpositive=has_nonpositive,
    )


def build_usdmyr_monthly_series(
    daily_exr_df: pd.DataFrame,
    *,
    snapshot_id: str,
    available_from: str,
) -> pd.DataFrame:
    """Compute monthly trading-day mean of BNM daily 1700 middle USD/MYR rate for complete months."""
    if daily_exr_df.empty:
        raise SnapshotValidationError("daily_exr_df is empty")

    work = daily_exr_df.copy()
    work["dt"] = pd.to_datetime(work["date"])
    max_dt = work["dt"].max()
    work["month"] = work["dt"].dt.strftime("%Y-%m-01")

    # If the trailing month in the daily feed ended before the 25th, it is an incomplete current month
    if max_dt.day < 25:
        trailing_month = max_dt.strftime("%Y-%m-01")
        work = work[work["month"] < trailing_month].copy()

    grouped = (
        work.groupby("month", as_index=False)["USD"]
        .mean()
        .sort_values("month")
        .reset_index(drop=True)
    )
    return pd.DataFrame(
        {
            "series_id": "usdmyr_avg",
            "month": grouped["month"].astype(str),
            "value": grouped["USD"].astype(float),
            "available_from": available_from,
            "snapshot_id": snapshot_id,
            "is_provisional": False,
        }
    )


def build_palm_myr_series(
    palm_usd_df: pd.DataFrame,
    usdmyr_df: pd.DataFrame,
) -> pd.DataFrame:
    """Construct `palm_wb_myr[m] = palm_wb_usd[m] * usdmyr_avg[m]` on overlapping complete months."""
    merged = palm_usd_df[["month", "value", "available_from", "snapshot_id"]].merge(
        usdmyr_df[["month", "value", "available_from", "snapshot_id"]],
        on="month",
        how="inner",
        suffixes=("_palm", "_fx"),
    )
    if merged.empty:
        raise SnapshotValidationError("No overlapping months between palm_wb_usd and usdmyr_avg")

    merged = merged.sort_values("month").reset_index(drop=True)
    avail = [
        max(str(a), str(b))
        for a, b in zip(merged["available_from_palm"], merged["available_from_fx"])
    ]
    snaps = [f"{a}+{b}" for a, b in zip(merged["snapshot_id_palm"], merged["snapshot_id_fx"])]
    return pd.DataFrame(
        {
            "series_id": "palm_wb_myr",
            "month": merged["month"].astype(str),
            "value": (merged["value_palm"] * merged["value_fx"]).astype(float),
            "available_from": avail,
            "snapshot_id": snaps,
            "is_provisional": False,
        }
    )


def _snapshot_payload_path(raw_root: Path, manifest: SnapshotManifest) -> Path:
    parts = manifest.snapshot_id.split(".")
    date_part = parts[2] if len(parts) >= 4 else manifest.retrieved_at_utc[:10]
    return (
        get_snapshot_dir(raw_root, manifest.source, manifest.dataset, date_part) / manifest.filename
    )


def _parse_snapshot_to_monthly_df(raw_root: Path, manifest: SnapshotManifest) -> pd.DataFrame:
    payload = _snapshot_payload_path(raw_root, manifest).read_bytes()
    avail = manifest.retrieved_at_utc[:10]
    if manifest.dataset == "pink_sheet":
        df, _ = parse_pink_sheet_xlsx(
            payload, snapshot_id=manifest.snapshot_id, available_from=avail
        )
        return df
    if manifest.dataset == "exchangerates_daily_1700":
        daily = parse_exchangerates(payload, manifest.filename)
        return build_usdmyr_monthly_series(
            daily, snapshot_id=manifest.snapshot_id, available_from=avail
        )
    if manifest.dataset == "ppi_sitc":
        return parse_ppi_sitc(
            payload,
            manifest.filename,
            snapshot_id=manifest.snapshot_id,
            available_from=avail,
        )
    if manifest.dataset == "trade_sitc_1d":
        return parse_trade_sitc(
            payload,
            manifest.filename,
            snapshot_id=manifest.snapshot_id,
            available_from=avail,
        )
    return pd.DataFrame()


def sync_revisions_from_snapshots(raw_root: Path, revisions_path: Path) -> pd.DataFrame:
    """Compare consecutive snapshots across all sources and persist revisions to `revisions.parquet`."""
    all_new_revs: list[pd.DataFrame] = []
    tracked = [
        ("worldbank", "pink_sheet"),
        ("bnm", "exchangerates_daily_1700"),
        ("dosm", "ppi_sitc"),
        ("dosm", "trade_sitc_1d"),
    ]
    for source, dataset in tracked:
        snaps = list_snapshots(raw_root, source, dataset)
        for idx in range(1, len(snaps)):
            prev_snap = snaps[idx - 1]
            curr_snap = snaps[idx]
            prev_df = _parse_snapshot_to_monthly_df(raw_root, prev_snap)
            curr_df = _parse_snapshot_to_monthly_df(raw_root, curr_snap)
            diff = diff_revisions(
                prev_df,
                curr_df,
                old_snapshot_id=prev_snap.snapshot_id,
                new_snapshot_id=curr_snap.snapshot_id,
            )
            if not diff.empty:
                all_new_revs.append(diff)

    combined_new = (
        pd.concat(all_new_revs, ignore_index=True)
        if all_new_revs
        else pd.DataFrame(
            columns=[
                "series_id",
                "period",
                "old_value",
                "new_value",
                "old_snapshot_id",
                "new_snapshot_id",
            ]
        )
    )
    return append_revisions(revisions_path, combined_new)


def compute_monthly_return_correlation(
    series_a: pd.DataFrame,
    series_b: pd.DataFrame,
) -> tuple[float, int]:
    """Compute Pearson correlation of monthly log returns `ln(y[t]/y[t-1])` on overlapping months."""
    a = series_a[["month", "value"]].sort_values("month").copy()
    b = series_b[["month", "value"]].sort_values("month").copy()
    a["r1_a"] = np.log(a["value"] / a["value"].shift(1))
    b["r1_b"] = np.log(b["value"] / b["value"].shift(1))
    merged = a[["month", "r1_a"]].merge(b[["month", "r1_b"]], on="month", how="inner").dropna()
    if len(merged) < 2:
        return 0.0, len(merged)
    corr = float(np.corrcoef(merged["r1_a"].to_numpy(), merged["r1_b"].to_numpy())[0, 1])
    return corr, len(merged)


def _render_data_quality_markdown(audit: DataQualityAudit, config: ProjectConfig) -> str:
    lines = [
        "# Data Quality Report (Gate G1)",
        "",
        f"- **Generated (UTC)**: `{audit.generated_at_utc}`",
        f"- **Gate G1 Status**: **{'PASS' if audit.gate_g1_passed else 'FAIL'}**",
        f"- **Objective O1 (`palm_wb_myr >= 180` gap-free months & contracts pass)**: **{'PASS' if audit.o1_passed else 'FAIL'}** (`{audit.palm_wb_myr_months}` months)",
        f"- **Selected Primary Target**: `{audit.selected_primary_target}` ({config.targets[audit.selected_primary_target].display_name})",
        f"- **Selected Secondary Target**: `{audit.selected_secondary_target}` ({config.targets[audit.selected_secondary_target].display_name})",
        f"- **Cross-check (`palm_wb_myr` vs `ppi_oilsfats_my` monthly log-return correlation)**: `{audit.palm_ppi_return_correlation:.4f}` over `{audit.palm_ppi_overlap_months}` overlapping months",
        f"- **Logged Revisions (`data/processed/revisions.parquet`)**: `{audit.revisions_count}` rows",
        "",
        "## 1. Series Contract Summary",
        "",
        "| Series ID | Snapshot ID | Rows | Start Month | End Month | Min | Max | Contiguous | Duplicates | Non-positive |",
        "| --- | --- | ---: | --- | --- | ---: | ---: | --- | --- | --- |",
    ]
    for s_id, s in audit.series_summaries.items():
        lines.append(
            f"| `{s_id}` | `{s.snapshot_id}` | {s.row_count} | `{s.start_month}` | `{s.end_month}` | "
            f"{s.min_value:.2f} | {s.max_value:.2f} | "
            f"{'Yes' if s.is_contiguous else 'No'} | {'Yes' if s.has_duplicates else 'No'} | "
            f"{'Yes' if s.has_nonpositive else 'No'} |"
        )

    lines.extend(
        [
            "",
            "## 2. World Bank Palm Oil Definition Breaks",
            "",
            "The series is **not** adjusted across definition changes; breaks are recorded from the World Bank Pink Sheet `Description` sheet and displayed on the dashboard:",
            "",
            "| Effective Date | World Bank Pink Sheet Basis Definition |",
            "| --- | --- |",
        ]
    )
    for brk in audit.definition_breaks:
        lines.append(f"| `{brk['date']}` | {brk['basis']} |")

    lines.extend(
        [
            "",
            "## 3. Attribution & Disclaimer",
            "",
            f"- **Licence**: {config.attribution.licence}",
            f"- **Transformation Note**: {config.attribution.transformation_note}",
            f"- **Disclaimer**: {config.attribution.disclaimer}",
            "",
        ]
    )
    return "\n".join(lines)


def run_data_quality_gate(
    config: ProjectConfig,
    *,
    root: Path = Path("."),
) -> DataQualityAudit:
    """Validate all ingested raw snapshots against contracts, log revisions, and write Gate G1 reports."""
    raw_root = root / config.paths.raw_dir
    processed_root = root / config.paths.processed_dir
    reports_root = root / config.paths.reports_dir

    wb_snap = latest_snapshot(raw_root, "worldbank", "pink_sheet")
    exr_snap = latest_snapshot(raw_root, "bnm", "exchangerates_daily_1700")
    ppi_snap = latest_snapshot(raw_root, "dosm", "ppi_sitc")
    trd_snap = latest_snapshot(raw_root, "dosm", "trade_sitc_1d")
    sitc_snap = latest_snapshot(raw_root, "dosm", "sitc")

    missing_snaps = [
        name
        for name, snap in [
            ("worldbank/pink_sheet", wb_snap),
            ("bnm/exchangerates_daily_1700", exr_snap),
            ("dosm/ppi_sitc", ppi_snap),
            ("dosm/trade_sitc_1d", trd_snap),
            ("dosm/sitc", sitc_snap),
        ]
        if snap is None
    ]
    if missing_snaps:
        raise SnapshotValidationError(f"Missing required raw snapshots: {missing_snaps}")

    assert wb_snap is not None
    assert exr_snap is not None
    assert ppi_snap is not None
    assert trd_snap is not None
    assert sitc_snap is not None

    # Validate SITC lookup
    parse_sitc_lookup(_snapshot_payload_path(raw_root, sitc_snap).read_bytes())

    wb_df = _parse_snapshot_to_monthly_df(raw_root, wb_snap)
    usdmyr_df = _parse_snapshot_to_monthly_df(raw_root, exr_snap)
    ppi_df = _parse_snapshot_to_monthly_df(raw_root, ppi_snap)
    trd_df = _parse_snapshot_to_monthly_df(raw_root, trd_snap)

    palm_usd_df = wb_df[wb_df["series_id"] == "palm_wb_usd"].reset_index(drop=True)
    brent_usd_df = wb_df[wb_df["series_id"] == "brent_wb_usd"].reset_index(drop=True)
    soyoil_usd_df = wb_df[wb_df["series_id"] == "soyoil_wb_usd"].reset_index(drop=True)
    palm_myr_df = build_palm_myr_series(palm_usd_df, usdmyr_df)

    series_map = {
        "palm_wb_usd": (palm_usd_df, 180),
        "palm_wb_myr": (palm_myr_df, config.targets["palm_wb_myr"].min_history_months),
        "ppi_oilsfats_my": (ppi_df, config.targets["ppi_oilsfats_my"].min_history_months),
        "brent_wb_usd": (brent_usd_df, 180),
        "soyoil_wb_usd": (soyoil_usd_df, 180),
        "usdmyr_avg": (usdmyr_df, 180),
        "exports_sitc4": (trd_df, 180),
    }

    summaries: dict[str, SeriesSummary] = {}
    for s_id, (s_df, min_r) in series_map.items():
        summaries[s_id] = validate_monthly_series_df(
            s_df,
            expected_series_id=s_id,
            min_rows=min_r,
            require_contiguous=True,
        )

    revisions_path = processed_root / "revisions.parquet"
    revs_df = sync_revisions_from_snapshots(raw_root, revisions_path)

    corr, overlap_n = compute_monthly_return_correlation(palm_myr_df, ppi_df)

    palm_months = summaries["palm_wb_myr"].row_count
    ppi_months = summaries["ppi_oilsfats_my"].row_count
    o1_passed = palm_months >= config.targets["palm_wb_myr"].min_history_months and all(
        s.is_contiguous and not s.has_duplicates and not s.has_nonpositive
        for s in summaries.values()
    )
    gate_g1_passed = (
        o1_passed and ppi_months >= config.targets["ppi_oilsfats_my"].min_history_months
    )
    selected_primary = "palm_wb_myr" if o1_passed else "ppi_oilsfats_my"
    selected_secondary = "ppi_oilsfats_my" if selected_primary == "palm_wb_myr" else "palm_wb_myr"

    reasons = [
        f"palm_wb_myr has {palm_months} contiguous monthly observations (>= 180 required for O1).",
        f"ppi_oilsfats_my has {ppi_months} contiguous monthly observations (>= 200 required).",
        f"Monthly log-return correlation between palm_wb_myr and ppi_oilsfats_my is {corr:.4f} (n={overlap_n}).",
    ]

    breaks = [b.model_dump() for b in config.targets["palm_wb_myr"].definition_breaks]
    audit = DataQualityAudit(
        generated_at_utc=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        gate_g1_passed=gate_g1_passed,
        o1_passed=o1_passed,
        selected_primary_target=selected_primary,
        selected_secondary_target=selected_secondary,
        palm_wb_myr_months=palm_months,
        ppi_oilsfats_my_months=ppi_months,
        palm_ppi_return_correlation=corr,
        palm_ppi_overlap_months=overlap_n,
        revisions_count=len(revs_df),
        series_summaries=summaries,
        definition_breaks=breaks,
        reasons=reasons,
    )

    reports_root.mkdir(parents=True, exist_ok=True)
    audit_json_path = reports_root / "data_quality_audit.json"
    audit_md_path = reports_root / "data_quality.md"
    audit_json_path.write_text(json.dumps(audit.model_dump(), indent=2) + "\n", encoding="utf-8")
    audit_md_path.write_text(_render_data_quality_markdown(audit, config), encoding="utf-8")

    return audit
