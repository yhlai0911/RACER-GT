"""Independent-derivation audit of benchmark.py.

This stage decides `final_series`: when a benchmark is supplied the pipeline
returns the benchmarked result, so an error here reaches the published series
directly rather than sitting in a diagnostic. That is why it is audited ahead of
the position its priority suggests.

Each reported quantity is checked against a derivation that shares no code with
the estimator. Where the solution has a closed form the check is an identity;
where it does not, it is the optimality condition or a search over feasible
points, neither of which can agree by construction. Every check has a
discriminating half, because a check that passes on the right answer and on a
plausible wrong one establishes nothing.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from scipy import sparse

from racergt.benchmark import (
    _difference_penalty,
    build_aggregation_matrix,
    temporal_benchmark,
)
from racergt.config import BenchmarkConfig

N_DAYS = 364
START = "2024-01-01"


def _series(noise_sd: float = 3.0, seed: int = 5):
    """A daily preliminary series, its latent truth, and exact weekly means of it."""

    rng = np.random.default_rng(seed)
    dates = pd.date_range(START, periods=N_DAYS, freq="D")
    day = np.arange(N_DAYS, dtype=float)
    truth = 100.0 + 20.0 * np.sin(day / 29.0) + 8.0 * np.cos(day / 11.0)
    preliminary = pd.DataFrame(
        {"historical_date": dates, "value": truth + rng.normal(0.0, noise_sd, size=N_DAYS)}
    )

    rows = []
    for start in pd.date_range(START, periods=52, freq="W-MON"):
        end = start + pd.Timedelta(days=6)
        mask = (dates >= start) & (dates <= end)
        if mask.sum():
            rows.append(
                {"period_start": start, "period_end": end, "value": float(truth[mask].mean())}
            )
    return preliminary, pd.DataFrame(rows), truth, dates


# ---------------------------------------------------------------------------
# Building blocks
# ---------------------------------------------------------------------------


def test_difference_penalty_matches_the_explicit_tridiagonal():
    """D'D for a first-difference D is [1,2,...,2,1] on the diagonal, -1 beside it."""

    n = 7
    reported = _difference_penalty(n).toarray()

    expected = np.zeros((n, n))
    np.fill_diagonal(expected, 2.0)
    expected[0, 0] = expected[-1, -1] = 1.0
    for i in range(n - 1):
        expected[i, i + 1] = expected[i + 1, i] = -1.0

    assert np.allclose(reported, expected)
    # A constant vector has no first differences, so it must be in the null space.
    assert np.allclose(reported @ np.ones(n), 0.0, atol=1e-12)
    # And a linear ramp must not be, or the penalty is not penalising differences.
    assert np.linalg.norm(reported @ np.arange(n, dtype=float)) > 0.5


def test_aggregation_rows_are_period_means():
    """Each row of A must average its period, not sum it."""

    preliminary, benchmark, _truth, dates = _series()
    a, b, _se, retained = build_aggregation_matrix(dates, benchmark)

    assert np.allclose(np.asarray(a.sum(axis=1)).ravel(), 1.0)

    values = preliminary["value"].to_numpy(dtype=float)
    aggregated = np.asarray(a @ values)
    for index, row in retained.iterrows():
        mask = (dates >= row["period_start"]) & (dates <= row["period_end"])
        assert aggregated[index] == pytest.approx(values[mask].mean(), rel=1e-12)
    assert len(b) == len(retained)


# ---------------------------------------------------------------------------
# The two estimators
# ---------------------------------------------------------------------------


def test_exact_mode_satisfies_the_constraint_it_promises():
    """Ax = b to solver precision, checked on the returned series."""

    preliminary, benchmark, _truth, dates = _series()
    config = BenchmarkConfig(mode="exact", preserve_nonnegative=False)
    result = temporal_benchmark(preliminary, benchmark, config)

    a, b, _se, _retained = build_aggregation_matrix(dates, benchmark)
    x = result.series["value"].to_numpy(dtype=float)
    assert np.allclose(np.asarray(a @ x), b, atol=1e-8)

    # The preliminary series does not satisfy it, so the assertion has content.
    z = preliminary["value"].to_numpy(dtype=float)
    assert not np.allclose(np.asarray(a @ z), b, atol=1e-8)


