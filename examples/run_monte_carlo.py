from datetime import date
from pathlib import Path

from racergt.config import QuerySpec, RacerGTConfig
from racergt.validation import run_monte_carlo

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

result = run_monte_carlo(config, replications=20, first_seed=1200)
out = Path("monte_carlo_results")
out.mkdir(exist_ok=True)
result.metrics.to_csv(out / "replication_metrics.csv", index=False)
result.summary.to_csv(out / "summary.csv", index=False)
result.paired_tests.to_csv(out / "paired_tests.csv", index=False)

print("Mean RMSE by estimator and information set")
print(
    result.summary[
        ["estimator", "benchmarked", "mean_rmse", "sd_rmse", "mcse_rmse", "mean_bias"]
    ].to_string(index=False)
)
print()
print("Paired comparisons (positive difference favours the first estimator)")
print(
    result.paired_tests[
        ["estimator", "reference", "comparison", "mean_rmse_difference", "t_p_value", "wins"]
    ].to_string(index=False)
)
