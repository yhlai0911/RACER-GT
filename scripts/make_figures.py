"""Regenerate the manuscript figures from the recorded Monte Carlo results.

The figures used to be produced by hand, which meant nothing tied them to the
numbers in monte_carlo_results/. Running this script after
`python examples/run_monte_carlo.py` keeps the plots, the tables, and the CSV
outputs consistent by construction.

    python scripts/make_figures.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "monte_carlo_results" / "summary.csv"
FIGURES = ROOT / "docs" / "latex" / "figures"

# Display order and labels. Each estimator appears twice, once per information set.
ESTIMATORS = [
    ("single_pull", "Single pull"),
    ("cross_pull_median", "Cross-pull median"),
    ("simple_mean", "Simple mean"),
    ("RACER_GT", "RACER-GT"),
]
UNBENCHMARKED_COLOR = "#4C72B0"
BENCHMARKED_COLOR = "#DD8452"


def load_summary() -> pd.DataFrame:
    if not RESULTS.exists():
        sys.exit(f"{RESULTS} not found. Run examples/run_monte_carlo.py first.")
    return pd.read_csv(RESULTS).set_index("estimator")


def _paired_values(summary: pd.DataFrame, column: str) -> tuple[list[float], list[float]]:
    plain = [float(summary.loc[key, column]) for key, _ in ESTIMATORS]
    benched = [float(summary.loc[f"{key}_benchmarked", column]) for key, _ in ESTIMATORS]
    return plain, benched


def figure_rmse(summary: pd.DataFrame) -> None:
    """RMSE by estimator, split by information set, with Monte Carlo error bars."""

    labels = [label for _, label in ESTIMATORS]
    plain, benched = _paired_values(summary, "mean_rmse")
    plain_err, benched_err = _paired_values(summary, "mcse_rmse")

    positions = range(len(labels))
    width = 0.38
    fig, ax = plt.subplots(figsize=(7.4, 4.2))
    ax.bar(
        [p - width / 2 for p in positions], plain, width, yerr=plain_err, capsize=3,
        label="Pulls only", color=UNBENCHMARKED_COLOR,
    )
    ax.bar(
        [p + width / 2 for p in positions], benched, width, yerr=benched_err, capsize=3,
        label="With weekly/monthly benchmark", color=BENCHMARKED_COLOR,
    )
    for position, (low, high) in enumerate(zip(plain, benched, strict=True)):
        ax.text(position - width / 2, low + 0.12, f"{low:.3f}", ha="center", fontsize=8)
        ax.text(position + width / 2, high + 0.12, f"{high:.3f}", ha="center", fontsize=8)

    ax.set_xticks(list(positions))
    ax.set_xticklabels(labels)
    ax.set_ylabel("Mean RMSE against latent truth")
    ax.set_title("Reconstruction error by estimator and information set (20 replications)")
    ax.legend(frameon=False)
    ax.spines[["top", "right"]].set_visible(False)
    ax.set_ylim(0, max(plain) * 1.18)
    fig.tight_layout()
    for suffix in ("pdf", "png"):
        fig.savefig(FIGURES / f"monte_carlo_rmse.{suffix}", dpi=200)
    plt.close(fig)


def figure_signal(summary: pd.DataFrame) -> None:
    """Level correlation, innovation correlation, and top-5% peak recall."""

    metrics = [
        ("mean_correlation", "Level correlation"),
        ("mean_innovation_correlation", "Innovation correlation"),
        ("mean_peak_recall", "Top-5% peak recall"),
    ]
    labels = [label for _, label in ESTIMATORS]
    fig, axes = plt.subplots(1, 3, figsize=(11.2, 3.8))
    for axis, (column, title) in zip(axes, metrics, strict=True):
        plain, benched = _paired_values(summary, column)
        positions = range(len(labels))
        width = 0.38
        axis.bar(
            [p - width / 2 for p in positions], plain, width,
            label="Pulls only", color=UNBENCHMARKED_COLOR,
        )
        axis.bar(
            [p + width / 2 for p in positions], benched, width,
            label="Benchmarked", color=BENCHMARKED_COLOR,
        )
        axis.set_xticks(list(positions))
        axis.set_xticklabels(labels, rotation=30, ha="right", fontsize=8)
        axis.set_title(title, fontsize=10)
        axis.spines[["top", "right"]].set_visible(False)
        lowest = min(min(plain), min(benched))
        axis.set_ylim(max(0.0, lowest - 0.05), 1.005)
    axes[0].set_ylabel("Mean across replications")
    axes[-1].legend(frameon=False, fontsize=8, loc="lower right")
    fig.tight_layout()
    for suffix in ("pdf", "png"):
        fig.savefig(FIGURES / f"monte_carlo_signal.{suffix}", dpi=200)
    plt.close(fig)


def main() -> None:
    summary = load_summary()
    missing = [
        name
        for key, _ in ESTIMATORS
        for name in (key, f"{key}_benchmarked")
        if name not in summary.index
    ]
    if missing:
        sys.exit(
            f"summary.csv is missing {missing}. Rerun examples/run_monte_carlo.py with "
            "a version of validation.py that reports both information sets."
        )
    FIGURES.mkdir(parents=True, exist_ok=True)
    figure_rmse(summary)
    figure_signal(summary)
    print(f"wrote monte_carlo_rmse and monte_carlo_signal (pdf, png) to {FIGURES}")


if __name__ == "__main__":
    main()
