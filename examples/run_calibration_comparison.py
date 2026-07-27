"""Does global overlap-graph calibration beat sequential stitching?

The manuscript's failure mode F1 argues that sequential stitching accumulates
scale error along the chain of joins, and that solving all overlaps jointly
avoids it. That is the core technical claim of the calibration stage, and until
now it was argued rather than measured.

Both methods run on the same raw chunks with the same edge estimator, the same
minimum-value gate, and the same baseline normalization. The only difference is
that one walks a spanning path and the other solves the whole graph. Two
questions are asked:

  1. Does the graph win on reconstruction error, and does the margin grow with
     the number of joins? F1 predicts it should.
  2. Does sequential error grow along the chain? F1's mechanism predicts that a
     chunk's error should increase with its position, while the graph's should
     not.

    PYTHONPATH=src python examples/run_calibration_comparison.py
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

from racergt.baselines import sequential_stitch
from racergt.config import QuerySpec, RacerGTConfig
from racergt.overlap import OverlapGraphCalibrator
from racergt.schema import coerce_raw_chunks
from racergt.simulation import SimulationSettings, simulate_racergt_data

# Step size controls how many chunks span the year, hence the chain length.
# Smaller steps mean more joins for sequential stitching to accumulate through.
# The last arm cuts retrieval noise. At the default level a single pull's error is
# dominated by day/stream/idiosyncratic disturbance, which can drown a difference
# in calibration; shrinking it lets calibration error carry a larger share of the
# total, which is the regime where F1's mechanism should matter most.
CHUNK_DESIGNS = [
    ("60-day step", 60, 0.06),
    ("30-day step", 30, 0.06),
    ("15-day step", 15, 0.06),
    ("15-day step, low noise", 15, 0.01),
]
SEEDS = list(range(1200, 1220))


def build_config(step_days: int) -> RacerGTConfig:
    config = RacerGTConfig(
        query=QuerySpec(
            series_id="cal",
            keyword="synthetic attention",
            geo="US",
            historical_start=date(2024, 1, 1),
            historical_end=date(2024, 12, 31),
            baseline_start=date(2024, 1, 1),
            baseline_end=date(2024, 12, 31),
        )
    )
    config.design.day_offsets = [0]
    config.design.streams = ["A", "B"]
    config.chunking.window_days = 120
    config.chunking.step_days = step_days
    config.chunking.min_overlap_days = 14
    return config


def _align(frame: pd.DataFrame, truth: pd.Series) -> tuple[np.ndarray, np.ndarray]:
    indexed = frame.set_index(pd.to_datetime(frame["historical_date"]))["value"]
    common = indexed.index.intersection(truth.index)
    return (
        indexed.loc[common].to_numpy(dtype=float),
        truth.loc[common].to_numpy(dtype=float),
    )


def rmse(estimate: np.ndarray, truth: np.ndarray) -> float:
    ok = np.isfinite(estimate) & np.isfinite(truth)
    return float(np.sqrt(np.mean((estimate[ok] - truth[ok]) ** 2)))


def compare() -> tuple[pd.DataFrame, pd.DataFrame]:
    rows, position_rows = [], []
    for label, step, noise in CHUNK_DESIGNS:
        config = build_config(step)
        for seed in SEEDS:
            simulation = simulate_racergt_data(
                config,
                SimulationSettings(
                    random_seed=seed,
                    exact_duplicate_fraction=0.0,
                    retrieval_noise_sd=noise,
                ),
            )
            data = coerce_raw_chunks(simulation.raw_chunks)
            truth = simulation.truth.set_index(
                pd.to_datetime(simulation.truth["historical_date"])
            )["true_index"]

            for pull_id in sorted(data["pull_id"].unique()):
                one = data[data["pull_id"] == pull_id]
                graph = OverlapGraphCalibrator(
                    config.calibration, min_overlap_days=config.chunking.min_overlap_days
                ).fit(
                    one,
                    baseline_start=config.query.baseline_start,
                    baseline_end=config.query.baseline_end,
                )
                stitched = sequential_stitch(
                    one,
                    config.calibration,
                    min_overlap_days=config.chunking.min_overlap_days,
                    baseline_start=config.query.baseline_start,
                    baseline_end=config.query.baseline_end,
                )

                graph_values, truth_values = _align(graph.full_series, truth)
                stitch_values, _ = _align(stitched.full_series, truth)
                rows.append(
                    {
                        "design": label,
                        "step_days": step,
                        "retrieval_noise_sd": noise,
                        "seed": seed,
                        "pull_id": pull_id,
                        "chain_length": stitched.diagnostics["chain_length"],
                        "graph": rmse(graph_values, truth_values),
                        "sequential": rmse(stitch_values, truth_values),
                    }
                )

                # F1's mechanism: does a chunk's scale error grow with its position
                # in the chain? Compare each method's recovered log scale against
                # the scale implied by the first chunk's own normalization.
                for method, scales in (("graph", graph.chunk_scales), ("sequential", stitched.chunk_scales)):
                    ordered = (
                        one.groupby("chunk_id")["window_start"].min().sort_values().index.astype(str)
                    )
                    table = scales.set_index(scales["chunk_id"].astype(str))["log_scale"]
                    for position, chunk_id in enumerate(ordered):
                        if chunk_id in table.index:
                            position_rows.append(
                                {
                                    "design": label,
                                    "seed": seed,
                                    "pull_id": pull_id,
                                    "method": method,
                                    "position": position,
                                    "log_scale": float(table.loc[chunk_id]),
                                }
                            )
    return pd.DataFrame(rows), pd.DataFrame(position_rows)


def summarize(frame: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for label, _step, _noise in CHUNK_DESIGNS:
        part = frame[frame["design"] == label]
        difference = part["sequential"] - part["graph"]
        t_stat, p_value = stats.ttest_rel(part["sequential"], part["graph"])
        rows.append(
            {
                "design": label,
                "chain_length": part["chain_length"].iloc[0],
                "graph_rmse": part["graph"].mean(),
                "sequential_rmse": part["sequential"].mean(),
                "graph_advantage": difference.mean(),
                "mcse": difference.std(ddof=1) / np.sqrt(len(difference)),
                "t": t_stat,
                "p": p_value,
                "graph_wins": int((difference > 0).sum()),
                "n": len(difference),
            }
        )
    return pd.DataFrame(rows)


if __name__ == "__main__":
    metrics, positions = compare()
    summary = summarize(metrics)

    out = Path("calibration_comparison")
    out.mkdir(exist_ok=True)
    metrics.to_csv(out / "replication_metrics.csv", index=False)
    positions.to_csv(out / "chunk_positions.csv", index=False)
    summary.to_csv(out / "summary.csv", index=False)

    pd.set_option("display.width", 150)
    print("Global overlap graph versus sequential stitching")
    print("(advantage is sequential minus graph, so positive favours the graph)\n")
    print(summary.to_string(index=False, float_format=lambda v: f"{v:.4f}"))

    print()
    print("F1's mechanism: does scale error grow along the chain?")
    print("Standard deviation of recovered log scale by position in the chain:\n")
    densest = "15-day step"
    subset = positions[positions["design"] == densest]
    spread = subset.groupby(["method", "position"])["log_scale"].std().unstack(0)
    early = spread.head(3).mean()
    late = spread.tail(3).mean()
    print(f"  design: {densest}")
    print(f"  first three positions : graph {early['graph']:.4f}   sequential {early['sequential']:.4f}")
    print(f"  last three positions  : graph {late['graph']:.4f}   sequential {late['sequential']:.4f}")
    for method in ("graph", "sequential"):
        growth = late[method] / early[method] if early[method] > 0 else float("nan")
        print(f"  {method:11s} late/early ratio = {growth:.2f}")