def test_soft_mode_satisfies_the_first_order_condition():
    """The gradient of the soft objective vanishes at the returned correction.

    This is a property of the optimum rather than a second way to compute it, so
    it cannot agree with the estimator by construction.
    """

    preliminary, benchmark, _truth, dates = _series()
    config = BenchmarkConfig(mode="soft", preserve_nonnegative=False, default_benchmark_se=2.0)
    result = temporal_benchmark(preliminary, benchmark, config)

    z = preliminary["value"].to_numpy(dtype=float)
    delta = result.series["value"].to_numpy(dtype=float) - z
    a, b, _se, _retained = build_aggregation_matrix(dates, benchmark)
    n = len(z)
    q = (
        config.fidelity_weight * sparse.eye(n, format="csr")
        + config.smoothness_weight * _difference_penalty(n)
        + config.ridge * sparse.eye(n, format="csr")
    )
    w = sparse.diags(np.full(a.shape[0], 1.0 / config.default_benchmark_se**2), format="csr")
    discrepancy = b - np.asarray(a @ z)

    gradient = 2.0 * (q @ delta) + 2.0 * (a.T @ (w @ (a @ delta - discrepancy)))
    scale = float(np.abs(2.0 * (a.T @ (w @ discrepancy))).max())
    assert float(np.abs(gradient).max()) < 1e-6 * max(scale, 1.0)


def test_soft_solution_beats_random_feasible_perturbations():
    """A search, using no optimality theory and no derivative."""

    preliminary, benchmark, _truth, dates = _series()
    config = BenchmarkConfig(mode="soft", preserve_nonnegative=False)
    result = temporal_benchmark(preliminary, benchmark, config)

    z = preliminary["value"].to_numpy(dtype=float)
    delta = result.series["value"].to_numpy(dtype=float) - z
    a, b, _se, _retained = build_aggregation_matrix(dates, benchmark)
    n = len(z)
    q = (
        config.fidelity_weight * sparse.eye(n, format="csr")
        + config.smoothness_weight * _difference_penalty(n)
        + config.ridge * sparse.eye(n, format="csr")
    )
    w = sparse.diags(np.full(a.shape[0], 1.0 / config.default_benchmark_se**2), format="csr")
    discrepancy = b - np.asarray(a @ z)

    def objective(candidate: np.ndarray) -> float:
        misfit = np.asarray(a @ candidate) - discrepancy
        return float(candidate @ (q @ candidate) + misfit @ (w @ misfit))

    best = objective(delta)
    rng = np.random.default_rng(17)
    for scale in (1e-3, 1e-2, 1e-1):
        for _ in range(60):
            assert objective(delta + rng.normal(0.0, scale, size=n)) >= best - 1e-9


# ---------------------------------------------------------------------------
# Design choices that are easy to misread
# ---------------------------------------------------------------------------


def test_smoothness_penalises_the_correction_path_not_the_final_series():
    """Q multiplies (x - z), so raising it flattens the correction, not the output.

    Two estimators are being distinguished here. Penalising the differences of x
    would smooth the published series; penalising the differences of x - z leaves
    the day-to-day shape of the preliminary series intact and only spreads the
    benchmark adjustment. The manuscript describes the latter, so this pins it.
    """

    preliminary, benchmark, _truth, _dates = _series()
    z = preliminary["value"].to_numpy(dtype=float)

    def roughness(values: np.ndarray) -> float:
        return float(np.mean(np.diff(values) ** 2))

    flat = temporal_benchmark(preliminary, benchmark, BenchmarkConfig(smoothness_weight=0.0))
    heavy = temporal_benchmark(preliminary, benchmark, BenchmarkConfig(smoothness_weight=1000.0))

    flat_x = flat.series["value"].to_numpy(dtype=float)
    heavy_x = heavy.series["value"].to_numpy(dtype=float)

    # The correction path becomes much smoother.
    assert roughness(heavy_x - z) < 0.2 * roughness(flat_x - z)
    # The output series does not, because its roughness is inherited from z.
    assert roughness(heavy_x) == pytest.approx(roughness(flat_x), rel=0.05)


