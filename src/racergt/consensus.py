from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from sklearn.covariance import LedoitWolf

from .config import ConsensusConfig
from .schema import vector_to_bytes


@dataclass
class DesignWeightedResult:
    """Finite-mixture estimator for the locked retrieval-design expectation."""

    consensus: pd.DataFrame
    cell_means: pd.DataFrame
    cell_weights: pd.DataFrame
    diagnostics: dict

    def save(self, output_dir: str | Path) -> dict[str, Path]:
        output = Path(output_dir)
        output.mkdir(parents=True, exist_ok=True)
        paths = {
            "consensus": output / "design_weighted_consensus.csv",
            "cell_means": output / "design_cell_means.csv",
            "cell_weights": output / "design_cell_weights.csv",
        }
        self.consensus.to_csv(paths["consensus"], index=False)
        self.cell_means.to_csv(paths["cell_means"], index=True)
        self.cell_weights.to_csv(paths["cell_weights"], index=False)
        return paths


@dataclass
class ConsensusResult:
    consensus: pd.DataFrame
    weights: pd.DataFrame
    covariance: pd.DataFrame
    aligned_matrix: pd.DataFrame
    residual_matrix: pd.DataFrame
    duplicate_map: pd.DataFrame
    diagnostics: dict

    def save(self, output_dir: str | Path) -> dict[str, Path]:
        output = Path(output_dir)
        output.mkdir(parents=True, exist_ok=True)
        paths = {
            "consensus": output / "consensus_series.csv",
            "weights": output / "consensus_weights.csv",
            "covariance": output / "pull_error_covariance.csv",
            "aligned_matrix": output / "aligned_pull_matrix.csv",
            "residual_matrix": output / "consensus_residuals.csv",
            "duplicate_map": output / "duplicate_collapse_map.csv",
        }
        self.consensus.to_csv(paths["consensus"], index=False)
        self.weights.to_csv(paths["weights"], index=False)
        self.covariance.to_csv(paths["covariance"], index=True)
        self.aligned_matrix.to_csv(paths["aligned_matrix"], index=True)
        self.residual_matrix.to_csv(paths["residual_matrix"], index=True)
        self.duplicate_map.to_csv(paths["duplicate_map"], index=False)
        return paths


def _hash_column(series: pd.Series, decimals: int = 10) -> str:
    return hashlib.sha256(vector_to_bytes(series.to_numpy(), decimals=decimals)).hexdigest()


def collapse_exact_vectors(matrix: pd.DataFrame, decimals: int = 10) -> tuple[pd.DataFrame, pd.DataFrame]:
    records: list[dict] = []
    representatives: list[str] = []
    for digest, cols in pd.Series(
        {_col: _hash_column(matrix[_col], decimals) for _col in matrix.columns}
    ).groupby(lambda idx: _hash_column(matrix[idx], decimals)):
        members = sorted(cols.index.astype(str).tolist())
        representative = members[0]
        representatives.append(representative)
        for member in members:
            records.append(
                {
                    "pull_id": member,
                    "representative_pull_id": representative,
                    "vector_hash": digest,
                    "multiplicity": len(members),
                    "collapsed": member != representative,
                }
            )
    return matrix.loc[:, representatives].copy(), pd.DataFrame(records)


