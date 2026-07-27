"""Does the covariance adjustment pay when dependence is heterogeneous?

The headline Monte Carlo finds no advantage for the covariance-adjusted consensus
over a simple mean. That result is conditional on a data-generating process in
which every pull carries the same error structure: the residual covariance is
block-equicorrelated, and the minimum-variance weights of such a matrix are equal
weights, so GLS has nothing to exploit and can only lose on estimation noise.

This experiment varies the one thing that condition depends on. A subset of pulls
is placed behind a shared cache disturbance that cuts across collection days and
streams, so the extra dependence is invisible to the design facets and can only be
found in the residual covariance. If the negative headline result is a property of
the estimator, the ranking should not move. If it is a property of the scenario,
GLS should overtake the simple mean as the cluster grows.

    PYTHONPATH=src python examples/run_dependence_experiment.py

Writes dependence_experiment/ (per-replication metrics, summary, paired tests).
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

from racergt.config import QuerySpec, RacerGTConfig
from racergt.consensus import fit_gls_consensus
from racergt.pipeline import RacerGTPipeline
from racergt.simulation import SimulationSettings, simulate_racergt_data

# Cluster fraction and the weight the shared disturbance carries for its members.
# (0.00, 0.0) reproduces the homogeneous scenario of the headline Monte Carlo.
SCENARIOS = [
    ("homogeneous", 0.00, 0.0),
    ("cache_third_moderate", 0.33, 0.5),
    ("cache_third_strong", 0.33, 0.8),
    ("cache_half_strong", 0.50, 0.8),
]
SEEDS = list(range(1200, 1220))


def build_config() -> RacerGTConfig:
    """Same protocol as the headline Monte Carlo, so results are comparable."""

    config = RacerGTConfig(
        query=QuerySpec(
            series_id="dep",
            keyword="synthetic attention",
            geo="US",
            historical_start=date(2024, 1, 1),
            historical_end=date(2024, 12, 31),
            baseline_start=date(2024, 1, 1),
            baseline_end=date(2024, 12, 31),
        )
    )
    config.design.day_offsets = [0, 1, 7]
    config.design.streams = ["A", "B", "C"]
    config.chunking.window_days = 120
    config.chunking.step_days = 30
    config.chunking.min_overlap_days = 14
    config.consensus.weight_cap = 0.6
    config.decision.min_unique_pulls = 3
    config.decision.min_spectral_effective_pulls = 1.0
    config.decision.min_level_generalizability = 0.0
    config.decision.min_innovation_generalizability = 0.0
    config.decision.max_benchmark_standardized_rmse = 10.0
    return config


def rmse(estimate: np.ndarray, truth: np.ndarray) -> float:
    ok = np.isfinite(estimate) & np.isfinite(truth)
    return float(np.sqrt(np.mean((estimate[ok] - truth[ok]) ** 2)))


def run() -> pd.DataFrame:
    config = build_config()
    records = []
    for label, fraction, weight in SCENARIOS:
        for seed in SEEDS:
            simulation = simulate_racergt_data(
                config,
                SimulationSettings(
                    random_seed=seed,
                    exact_duplicate_fraction=0.10,
                    cache_cluster_fraction=fraction,
                    cache_cluster_weight=weight,
                ),
            )
            result = RacerGTPipeline(config).fit(simulation.raw_chunks, simulation.benchmark)

            matrix = result.complete_pulls.pivot(
                index="historical_date", columns="pull_id", values="value"
            ).sort_index()
            matrix.index = pd.to_datetime(matrix.index)
            truth = simulation.truth.set_index(
                pd.to_datetime(simulation.truth["historical_date"])
            )["true_index"]
            common = matrix.index.intersection(truth.index)
            truth_values = truth.loc[common].to_numpy(dtype=float)
            sub = matrix.loc[common]

            consensus = result.consensus.consensus.copy()
            consensus.index = pd.to_datetime(consensus["historical_date"])

            weights = result.consensus.weights["weight"].to_numpy(dtype=float)
            records.append(
                {
                    "scenario": label,
                    "cache_fraction": fraction,
                    "cache_weight": weight,
                    "seed": seed,
                    "gls": rmse(consensus.loc[common, "value"].to_numpy(dtype=float), truth_values),
                    "simple_mean": rmse(sub.mean(axis=1).to_numpy(dtype=float), truth_values),
                    "median": rmse(sub.median(axis=1).to_numpy(dtype=float), truth_values),
                    # How far the fitted weights depart from equal weighting. If GLS
                    # cannot distinguish the pulls, this is ~0 and it must tie.
                    "weight_dispersion": float(np.std(weights, ddof=1)),
                    "spectral_effective": result.consensus.diagnostics["spectral_effective_pulls"],
                    "n_pulls": int(sub.shape[1]),
                }
            )
    return pd.DataFrame(records)


def diagnose(scenario: str = "cache_third_strong", n_seeds: int = 10) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Two follow-ups that decide how a negative result should be read.

    If the covariance adjustment loses, there are three candidate explanations:
    the constraints bind and prevent it from exploiting the structure, the
    mechanism fails to find the structure at all, or it finds the structure but
    the noise in estimating Sigma exceeds the efficiency it buys. The first two
    are checked directly here so that the third is a conclusion rather than an
    assumption.
    """

    config = build_config()
    _, fraction, weight = next(s for s in SCENARIOS if s[0] == scenario)
    variants = {
        "constrained_lw": {"covariance": "ledoit_wolf", "nonnegative_weights": True, "weight_cap": 0.6},
        "uncapped_lw": {"covariance": "ledoit_wolf", "nonnegative_weights": True, "weight_cap": None},
        "unrestricted_lw": {"covariance": "ledoit_wolf", "nonnegative_weights": False, "weight_cap": None},
        "unrestricted_empirical": {"covariance": "empirical", "nonnegative_weights": False, "weight_cap": None},
        "diagonal": {"covariance": "diagonal", "nonnegative_weights": True, "weight_cap": 0.6},
    }

    variant_rows, alignment_rows = [], []
    for seed in range(SEEDS[0], SEEDS[0] + n_seeds):
        simulation = simulate_racergt_data(
            config,
            SimulationSettings(
                random_seed=seed,
                exact_duplicate_fraction=0.10,
                cache_cluster_fraction=fraction,
                cache_cluster_weight=weight,
            ),
        )
        result = RacerGTPipeline(config).fit(simulation.raw_chunks, simulation.benchmark)
        matrix = result.complete_pulls.pivot(
            index="historical_date", columns="pull_id", values="value"
        ).sort_index()
        matrix.index = pd.to_datetime(matrix.index)
        truth = simulation.truth.set_index(
            pd.to_datetime(simulation.truth["historical_date"])
        )["true_index"]
        common = matrix.index.intersection(truth.index)
        truth_values = truth.loc[common].to_numpy(dtype=float)
        sub = matrix.loc[common]

        row = {"seed": seed, "simple_mean": rmse(sub.mean(axis=1).to_numpy(dtype=float), truth_values)}
        for name, overrides in variants.items():
            variant_config = config.model_copy(deep=True)
            for key, value in overrides.items():
                setattr(variant_config.consensus, key, value)
            estimate = fit_gls_consensus(
                matrix,
                variant_config.consensus,
                baseline_start=config.query.baseline_start,
                baseline_end=config.query.baseline_end,
            )
            row[name] = rmse(estimate.consensus["value"].to_numpy(dtype=float), truth_values)
        variant_rows.append(row)

        # Does the weight actually fall on the pulls that share dependence? A
        # negative correlation means the mechanism is working as designed.
        correlation = result.consensus.residual_matrix.corr().to_numpy(dtype=float).copy()
        np.fill_diagonal(correlation, np.nan)
        mean_correlation = pd.Series(
            np.nanmean(correlation, axis=1), index=result.consensus.residual_matrix.columns
        )
        fitted = result.consensus.weights.set_index("pull_id")["weight"]
        shared = [p for p in mean_correlation.index if p in fitted.index]
        alignment_rows.append(
            {
                "seed": seed,
                "corr_meanresidcorr_vs_weight": float(
                    np.corrcoef(mean_correlation.loc[shared], fitted.loc[shared])[0, 1]
                ),
            }
        )
    return pd.DataFrame(variant_rows), pd.DataFrame(alignment_rows)


