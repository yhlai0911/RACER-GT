from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

import numpy as np
import pandas as pd

RAW_REQUIRED_COLUMNS = {
    "series_id",
    "pull_id",
    "chunk_id",
    "historical_date",
    "value",
    "collection_day",
    "stream_id",
    "replicate_id",
    "window_start",
    "window_end",
}

COMPLETE_PULL_REQUIRED_COLUMNS = {
    "series_id",
    "pull_id",
    "historical_date",
    "value",
    "collection_day",
    "stream_id",
    "replicate_id",
}

BENCHMARK_REQUIRED_COLUMNS = {
    "series_id",
    "period_start",
    "period_end",
    "value",
}


@dataclass(frozen=True)
class ValidationIssue:
    severity: str
    code: str
    message: str
    rows: int | None = None


def _missing_columns(df: pd.DataFrame, required: Iterable[str]) -> set[str]:
    return set(required).difference(df.columns)


def validate_raw_chunks(df: pd.DataFrame) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    missing = _missing_columns(df, RAW_REQUIRED_COLUMNS)
    if missing:
        issues.append(
            ValidationIssue("error", "missing_columns", f"Missing columns: {sorted(missing)}")
        )
        return issues

    date_cols = ["historical_date", "window_start", "window_end"]
    for col in date_cols:
        parsed = pd.to_datetime(df[col], errors="coerce")
        bad = int(parsed.isna().sum())
        if bad:
            issues.append(ValidationIssue("error", f"invalid_{col}", f"Invalid {col}", bad))

    values = pd.to_numeric(df["value"], errors="coerce")
    bad_numeric = int(values.isna().sum() - df["value"].isna().sum())
    if bad_numeric:
        issues.append(ValidationIssue("error", "invalid_value", "Non-numeric GT values", bad_numeric))
    out_of_range = int(((values < 0) | (values > 100)).sum())
    if out_of_range:
        issues.append(
            ValidationIssue(
                "warning",
                "value_outside_0_100",
                "Values outside [0, 100]; acceptable only if input is already calibrated",
                out_of_range,
            )
        )

    duplicate_key = ["series_id", "pull_id", "chunk_id", "historical_date"]
    dup = int(df.duplicated(duplicate_key, keep=False).sum())
    if dup:
        issues.append(
            ValidationIssue("error", "duplicate_raw_keys", "Duplicate raw observation keys", dup)
        )

    start = pd.to_datetime(df["window_start"], errors="coerce")
    end = pd.to_datetime(df["window_end"], errors="coerce")
    hist = pd.to_datetime(df["historical_date"], errors="coerce")
    outside = int(((hist < start) | (hist > end)).sum())
    if outside:
        issues.append(
            ValidationIssue(
                "error",
                "date_outside_window",
                "Historical date falls outside its declared chunk window",
                outside,
            )
        )

    if "is_partial" in df.columns:
        partial = int(df["is_partial"].fillna(False).astype(bool).sum())
        if partial:
            issues.append(
                ValidationIssue("error", "partial_observations", "Partial observations present", partial)
            )

    return issues


def coerce_raw_chunks(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for col in ["historical_date", "window_start", "window_end"]:
        out[col] = pd.to_datetime(out[col]).dt.normalize()
    if "retrieved_at" in out.columns:
        out["retrieved_at"] = pd.to_datetime(out["retrieved_at"], utc=True, errors="coerce")
    out["value"] = pd.to_numeric(out["value"], errors="coerce").astype(float)
    out["collection_day"] = pd.to_numeric(out["collection_day"], errors="raise").astype(int)
    out["replicate_id"] = out["replicate_id"].astype(str)
    out["stream_id"] = out["stream_id"].astype(str)
    out["pull_id"] = out["pull_id"].astype(str)
    out["chunk_id"] = out["chunk_id"].astype(str)
    out["series_id"] = out["series_id"].astype(str)
    return out


def wide_pull_matrix(complete: pd.DataFrame, value_col: str = "value") -> pd.DataFrame:
    missing = _missing_columns(complete, COMPLETE_PULL_REQUIRED_COLUMNS)
    if missing:
        raise ValueError(f"Missing complete-pull columns: {sorted(missing)}")
    data = complete.copy()
    data["historical_date"] = pd.to_datetime(data["historical_date"]).dt.normalize()
    matrix = data.pivot(index="historical_date", columns="pull_id", values=value_col).sort_index()
    return matrix


def ensure_finite_matrix(matrix: pd.DataFrame, min_fraction: float = 0.9) -> pd.DataFrame:
    keep_cols = matrix.notna().mean(axis=0) >= min_fraction
    result = matrix.loc[:, keep_cols]
    if result.empty:
        raise ValueError("No pulls satisfy the minimum finite-observation fraction")
    return result


def vector_to_bytes(values: np.ndarray, decimals: int = 10) -> bytes:
    arr = np.asarray(values, dtype=np.float64)
    rounded = np.round(arr, decimals=decimals)
    sentinel = np.float64(9.876543210123456e307)
    rounded = np.where(np.isnan(rounded), sentinel, rounded)
    return rounded.tobytes(order="C")