def fit_design_weighted_consensus(
    matrix: pd.DataFrame,
    metadata: pd.DataFrame,
    cell_columns: tuple[str, ...] = ("collection_day", "stream_id"),
    target_weights: dict[str, float] | None = None,
    baseline_start: pd.Timestamp | str | None = None,
    baseline_end: pd.Timestamp | str | None = None,
    require_complete_cells: bool = True,
) -> DesignWeightedResult:
    """Estimate the pre-specified finite-mixture retrieval-design expectation.

    Pulls are averaged within design cells and cell means are then combined using
    fixed target weights. With non-informative inclusion and pre-specified weights,
    this estimator is unbiased for the corresponding mixture of cell expectations;
    cross-pull dependence changes its variance, not its expectation.

    This estimator is retained as a transparent design-based reference. The primary
    RACER-GT latent-signal estimator is the covariance-adjusted consensus returned by
    :func:`fit_gls_consensus`.
    """

    if matrix.empty:
        raise ValueError("matrix must contain at least one pull")
    missing = {"pull_id", *cell_columns}.difference(metadata.columns)
    if missing:
        raise ValueError(f"Missing design metadata columns: {sorted(missing)}")

    work = matrix.sort_index().astype(float).copy()
    work.columns = work.columns.astype(str)
    meta = metadata.copy()
    meta["pull_id"] = meta["pull_id"].astype(str)
    if meta["pull_id"].duplicated().any():
        raise ValueError("metadata must contain one row per pull_id")
    unknown = sorted(set(work.columns).difference(meta["pull_id"]))
    if unknown:
        raise ValueError(f"Missing metadata for pulls: {unknown}")
    meta = meta[meta["pull_id"].isin(work.columns)].copy()
    meta["design_cell"] = meta[list(cell_columns)].astype(str).agg("|".join, axis=1)

    start = pd.Timestamp(baseline_start).normalize() if baseline_start is not None else work.index.min()
    end = pd.Timestamp(baseline_end).normalize() if baseline_end is not None else work.index.max()
    mask = (work.index >= start) & (work.index <= end)
    means = work.loc[mask].mean(axis=0, skipna=True)
    if (means <= 0).any() or means.isna().any():
        raise ValueError("Every pull must have a positive finite baseline mean")
    work = work.divide(means, axis=1) * 100.0

    cell_series: dict[str, pd.Series] = {}
    cell_rows: list[dict] = []
    for cell_id, group in meta.groupby("design_cell", sort=True):
        pulls = group["pull_id"].tolist()
        values = work[pulls]
        if require_complete_cells:
            series = values.mean(axis=1, skipna=False)
        else:
            series = values.mean(axis=1, skipna=True)
        cell_series[str(cell_id)] = series
        row = {
            "design_cell": str(cell_id),
            "n_pulls": len(pulls),
            "pull_ids": ";".join(pulls),
        }
        for col in cell_columns:
            unique_values = group[col].drop_duplicates().tolist()
            row[col] = unique_values[0] if len(unique_values) == 1 else ";".join(map(str, unique_values))
        cell_rows.append(row)
    cell_means = pd.DataFrame(cell_series, index=work.index)
    cells = list(cell_means.columns)
    if not cells:
        raise ValueError("No design cells could be formed")

    if target_weights is None:
        weights = pd.Series(1.0 / len(cells), index=cells, dtype=float)
    else:
        missing_weights = sorted(set(cells).difference(target_weights))
        extra_weights = sorted(set(target_weights).difference(cells))
        if missing_weights or extra_weights:
            raise ValueError(
                f"target_weights must match design cells; missing={missing_weights}, extra={extra_weights}"
            )
        weights = pd.Series({cell: float(target_weights[cell]) for cell in cells})
        if (weights < 0).any() or not np.isfinite(weights).all() or weights.sum() <= 0:
            raise ValueError("target_weights must be finite, nonnegative, and sum to a positive value")
        weights = weights / weights.sum()

    complete = cell_means.notna().all(axis=1)
    values = cell_means.mul(weights, axis=1).sum(axis=1, min_count=len(cells))
    dispersion = cell_means.std(axis=1, ddof=1) if len(cells) > 1 else pd.Series(0.0, index=work.index)
    out = pd.DataFrame(
        {
            "historical_date": work.index,
            "value": values.to_numpy(dtype=float),
            "between_cell_sd": dispersion.to_numpy(dtype=float),
            "n_design_cells_available": cell_means.notna().sum(axis=1).to_numpy(dtype=int),
            "complete_cell_coverage": complete.to_numpy(dtype=bool),
        }
    )
    weight_table = pd.DataFrame(cell_rows).merge(
        weights.rename("target_weight").rename_axis("design_cell").reset_index(),
        on="design_cell",
        how="left",
        validate="one_to_one",
    )
    diagnostics = {
        "cell_columns": list(cell_columns),
        "n_design_cells": len(cells),
        "n_pulls": int(work.shape[1]),
        "n_complete_dates": int(complete.sum()),
        "complete_date_share": float(complete.mean()),
        "require_complete_cells": bool(require_complete_cells),
        "baseline_start": str(start.date()),
        "baseline_end": str(end.date()),
        "weight_sum": float(weights.sum()),
    }
    return DesignWeightedResult(
        consensus=out,
        cell_means=cell_means,
        cell_weights=weight_table,
        diagnostics=diagnostics,
    )


def _nearest_psd(matrix: np.ndarray, floor: float = 1e-10) -> np.ndarray:
    symmetric = 0.5 * (matrix + matrix.T)
    vals, vecs = np.linalg.eigh(symmetric)
    vals = np.maximum(vals, floor)
    return (vecs * vals) @ vecs.T


