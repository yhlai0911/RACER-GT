from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy import stats

from .benchmark import temporal_benchmark
from .config import RacerGTConfig
from .pipeline import RacerGTPipeline
from .simulation import SimulationSettings, simulate_racergt_data

# Estimators are compared in matched information sets: every "*_benchmarked" variant
# receives exactly the same lower-frequency benchmark that RACER-GT receives, so a
# comparison isolates the estimator rather than the information it was handed.


@dataclass
class ValidationResult:
    metrics: pd.DataFrame
    summary: pd.DataFrame
    paired_tests: pd.DataFrame


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


def _mean_metrics(rows: list[dict]) -> dict:
    """Expected performance of one randomly drawn member of a set of series."""

    return {key: float(np.mean([row[key] for row in rows])) for key in rows[0]}


def evaluate_pipeline_against_truth(
    result,
    truth: pd.DataFrame,
    benchmark: pd.DataFrame | None = None,
    config: RacerGTConfig | None = None,
) -> pd.DataFrame:
    """Compare RACER-GT with cross-pull baselines against a known latent truth.

    Estimators are evaluated twice: once on the calibrated pulls alone, and once after
    applying the same temporal benchmark to each. Reporting only the benchmarked
    RACER-GT against unbenchmarked baselines would confound the estimator with the
    extra low-frequency information, which is why both blocks are always returned.
    """

    truth_series = truth.set_index(pd.to_datetime(truth["historical_date"]))["true_index"]
    matrix = result.complete_pulls.pivot(
        index="historical_date", columns="pull_id", values="value"
    ).sort_index()
    matrix.index = pd.to_datetime(matrix.index)
    common = matrix.index.intersection(truth_series.index)
    truth_values = truth_series.loc[common].to_numpy(dtype=float)
    sub = matrix.loc[common]

    consensus = result.consensus.consensus.copy()
    consensus.index = pd.to_datetime(consensus["historical_date"])
    racer_unbenchmarked = consensus.loc[common, "value"].to_numpy(dtype=float)

    series = {
        "cross_pull_median": sub.median(axis=1).to_numpy(dtype=float),
        "simple_mean": sub.mean(axis=1).to_numpy(dtype=float),
        "RACER_GT": racer_unbenchmarked,
    }
    per_pull = [sub[column].to_numpy(dtype=float) for column in sub.columns]

    rows = [
        {"estimator": "single_pull", "benchmarked": False,
         **_mean_metrics([_metrics(values, truth_values) for values in per_pull])}
    ]
    rows.extend(
        {"estimator": name, "benchmarked": False, **_metrics(values, truth_values)}
        for name, values in series.items()
    )

    if benchmark is not None and config is not None and config.benchmark.enabled:

        def apply_benchmark(values: np.ndarray) -> np.ndarray:
            frame = pd.DataFrame({"historical_date": common, "value": values})
            return (
                temporal_benchmark(frame, benchmark, config.benchmark)
                .series["value"]
                .to_numpy(dtype=float)
            )

        rows.append(
            {
                "estimator": "single_pull_benchmarked",
                "benchmarked": True,
                **_mean_metrics(
                    [_metrics(apply_benchmark(values), truth_values) for values in per_pull]
                ),
            }
        )
        rows.extend(
            {
                "estimator": f"{name}_benchmarked",
                "benchmarked": True,
                **_metrics(apply_benchmark(values), truth_values),
            }
            for name, values in series.items()
        )

    return pd.DataFrame(rows)


def _paired_comparison(pivot: pd.DataFrame, better: str, worse: str, note: str) -> dict | None:
    """One paired test on RMSE. A positive difference favours `better`."""

    if better not in pivot.columns or worse not in pivot.columns:
        return None
    difference = pivot[worse] - pivot[better]
    t_stat, t_p = stats.ttest_rel(pivot[worse], pivot[better])
    try:
        _, w_p = stats.wilcoxon(pivot[worse], pivot[better])
    except ValueError:  # identical series leave the signed-rank test undefined
        w_p = np.nan
    return {
        "estimator": better,
        "reference": worse,
        "comparison": note,
        "mean_rmse_difference": float(difference.mean()),
        "t_statistic": float(t_stat),
        "t_p_value": float(t_p),
        "wilcoxon_p_value": float(w_p),
        "wins": int((difference > 0).sum()),
        "n_replications": len(difference),
    }


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
        metrics = evaluate_pipeline_against_truth(
            result, simulation.truth, benchmark=simulation.benchmark, config=config
        )
        metrics.insert(0, "replication", replication + 1)
        metrics.insert(1, "seed", seed)
        records.append(metrics)
    all_metrics = pd.concat(records, ignore_index=True)

    grouped = all_metrics.groupby("estimator")
    summary = grouped.agg(
        benchmarked=("benchmarked", "first"),
        mean_bias=("bias", "mean"),
        mean_absolute_bias=("absolute_bias", "mean"),
        mean_mae=("mae", "mean"),
        mean_rmse=("rmse", "mean"),
        median_rmse=("rmse", "median"),
        sd_rmse=("rmse", "std"),
        mean_correlation=("correlation", "mean"),
        mean_innovation_correlation=("innovation_correlation", "mean"),
        mean_peak_recall=("top_peak_recall", "mean"),
    ).reset_index()
    # Monte Carlo standard error of the mean RMSE: without it, four-decimal RMSE
    # figures imply a precision that the number of replications cannot support.
    summary["mcse_rmse"] = summary["sd_rmse"] / np.sqrt(replications)
    summary = summary.sort_values("mean_rmse").reset_index(drop=True)

    pivot = all_metrics.pivot(index="replication", columns="estimator", values="rmse")
    comparisons = [
        ("RACER_GT", "single_pull", "aggregation gain, neither benchmarked"),
        ("RACER_GT", "simple_mean", "weighting gain, neither benchmarked"),
        ("RACER_GT", "cross_pull_median", "weighting gain versus the median"),
        (
            "RACER_GT_benchmarked",
            "simple_mean_benchmarked",
            "weighting gain, both benchmarked",
        ),
        (
            "RACER_GT_benchmarked",
            "RACER_GT",
            "benchmark gain, estimator held fixed",
        ),
        (
            "simple_mean_benchmarked",
            "simple_mean",
            "benchmark gain for the simple mean",
        ),
    ]
    tests = [
        row
        for better, worse, note in comparisons
        if (row := _paired_comparison(pivot, better, worse, note)) is not None
    ]
    return ValidationResult(
        metrics=all_metrics,
        summary=summary,
        paired_tests=pd.DataFrame(tests),
    )
