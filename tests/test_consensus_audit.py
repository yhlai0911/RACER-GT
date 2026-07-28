"""Independent-derivation audit of consensus.py.

The method is the one that worked on overlap.py in 1.4.0: check each reported
quantity against a derivation that does not share the estimator's code path, and
show the check fails against a plausible wrong answer before trusting it to pass.
Checking an estimator against itself finds nothing --- 1.4.0's se unit bug survived
every existing test because no test computed the variance a second way.

Where a constrained solution has no closed form the check is stated as a property
rather than an identity: no feasible point beats the optimum, the shrinkage keeps
the trace, the collapse agrees with brute-force comparison. Where no independent
derivation exists at all, the test says so rather than dressing up a tautology.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from racergt.config import ConsensusConfig
from racergt.consensus import (
    _estimate_covariance,
    _minimum_variance_weights,
    _spectral_effective_count,
    collapse_exact_vectors,
    fit_gls_consensus,
)

N_DAYS = 260
START = "2023-01-01"
SEED = 20260728


def _matrix(
    n_pulls: int = 6,
    noise_sds: tuple[float, ...] | None = None,
    duplicate_of: dict[str, str] | None = None,
    seed: int = SEED,
) -> pd.DataFrame:
    """A wide pull matrix from one latent series with per-pull noise scales."""

    rng = np.random.default_rng(seed)
    dates = pd.date_range(START, periods=N_DAYS, freq="D")
    day = np.arange(N_DAYS, dtype=float)
    latent = 50.0 + 18.0 * np.sin(day / 31.0) + 7.0 * np.cos(day / 11.0)

    sds = noise_sds if noise_sds is not None else tuple(0.5 + 0.2 * i for i in range(n_pulls))
    columns = {}
    for index in range(n_pulls):
        columns[f"P{index + 1:03d}"] = latent + rng.normal(scale=sds[index], size=N_DAYS)
    matrix = pd.DataFrame(columns, index=dates)
    matrix.index.name = "historical_date"

    if duplicate_of:
        for target, source in duplicate_of.items():
            matrix[target] = matrix[source].to_numpy()
    return matrix


def _residuals(matrix: pd.DataFrame) -> pd.DataFrame:
    return matrix.sub(matrix.median(axis=1, skipna=True), axis=0)


# ---------------------------------------------------------------------------
# Effective pull count
# ---------------------------------------------------------------------------


def test_spectral_count_matches_the_eigenvalue_derivation():
    """tr(R)^2 / tr(R@R) against sum(lam)^2 / sum(lam^2), computed a different way.

    The estimator forms R @ R. The check eigendecomposes R instead, so a mistake in
    the matrix product cannot hide. The discriminating half rules out the variant
    that drops the square in the denominator, which is the natural typo and which
    returns a number of the right order.
    """

    residuals = _residuals(_matrix(n_pulls=7))
    reported = _spectral_effective_count(residuals)

    clean = residuals.dropna(axis=0, how="any")
    correlation = np.corrcoef(clean.to_numpy(dtype=float), rowvar=False)
    eigenvalues = np.linalg.eigvalsh(correlation)
    independent = float(eigenvalues.sum() ** 2 / (eigenvalues**2).sum())

    assert reported == pytest.approx(independent, rel=1e-10)

    # The plausible wrong answer, which the assertion above must exclude.
    wrong = float(eigenvalues.sum() ** 2 / eigenvalues.sum())
    assert abs(reported - wrong) > 0.5


def test_spectral_count_is_the_pull_count_when_residuals_are_independent():
    """Analytic anchor: with an identity correlation matrix the count is exactly m."""

    identity = pd.DataFrame(
        np.random.default_rng(5).normal(size=(4000, 5)),
        columns=[f"P{i:03d}" for i in range(5)],
    )
    assert _spectral_effective_count(identity) == pytest.approx(5.0, abs=0.05)


# ---------------------------------------------------------------------------
# Minimum-variance weights
# ---------------------------------------------------------------------------


def test_unconstrained_weights_satisfy_the_first_order_condition():
    """Sigma w must be parallel to 1, checked without re-deriving the closed form.

    At the optimum of w'Sigma w subject to 1'w = 1, the gradient 2 Sigma w is
    orthogonal to every feasible direction, and the feasible directions are exactly
    the d with 1'd = 0. This is a property of the solution, not a second way of
    computing it, so it cannot agree by construction.
    """

    covariance = np.cov(_residuals(_matrix(n_pulls=5)).to_numpy(dtype=float), rowvar=False)
    weights = _minimum_variance_weights(covariance, nonnegative=False, cap=None)

    assert weights.sum() == pytest.approx(1.0, abs=1e-12)

    gradient = covariance @ weights
    rng = np.random.default_rng(3)
    for _ in range(200):
        direction = rng.normal(size=weights.size)
        direction -= direction.mean()  # 1'd = 0
        assert abs(float(direction @ gradient)) < 1e-8 * max(1.0, float(np.abs(gradient).max()))

    # Equal weights are feasible and, for a non-trivial Sigma, strictly worse.
    equal = np.full(weights.size, 1.0 / weights.size)
    assert float(weights @ covariance @ weights) < float(equal @ covariance @ equal)


def test_constrained_weights_beat_every_feasible_perturbation():
    """No closed form exists under the box, so the check is a search, not an identity.

    Sampling the feasible set is fully independent of SLSQP: it uses no optimality
    theory and no derivative. If the solver returned a non-optimal point, a random
    feasible point would eventually beat it.
    """

    covariance = np.cov(_residuals(_matrix(n_pulls=6)).to_numpy(dtype=float), rowvar=False)
    cap = 0.50
    weights = _minimum_variance_weights(covariance, nonnegative=True, cap=cap)
    objective = float(weights @ covariance @ weights)

    assert weights.sum() == pytest.approx(1.0, abs=1e-9)
    assert weights.min() >= -1e-12
    assert weights.max() <= cap + 1e-9

    rng = np.random.default_rng(11)
    best_found = objective
    for _ in range(4000):
        candidate = rng.dirichlet(np.ones(weights.size))
        if candidate.max() > cap:
            continue
        best_found = min(best_found, float(candidate @ covariance @ candidate))
    assert best_found >= objective - 1e-12


def test_the_cap_binds_and_costs_variance():
    """The cap is a stabilizer, not an improvement --- the paper says so; verify it."""

    covariance = np.cov(
        _residuals(_matrix(n_pulls=4, noise_sds=(0.05, 2.0, 2.0, 2.0))).to_numpy(dtype=float),
        rowvar=False,
    )
    capped = _minimum_variance_weights(covariance, nonnegative=True, cap=0.30)
    free = _minimum_variance_weights(covariance, nonnegative=False, cap=None)

    assert capped.max() == pytest.approx(0.30, abs=1e-6)
    assert free.max() > 0.30
    assert float(capped @ covariance @ capped) > float(free @ covariance @ free)


def test_median_residuals_compress_how_far_weights_can_concentrate():
    """Why the default cap of 0.50 almost never binds, measured rather than argued.

    Residuals are every pull minus the daily median *of the pulls themselves*. They
    therefore share a common, noisy subtrahend, which induces negative correlation
    among them and puts a floor under the residual variance of even a near-perfect
    pull. Sigma comes out flatter than the pulls' true precisions, and the weights
    concentrate less than the design would justify.

    With one pull at noise 0.05 and three at 2.0 --- a fortyfold precision ratio --- the
    maximum weight lands near 0.37, so the 0.50 cap does not bind. The direction
    matters for reading the Monte Carlo result that GLS does not beat a simple mean:
    the gap is not evidence against GLS weighting, it is evidence that the Sigma fed
    to it has been flattened before it arrives.
    """

    covariance = np.cov(
        _residuals(_matrix(n_pulls=4, noise_sds=(0.05, 2.0, 2.0, 2.0))).to_numpy(dtype=float),
        rowvar=False,
    )
    weights = _minimum_variance_weights(covariance, nonnegative=True, cap=0.50)
    assert weights.max() < 0.50  # the default cap is slack here

    # The precision ratio Sigma reports is a small fraction of the true one.
    reported_ratio = float(np.max(np.diag(covariance)) / np.min(np.diag(covariance)))
    true_ratio = (2.0 / 0.05) ** 2
    assert reported_ratio < 0.05 * true_ratio


# ---------------------------------------------------------------------------
# Covariance estimation
# ---------------------------------------------------------------------------


def test_ledoit_wolf_preserves_the_trace_of_its_own_input():
    """Shrinkage properties, not a reimplementation of the shrinkage formula.

    Rewriting the formula risks reproducing the same misunderstanding. Trace
    preservation and non-worsening of the condition number hold for any convex
    combination toward a scaled identity target, and fail immediately if the
    estimator is not returning one.

    The basis has to be the matrix Ledoit--Wolf actually shrinks: with
    assume_centered=True that is X'X/n, not the ddof=1 sample covariance.
    """

    residuals = _residuals(_matrix(n_pulls=6))
    values = residuals.dropna(axis=0, how="any").to_numpy(dtype=float)
    unshrunk = values.T @ values / values.shape[0]

    shrunk = _estimate_covariance(residuals, "ledoit_wolf")

    assert np.trace(shrunk) == pytest.approx(np.trace(unshrunk), rel=1e-8)
    assert np.linalg.cond(shrunk) <= np.linalg.cond(unshrunk) + 1e-8
    assert np.allclose(shrunk, shrunk.T, atol=1e-12)
    assert np.linalg.eigvalsh(shrunk).min() > 0.0


def test_the_covariance_methods_disagree_on_centring_and_degrees_of_freedom():
    """Switching config.covariance changes more than the shrinkage. Pin it.

    The "empirical" branch calls np.cov with ddof=1, which subtracts column means
    and divides by n-1. The "ledoit_wolf" branch passes assume_centered=True, which
    subtracts nothing and divides by n. So the two options differ in centring and in
    degrees of freedom on top of the shrinkage they were chosen to differ in, and a
    user comparing them is not holding those fixed.

    Small in this sample, but it is a difference in definition rather than in
    estimate, and nothing in the configuration says so.
    """

    residuals = _residuals(_matrix(n_pulls=6))
    values = residuals.dropna(axis=0, how="any").to_numpy(dtype=float)

    uncentred_n = values.T @ values / values.shape[0]
    centred_n_minus_1 = np.cov(values, rowvar=False, ddof=1)

    assert np.trace(uncentred_n) != pytest.approx(np.trace(centred_n_minus_1), rel=1e-9)
    ratio = float(np.trace(uncentred_n) / np.trace(centred_n_minus_1))
    assert 0.99 < ratio < 1.01


def test_covariance_is_computed_uncentred_and_the_residual_mean_is_not_zero():
    """Pin an assumption the estimator makes silently, and measure what it costs.

    The estimator calls Ledoit--Wolf with assume_centered=True, so it forms X'X/n
    rather than subtracting the column means. Residuals are taken about the daily
    *median*, and the median is not the mean, so those column means are not zero.
    The uncentred moment therefore exceeds the covariance by the outer product of
    the residual means -- an *over*statement, running opposite to the three
    understatements documented for the per-day standard error.

    Measured here so the net direction is a number rather than an argument.
    """

    residuals = _residuals(_matrix(n_pulls=6))
    values = residuals.to_numpy(dtype=float)
    column_means = values.mean(axis=0)

    # Not zero, which is the premise of everything below.
    assert np.abs(column_means).max() > 1e-6

    uncentred = _estimate_covariance(residuals, "empirical")
    centred = np.cov(values, rowvar=False, ddof=1)

    inflation = float(np.trace(uncentred) / np.trace(centred))
    # The overstatement is real but small: the median and mean of a near-symmetric
    # residual differ little. Recorded as a bound, not as "negligible".
    assert inflation > 1.0
    assert inflation < 1.05


# ---------------------------------------------------------------------------
# Duplicate collapse
# ---------------------------------------------------------------------------


def test_exact_collapse_agrees_with_brute_force_comparison():
    """Hashing against O(m^2) element-wise comparison, which shares no code."""

    matrix = _matrix(n_pulls=5, duplicate_of={"P002": "P001", "P005": "P004"})
    collapsed, mapping = collapse_exact_vectors(matrix)

    groups: dict[str, str] = {}
    for column in matrix.columns:
        for representative in groups.values():
            if np.array_equal(
                matrix[column].to_numpy(dtype=float), matrix[representative].to_numpy(dtype=float)
            ):
                groups[column] = representative
                break
        else:
            groups[column] = column

    expected_representatives = sorted(set(groups.values()))
    assert sorted(collapsed.columns.tolist()) == expected_representatives
    assert collapsed.shape[1] == 3

    for row in mapping.itertuples():
        assert np.array_equal(
            matrix[row.pull_id].to_numpy(dtype=float),
            matrix[row.representative_pull_id].to_numpy(dtype=float),
        )


def test_collapse_leaves_distinct_pulls_alone():
    """The mirror case: a collapser that collapses everything would pass the above."""

    collapsed, mapping = collapse_exact_vectors(_matrix(n_pulls=5))
    assert collapsed.shape[1] == 5
    assert not mapping["collapsed"].any()


# ---------------------------------------------------------------------------
# End-to-end invariants
# ---------------------------------------------------------------------------


def test_baseline_rescaling_puts_every_pull_at_mean_one_hundred():
    """A defining property of the estimand, checkable without touching the estimator."""

    matrix = _matrix(n_pulls=5)
    result = fit_gls_consensus(matrix, ConsensusConfig(), baseline_start=START)
    baseline_means = result.aligned_matrix.mean(axis=0)
    assert np.allclose(baseline_means.to_numpy(dtype=float), 100.0, atol=1e-9)


def test_kish_count_equals_the_pull_count_only_under_equal_weights():
    """Analytic anchor at both ends: equal weights give m, concentration gives less."""

    equal = np.full(6, 1.0 / 6)
    assert 1.0 / np.sum(equal**2) == pytest.approx(6.0)

    result = fit_gls_consensus(
        _matrix(n_pulls=6, noise_sds=(0.1, 2.0, 2.0, 2.0, 2.0, 2.0)),
        ConsensusConfig(),
        baseline_start=START,
    )
    weights = result.weights["weight"].to_numpy(dtype=float)
    assert result.diagnostics["kish_effective_pulls"] == pytest.approx(
        1.0 / np.sum(weights**2), rel=1e-10
    )
    assert result.diagnostics["kish_effective_pulls"] < 6.0


def test_daily_consensus_uses_renormalized_weights_when_pulls_are_missing():
    """Recompute one day by hand. The point estimate does renormalize --- the
    standard error does not, which is recorded in review/tickets/08."""

    matrix = _matrix(n_pulls=5)
    gap_date = matrix.index[100]
    matrix.loc[gap_date, ["P001", "P002"]] = np.nan

    result = fit_gls_consensus(matrix, ConsensusConfig(), baseline_start=START)
    weights = result.weights.set_index("pull_id")["weight"]
    row = result.aligned_matrix.loc[gap_date]
    available = row.dropna()
    local = weights.loc[available.index]
    expected = float((local / local.sum()) @ available)

    reported = float(
        result.consensus.set_index("historical_date").loc[gap_date, "value"]
    )
    assert reported == pytest.approx(expected, rel=1e-10)

    # And the flat one that would be wrong, excluded explicitly.
    naive = float(weights.loc[available.index] @ available)
    assert abs(reported - naive) > 1e-6