def test_more_smoothing_fits_the_benchmark_worse_not_better():
    """Direction, measured. Raising Q suppresses the correction, so the benchmark
    residual grows. The effect is small: over four orders of magnitude of
    smoothness_weight the benchmark RMSE moves about three percent, which is worth
    knowing before that constant is defended as a material choice."""

    preliminary, benchmark, truth, _dates = _series()

    fits = {}
    for weight in (0.0, 10.0, 1000.0):
        result = temporal_benchmark(
            preliminary, benchmark, BenchmarkConfig(smoothness_weight=weight)
        )
        fits[weight] = (
            result.diagnostics["benchmark_rmse"],
            result.diagnostics["mean_absolute_correction"],
            float(np.sqrt(np.mean((result.series["value"].to_numpy(dtype=float) - truth) ** 2))),
        )

    assert fits[0.0][0] < fits[10.0][0] < fits[1000.0][0]
    assert fits[0.0][1] > fits[10.0][1] > fits[1000.0][1]
    assert fits[1000.0][0] < 1.05 * fits[0.0][0]
    # And it does not help against the truth either, so it is not a hidden bias fix.
    assert fits[1000.0][2] > fits[0.0][2]


def test_default_benchmark_se_mechanically_moves_the_acceptance_key():
    """benchmark_standardized_rmse is what decision.py reads, and when the
    benchmark carries no standard error every constraint is assigned
    default_benchmark_se. The reported key is then the raw RMSE divided by a
    configuration constant with no statistical content, so the same data passes or
    fails on that constant alone. Larger is more permissive, which is the direction
    that favours accepting a batch."""

    preliminary, benchmark, _truth, _dates = _series()
    assert "se" not in benchmark.columns  # the situation this is about

    standardized = {}
    for default_se in (0.5, 1.0, 2.0, 4.0):
        result = temporal_benchmark(
            preliminary, benchmark, BenchmarkConfig(default_benchmark_se=default_se)
        )
        standardized[default_se] = result.diagnostics["benchmark_standardized_rmse"]

    assert standardized[0.5] > standardized[1.0] > standardized[2.0] > standardized[4.0]
    # The default threshold is 1.5. The same data crosses it inside this range.
    assert standardized[0.5] > 1.5
    assert standardized[2.0] < 1.5


def test_supplied_benchmark_standard_errors_override_the_default():
    """The constant only bites when the caller supplies nothing, so the escape
    hatch has to work or the previous test describes a trap with no exit."""

    preliminary, benchmark, _truth, _dates = _series()
    with_se = benchmark.copy()
    with_se["se"] = 0.5

    default = temporal_benchmark(preliminary, benchmark, BenchmarkConfig())
    supplied = temporal_benchmark(preliminary, with_se, BenchmarkConfig())

    assert supplied.diagnostics["benchmark_standardized_rmse"] > default.diagnostics[
        "benchmark_standardized_rmse"
    ]


def test_nonnegative_projection_breaks_the_exact_constraint_and_says_so():
    """Clipping happens after the solve, so exact mode stops satisfying Ax = b.

    That is defensible -- a negative search index is not a value Trends can produce
    -- but it means the constraint is a pre-clip property. The diagnostics flag it
    and the reported fit is computed on the clipped series, so the violation shows
    up in benchmark_rmse rather than being hidden by it.
    """

    dates = pd.date_range(START, periods=60, freq="D")
    preliminary = pd.DataFrame({"historical_date": dates, "value": np.full(60, 5.0)})
    # A benchmark far below zero forces the correction through the floor.
    benchmark = pd.DataFrame(
        [{"period_start": dates[0], "period_end": dates[-1], "value": -40.0}]
    )

    clipped = temporal_benchmark(
        preliminary, benchmark, BenchmarkConfig(mode="exact", preserve_nonnegative=True)
    )
    assert clipped.diagnostics["negative_values_before_clip"] > 0
    assert clipped.diagnostics["nonnegative_projection_used"] is True
    assert (clipped.series["value"].to_numpy(dtype=float) >= 0.0).all()
    # The violation is visible in the reported fit, not swallowed.
    assert clipped.diagnostics["benchmark_rmse"] > 1.0

    unclipped = temporal_benchmark(
        preliminary, benchmark, BenchmarkConfig(mode="exact", preserve_nonnegative=False)
    )
    assert unclipped.diagnostics["nonnegative_projection_used"] is False
    assert unclipped.diagnostics["benchmark_rmse"] < 1e-6