def _estimate_covariance(residuals: pd.DataFrame, method: str) -> np.ndarray:
    clean = residuals.dropna(axis=0, how="any")
    if len(clean) < max(5, residuals.shape[1] + 1):
        # Missing residuals are centered; zero imputation is conservative for rare gaps.
        clean = residuals.fillna(0.0)
    x = clean.to_numpy(dtype=float)
    if method == "diagonal":
        var = np.var(x, axis=0, ddof=1)
        return np.diag(np.maximum(var, 1e-10))
    if method == "empirical":
        return _nearest_psd(np.cov(x, rowvar=False, ddof=1))
    return _nearest_psd(LedoitWolf(assume_centered=True).fit(x).covariance_)


def _minimum_variance_weights(
    covariance: np.ndarray,
    nonnegative: bool,
    cap: float | None,
) -> np.ndarray:
    m = covariance.shape[0]
    ones = np.ones(m)
    if not nonnegative and cap is None:
        inv = np.linalg.pinv(covariance)
        denom = float(ones @ inv @ ones)
        if denom <= 0:
            raise ValueError("Invalid covariance matrix for GLS weights")
        return inv @ ones / denom

    upper = 1.0 if cap is None else float(cap)
    if m * upper < 1.0 - 1e-12:
        raise ValueError(f"weight_cap={upper} is infeasible for {m} pulls")
    bounds = [(0.0 if nonnegative else -np.inf, upper) for _ in range(m)]
    constraints = {"type": "eq", "fun": lambda w: np.sum(w) - 1.0}
    x0 = np.full(m, 1.0 / m)
    result = minimize(
        lambda w: float(w @ covariance @ w),
        x0,
        method="SLSQP",
        bounds=bounds,
        constraints=constraints,
        options={"ftol": 1e-12, "maxiter": 2000},
    )
    if not result.success:
        raise RuntimeError(f"Consensus weight optimization failed: {result.message}")
    weights = np.asarray(result.x, dtype=float)
    weights[np.abs(weights) < 1e-12] = 0.0
    return weights / weights.sum()


def _spectral_effective_count(residuals: pd.DataFrame) -> float:
    clean = residuals.dropna(axis=0, how="any")
    if len(clean) < 3:
        return float("nan")
    corr = np.corrcoef(clean.to_numpy(dtype=float), rowvar=False)
    corr = np.nan_to_num(corr, nan=0.0)
    np.fill_diagonal(corr, 1.0)
    trace = float(np.trace(corr))
    denom = float(np.trace(corr @ corr))
    return trace**2 / denom if denom > 0 else float("nan")


