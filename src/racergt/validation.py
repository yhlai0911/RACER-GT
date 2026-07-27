from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .config import RacerGTConfig
from .pipeline import RacerGTPipeline
from .simulation import SimulationSettings, simulate_racergt_data


@dataclass
class ValidationResult:
    metrics: pd.DataFrame
    summary: pd.DataFrame


def _metrics(estimate: np.ndarray, truth: np.ndarray, top_fraction: float = 0.05) -> dict:
    finite = np.isfinite(estimate) & np.isfinite(truth)
    e = estimate[finite]
    t = truth[finite]
    error = e - t
    corr = np.corrcoef(e, t)[0, 1] if np.std(e) > 0 and np.std(t) > 0 else np.nan
    de = np.diff(np.log1p(np.maximum(e, 0)))
    dt = np.diff(np.log1p(np.maximum(t, 0)))
    innovation_corr = (
        np.corrcoef(de, dt)[0, 1] if np.std(de) > 0 and np.std(dt) > 0 else np.nan
    )
    k = max(1, int(np.ceil(top_fraction * len(t))))
    top_e = set(np.argpartition(e, -k)[-k:])
    top_t = set(np.argpartition(t, -k)[-k:])
    peak_recall = len(top_e & top_t) / k
    return {
        "bias": float(np.mean(error)),
        "absolute_bias": float(abs(np.mean(error))),
        "mae": float(np.mean(np.abs(error))),
        "rmse": float(np.sqrt(np.mean(error**2))),
        "correlation": float(corr),
        "innovation_correlation": float(innovation_corr),
        "top_peak_recall": float(peak_recall),
    }


def evaluate_pipeline_against_truth(result, truth: pd.DataFrame) -> pd.DataFrame:
    truth_series = truth.set_index(pd.to_datetime(truth["historical_date"]))["true_index"]
    matrix = result.complete_pulls.pivot(
        index="historical_date", columns="pull_id", values="value"
    ).sort_index()
    matrix.index = pd.to_datetime(matrix.index)
    common = matrix.index.intersection(truth_series.index)
    truth_values = truth_series.loc[common].to_numpy(dtype=float)
    estimators = {
        "single_pull": matrix.loc[common].iloc[:, 0].to_numpy(dtype=float),
        "simple_mean": matrix.loc[common].mean(axis=1).to_numpy(dtype=float),
        "cross_pull_median": matrix.loc[common].median(axis=1).to_numpy(dtype=float),
    }
    final = result.final_series.copy()
    final.index = pd.to_datetime(final["historical_date"])
    estimators["RACER_GT"] = final.loc[common, "value"].to_numpy(dtype=float)
    rows = []
    for name, estimate in estimators.items():
        row = {"estimator": name, **_metrics(estimate, truth_values)}
        rows.append(row)
    return pd.DataFrame(rows)


def run_monte_carlo(
    config: RacerGTConfig,
    replications: int = 20,
    first_seed: int = 1000,
) -> ValidationResult:
    records = []
    for replication in range(replications):
        seed = first_seed + replication
        simulation = simulate_racergt_data(
            config,
            SimulationSettings(random_seed=seed, exact_duplicate_fraction=0.10),
        )
        result = RacerGTPipeline(config).fit(simulation.raw_chunks, simulation.benchmark)
        metrics = evaluate_pipeline_against_truth(result, simulation.truth)
        metrics.insert(0, "replication", replication + 1)
        metrics.insert(1, "seed", seed)
        records.append(metrics)
    all_metrics = pd.concat(records, ignore_index=True)
    summary = (
        all_metrics.groupby("estimator")
        .agg(
            mean_bias=("bias", "mean"),
            mean_absolute_bias=("absolute_bias", "mean"),
            mean_mae=("mae", "mean"),
            mean_rmse=("rmse", "mean"),
            median_rmse=("rmse", "median"),
            mean_correlation=("correlation", "mean"),
            mean_innovation_correlation=("innovation_correlation", "mean"),
            mean_peak_recall=("top_peak_recall", "mean"),
        )
        .reset_index()
    )
    return ValidationResult(metrics=all_metrics, summary=summary)