def summarize(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows, tests = [], []
    for label, _fraction, _weight in SCENARIOS:
        part = frame[frame["scenario"] == label]
        difference = part["simple_mean"] - part["gls"]
        t_stat, p_value = stats.ttest_rel(part["simple_mean"], part["gls"])
        rows.append(
            {
                "scenario": label,
                "gls_rmse": part["gls"].mean(),
                "simple_mean_rmse": part["simple_mean"].mean(),
                "median_rmse": part["median"].mean(),
                "gls_advantage": difference.mean(),
                "mcse": difference.std(ddof=1) / np.sqrt(len(difference)),
                "weight_dispersion": part["weight_dispersion"].mean(),
                "spectral_effective": part["spectral_effective"].mean(),
            }
        )
        tests.append(
            {
                "scenario": label,
                "mean_difference": float(difference.mean()),
                "t_statistic": float(t_stat),
                "p_value": float(p_value),
                "gls_wins": int((difference > 0).sum()),
                "n": len(difference),
            }
        )
    return pd.DataFrame(rows), pd.DataFrame(tests)


if __name__ == "__main__":
    metrics = run()
    summary, paired = summarize(metrics)
    variants, alignment = diagnose()

    out = Path("dependence_experiment")
    out.mkdir(exist_ok=True)
    metrics.to_csv(out / "replication_metrics.csv", index=False)
    summary.to_csv(out / "summary.csv", index=False)
    paired.to_csv(out / "paired_tests.csv", index=False)
    variants.to_csv(out / "estimator_variants.csv", index=False)
    alignment.to_csv(out / "weight_alignment.csv", index=False)

    pd.set_option("display.width", 150)
    print("Mean RMSE by scenario (positive advantage favours GLS over the simple mean)")
    print(summary.to_string(index=False, float_format=lambda v: f"{v:.4f}"))
    print()
    print("Paired tests, GLS versus simple mean")
    print(paired.to_string(index=False, float_format=lambda v: f"{v:.4f}"))
    print()
    print("Diagnostic 1 -- do the constraints explain the loss? (cache_third_strong)")
    means = variants.drop(columns=["seed"]).mean()
    for name, value in means.items():
        marker = "  <- baseline" if name == "simple_mean" else ""
        print(f"  {name:24s} {value:.4f}{marker}")
    print()
    print("Diagnostic 2 -- does the weight fall on the dependent pulls?")
    correlations = alignment["corr_meanresidcorr_vs_weight"]
    print(
        f"  corr(mean residual correlation, GLS weight) = {correlations.mean():+.3f} "
        f"(n={len(correlations)}, all negative: {bool((correlations < 0).all())})"
    )