def fit_gls_consensus(
    matrix: pd.DataFrame,
    config: ConsensusConfig,
    metadata: pd.DataFrame | None = None,
    baseline_start: pd.Timestamp | str | None = None,
    baseline_end: pd.Timestamp | str | None = None,
) -> ConsensusResult:
    """Estimate a covariance-adjusted latent consensus across complete GT pulls.

    Under Z_t = 1 * X_t + e_t, E(e_t)=0, and Var(e_t)=Sigma, the unrestricted
    weights Sigma^{-1}1/(1' Sigma^{-1}1) are BLUE. The default constrained version
    enforces nonnegative weights to avoid unstable extrapolation while preserving the
    sum-to-one unbiasedness condition.
    """

    if matrix.shape[1] < 2:
        raise ValueError("At least two pulls are required")
    original = matrix.sort_index().astype(float).copy()
    if config.collapse_exact_duplicates:
        work, duplicate_map = collapse_exact_vectors(original)
    else:
        work = original.copy()
        duplicate_map = pd.DataFrame(
            {
                "pull_id": work.columns.astype(str),
                "representative_pull_id": work.columns.astype(str),
                "vector_hash": [_hash_column(work[c]) for c in work.columns],
                "multiplicity": 1,
                "collapsed": False,
            }
        )

    # Put all pulls on the same identified index scale. This is not an estimate of
    # absolute search counts; it defines a common baseline-mean-100 estimand.
    if config.baseline_rescale:
        start = pd.Timestamp(baseline_start).normalize() if baseline_start is not None else work.index.min()
        end = pd.Timestamp(baseline_end).normalize() if baseline_end is not None else work.index.max()
        mask = (work.index >= start) & (work.index <= end)
        means = work.loc[mask].mean(axis=0, skipna=True)
        if (means <= 0).any() or means.isna().any():
            raise ValueError("Every pull must have a positive finite baseline mean")
        work = work.divide(means, axis=1) * 100.0

    preliminary = work.median(axis=1, skipna=True)
    pull_bias = work.sub(preliminary, axis=0).mean(axis=0, skipna=True)
    aligned = work.sub(pull_bias, axis=1) if config.center_pull_bias else work.copy()
    preliminary = aligned.median(axis=1, skipna=True)
    residuals = aligned.sub(preliminary, axis=0)

    covariance = _estimate_covariance(residuals, config.covariance)
    weights = _minimum_variance_weights(
        covariance,
        nonnegative=config.nonnegative_weights,
        cap=config.weight_cap,
    )
    pull_ids = list(map(str, aligned.columns))

    consensus_values: list[float] = []
    available_counts: list[int] = []
    for _, row in aligned.iterrows():
        values = row.to_numpy(dtype=float)
        available = np.isfinite(values)
        available_counts.append(int(available.sum()))
        if not available.any():
            consensus_values.append(np.nan)
            continue
        local_weights = weights[available]
        local_weights = local_weights / local_weights.sum()
        consensus_values.append(float(local_weights @ values[available]))
    consensus_array = np.asarray(consensus_values, dtype=float)

    base_variance = float(weights @ covariance @ weights)
    base_se = float(np.sqrt(max(base_variance, 0.0)))
    if config.local_uncertainty:
        deviations = aligned.sub(consensus_array, axis=0).abs()
        local_mad = deviations.median(axis=1, skipna=True).to_numpy(dtype=float)
        global_mad = float(np.nanmedian(local_mad))
        if not np.isfinite(global_mad) or global_mad <= 1e-12:
            multipliers = np.ones_like(local_mad)
        else:
            multipliers = np.clip(local_mad / global_mad, 0.25, 4.0)
        standard_errors = base_se * multipliers
    else:
        standard_errors = np.full(len(aligned), base_se)

    consensus = pd.DataFrame(
        {
            "historical_date": aligned.index,
            "value": consensus_array,
            "standard_error": standard_errors,
            "ci_lower_95": consensus_array - 1.96 * standard_errors,
            "ci_upper_95": consensus_array + 1.96 * standard_errors,
            "n_available_pulls": available_counts,
        }
    )

    multiplicity_map = (
        duplicate_map.groupby("representative_pull_id")["multiplicity"].max().to_dict()
    )
    bias_map = pull_bias.to_dict()
    meta_map: dict[str, dict] = {}
    if metadata is not None and "pull_id" in metadata.columns:
        for record in metadata.drop_duplicates("pull_id").to_dict(orient="records"):
            meta_map[str(record["pull_id"])] = record
    weight_rows = []
    for idx, pull_id in enumerate(pull_ids):
        row = {
            "pull_id": pull_id,
            "weight": float(weights[idx]),
            "pull_bias_removed": float(bias_map.get(pull_id, 0.0)),
            "exact_multiplicity": int(multiplicity_map.get(pull_id, 1)),
        }
        row.update({k: v for k, v in meta_map.get(pull_id, {}).items() if k != "pull_id"})
        weight_rows.append(row)
    weight_table = pd.DataFrame(weight_rows).sort_values("weight", ascending=False)

    kish_effective = float(1.0 / np.sum(weights**2)) if np.all(weights >= 0) else float("nan")
    diagnostics = {
        "n_raw_pulls": int(original.shape[1]),
        "n_unique_pulls": int(aligned.shape[1]),
        "n_collapsed_exact_duplicates": int(original.shape[1] - aligned.shape[1]),
        "covariance_method": config.covariance,
        "nonnegative_weights": config.nonnegative_weights,
        "base_consensus_se": base_se,
        "minimum_weight": float(weights.min()),
        "maximum_weight": float(weights.max()),
        "kish_effective_pulls": kish_effective,
        "spectral_effective_pulls": _spectral_effective_count(residuals),
        "covariance_condition_number": float(np.linalg.cond(covariance)),
        "weight_sum": float(weights.sum()),
    }
    covariance_df = pd.DataFrame(covariance, index=pull_ids, columns=pull_ids)
    return ConsensusResult(
        consensus=consensus,
        weights=weight_table,
        covariance=covariance_df,
        aligned_matrix=aligned,
        residual_matrix=residuals,
        duplicate_map=duplicate_map,
        diagnostics=diagnostics,
    )
