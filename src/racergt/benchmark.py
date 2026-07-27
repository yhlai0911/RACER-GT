from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import sparse
from scipy.sparse.linalg import spsolve

from .config import BenchmarkConfig


@dataclass
class BenchmarkResult:
    series: pd.DataFrame
    benchmark_fit: pd.DataFrame
    diagnostics: dict

    def save(self, output_dir: str | Path) -> dict[str, Path]:
        output = Path(output_dir)
        output.mkdir(parents=True, exist_ok=True)
        paths = {
            "series": output / "benchmarked_consensus_series.csv",
            "fit": output / "benchmark_fit.csv",
        }
        self.series.to_csv(paths["series"], index=False)
        self.benchmark_fit.to_csv(paths["fit"], index=False)
        return paths


def _difference_penalty(n: int) -> sparse.csr_matrix:
    if n <= 1:
        return sparse.csr_matrix((n, n))
    diagonals = [-np.ones(n - 1), np.ones(n - 1)]
    d = sparse.diags(diagonals, offsets=[0, 1], shape=(n - 1, n), format="csr")
    return d.T @ d


def build_aggregation_matrix(
    daily_dates: pd.DatetimeIndex,
    benchmark: pd.DataFrame,
) -> tuple[sparse.csr_matrix, np.ndarray, np.ndarray, pd.DataFrame]:
    required = {"period_start", "period_end", "value"}
    missing = required.difference(benchmark.columns)
    if missing:
        raise ValueError(f"Missing benchmark columns: {sorted(missing)}")
    bench = benchmark.copy()
    bench["period_start"] = pd.to_datetime(bench["period_start"]).dt.normalize()
    bench["period_end"] = pd.to_datetime(bench["period_end"]).dt.normalize()
    bench["value"] = pd.to_numeric(bench["value"], errors="coerce").astype(float)
    if "se" not in bench.columns:
        bench["se"] = np.nan
    bench["se"] = pd.to_numeric(bench["se"], errors="coerce").astype(float)

    date_positions = {date: idx for idx, date in enumerate(daily_dates)}
    row_indices: list[int] = []
    col_indices: list[int] = []
    values: list[float] = []
    retained_rows: list[int] = []
    for new_row, (old_idx, row) in enumerate(bench.iterrows()):
        dates = daily_dates[(daily_dates >= row["period_start"]) & (daily_dates <= row["period_end"])]
        if len(dates) == 0 or not np.isfinite(row["value"]):
            continue
        retained_rows.append(old_idx)
        weight = 1.0 / len(dates)
        for date in dates:
            row_indices.append(len(retained_rows) - 1)
            col_indices.append(date_positions[date])
            values.append(weight)
    retained = bench.loc[retained_rows].reset_index(drop=True)
    a = sparse.coo_matrix(
        (values, (row_indices, col_indices)), shape=(len(retained), len(daily_dates))
    ).tocsr()
    b = retained["value"].to_numpy(dtype=float)
    se = retained["se"].to_numpy(dtype=float)
    return a, b, se, retained


def temporal_benchmark(
    preliminary: pd.DataFrame,
    benchmark: pd.DataFrame,
    config: BenchmarkConfig,
) -> BenchmarkResult:
    """Benchmark a daily consensus to noisy lower-frequency measurements.

    Let z be the preliminary daily index, A the temporal aggregation matrix, and b
    lower-frequency benchmark values. The soft estimator minimizes

        (x-z)' Q (x-z) + (Ax-b)' W (Ax-b),

    where Q combines fidelity and first-difference smoothness. The exact estimator
    solves the same correction problem subject to Ax=b.
    """

    if not {"historical_date", "value"}.issubset(preliminary.columns):
        raise ValueError("preliminary must contain historical_date and value")
    daily = preliminary.copy().sort_values("historical_date")
    daily["historical_date"] = pd.to_datetime(daily["historical_date"]).dt.normalize()
    dates = pd.DatetimeIndex(daily["historical_date"])
    z = daily["value"].to_numpy(dtype=float)
    if not np.isfinite(z).all():
        z = pd.Series(z, index=dates).interpolate(limit_direction="both").to_numpy()
    a, b, se, retained = build_aggregation_matrix(dates, benchmark)
    if a.shape[0] == 0:
        raise ValueError("No benchmark periods overlap the daily series")

    n = len(z)
    q = (
        config.fidelity_weight * sparse.eye(n, format="csr")
        + config.smoothness_weight * _difference_penalty(n)
        + config.ridge * sparse.eye(n, format="csr")
    )
    discrepancy = b - a @ z

    if config.mode == "exact":
        zero = sparse.csr_matrix((a.shape[0], a.shape[0]))
        kkt = sparse.bmat([[q, a.T], [a, zero]], format="csr")
        rhs = np.concatenate([np.zeros(n), discrepancy])
        solution = spsolve(kkt, rhs)
        delta = solution[:n]
    else:
        se_filled = np.where(
            np.isfinite(se) & (se > 0),
            se,
            config.default_benchmark_se,
        )
        w = sparse.diags(1.0 / (se_filled**2), format="csr")
        normal = q + a.T @ w @ a
        rhs = a.T @ w @ discrepancy
        delta = spsolve(normal, rhs)

    x = z + np.asarray(delta)
    negative_before_clip = int(np.sum(x < 0))
    if config.preserve_nonnegative and negative_before_clip:
        x = np.maximum(x, 0.0)

    fitted = np.asarray(a @ x)
    residual = fitted - b
    se_filled = np.where(
        np.isfinite(se) & (se > 0),
        se,
        config.default_benchmark_se,
    )
    fit = retained.copy()
    fit["fitted_value"] = fitted
    fit["residual"] = residual
    fit["standardized_residual"] = residual / se_filled

    out = daily.copy()
    out = out.rename(columns={"value": "preliminary_value"})
    out["value"] = x
    out["benchmark_correction"] = x - z
    # Conditional uncertainty from the cross-pull consensus is retained after
    # deterministic temporal benchmarking. This is an approximation: it does not
    # include uncertainty in the lower-frequency benchmark itself.
    if "standard_error" in out.columns:
        se_out = pd.to_numeric(out["standard_error"], errors="coerce").to_numpy(dtype=float)
        out["ci_lower_95"] = x - 1.96 * se_out
        out["ci_upper_95"] = x + 1.96 * se_out
    diagnostics = {
        "mode": config.mode,
        "n_daily_observations": n,
        "n_benchmark_constraints": int(a.shape[0]),
        "benchmark_rmse": float(np.sqrt(np.mean(residual**2))),
        "benchmark_standardized_rmse": float(
            np.sqrt(np.mean((residual / se_filled) ** 2))
        ),
        "mean_absolute_correction": float(np.mean(np.abs(x - z))),
        "max_absolute_correction": float(np.max(np.abs(x - z))),
        "negative_values_before_clip": negative_before_clip,
        "nonnegative_projection_used": bool(config.preserve_nonnegative and negative_before_clip),
    }
    return BenchmarkResult(series=out, benchmark_fit=fit, diagnostics=diagnostics)
