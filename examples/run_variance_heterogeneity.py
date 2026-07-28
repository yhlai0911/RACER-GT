"""Does covariance adjustment pay when the pulls differ in variance?

The headline Monte Carlo answers no, but its data-generating process gives every
pull the same error structure, so the minimum-variance weights are equal weights
by construction and there is nothing for the adjustment to exploit. The existing
heterogeneity experiment varies how pulls covary, not how noisy they are.

This script varies the noise. `retrieval_noise_ladder` is the ratio of the largest
to the smallest retrieval-noise standard deviation, spread geometrically with
geometric mean one, so the noise budget moves between pulls rather than growing.
A ladder of 1.0 reproduces the default exactly.

The last scenario is a control, not a result. It restores homogeneous variances
and introduces correlation heterogeneity instead, where the covariance-adjusted
estimator is known to lose. A comparison that cannot show RACER-GT losing is not
evidence that it wins, so the control runs on every invocation.
"""

from datetime import date
from pathlib import Path

import pandas as pd

from racergt.config import QuerySpec, RacerGTConfig
from racergt.simulation import SimulationSettings
from racergt.validation import run_monte_carlo

REPLICATIONS = 20
FIRST_SEED = 1200

SCENARIOS = [
    ("homogeneous", "default: every pull shares one error structure", {}),
    ("ladder_5", "sd ratio 5, variance ratio 25", {"retrieval_noise_ladder": 5.0}),
    ("ladder_10", "sd ratio 10, variance ratio 100", {"retrieval_noise_ladder": 10.0}),
    ("ladder_20", "sd ratio 20, variance ratio 400", {"retrieval_noise_ladder": 20.0}),
    (
        "control_correlation_only",
        "homogeneous variances, shared cache disturbance",
        {"cache_cluster_fraction": 0.33, "cache_cluster_weight": 0.60},
    ),
]

config = RacerGTConfig(
    query=QuerySpec(
        series_id="mc",
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

rows = []
for name, description, overrides in SCENARIOS:
    result = run_monte_carlo(
        config,
        replications=REPLICATIONS,
        first_seed=FIRST_SEED,
        settings=SimulationSettings(exact_duplicate_fraction=0.10, **overrides),
    )
    summary = result.summary.set_index("estimator")
    paired = result.paired_tests
    versus_mean = paired[
        (paired["estimator"] == "RACER_GT") & (paired["reference"] == "simple_mean")
    ].iloc[0]
    ladder = float(overrides.get("retrieval_noise_ladder", 1.0))
    rows.append(
        {
            "scenario": name,
            "description": description,
            "true_variance_ratio": ladder**2,
            "racer_gt_rmse": float(summary.loc["RACER_GT", "mean_rmse"]),
            "simple_mean_rmse": float(summary.loc["simple_mean", "mean_rmse"]),
            "cross_pull_median_rmse": float(summary.loc["cross_pull_median", "mean_rmse"]),
            "single_pull_rmse": float(summary.loc["single_pull", "mean_rmse"]),
            "advantage": float(versus_mean["mean_rmse_difference"]),
            "t_p_value": float(versus_mean["t_p_value"]),
            "wins": int(versus_mean["wins"]),
            "n_replications": REPLICATIONS,
        }
    )

table = pd.DataFrame(rows)
output = Path("monte_carlo_results")
output.mkdir(exist_ok=True)
table.to_csv(output / "variance_heterogeneity.csv", index=False)

print("Advantage is simple-mean RMSE minus RACER-GT RMSE; positive favours RACER-GT.")
print(
    table[
        [
            "scenario",
            "true_variance_ratio",
            "racer_gt_rmse",
            "simple_mean_rmse",
            "advantage",
            "t_p_value",
            "wins",
        ]
    ].to_string(index=False)
)
print()
print(f"Wrote {output / 'variance_heterogeneity.csv'}")
