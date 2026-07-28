"""The calibration standard error reaches the consensus, and what it says there.

Until now overlap.py computed a per-day standard error for every pull, its own
comment said it was "propagated into the downstream errors-in-variables
correction", 1.4.0 fixed a unit bug in it, and nothing downstream ever read it.
These tests hold the wiring in place and pin what the resulting diagnostic can and
cannot detect.

It is reported beside the consensus standard error rather than added to it. Sigma
is estimated from residuals that already contain calibration error, so a sum would
double count. What it buys is an independent lower bound: it comes from within-day
chunk disagreement through the delta method, a derivation that shares nothing with
the residual covariance, so days where it exceeds the consensus standard error are
days that estimate is too small.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from racergt.config import ConsensusConfig
from racergt.consensus import fit_gls_consensus

N_DAYS = 240
START = "2024-01-01"


def _matrix_and_calibration(
    n_pulls: int = 5,
    pull_noise_sd: float = 1.5,
    calibration_sd: float = 0.30,
    seed: int = 909,
):
    """A wide pull matrix with a matching per-day, per-pull calibration error."""

    rng = np.random.default_rng(seed)
    dates = pd.date_range(START, periods=N_DAYS, freq="D")
    day = np.arange(N_DAYS, dtype=float)
    latent = 100.0 + 20.0 * np.sin(day / 29.0) + 8.0 * np.cos(day / 11.0)

    values, errors = {}, {}
    for index in range(n_pulls):
        name = f"P{index + 1:03d}"
        values[name] = latent + rng.normal(0.0, pull_noise_sd, size=N_DAYS)
        errors[name] = np.full(N_DAYS, calibration_sd)
    matrix = pd.DataFrame(values, index=dates)
    matrix.index.name = "historical_date"
    calibration = pd.DataFrame(errors, index=dates)
    calibration.index.name = "historical_date"
    return matrix, calibration


def test_omitting_calibration_se_leaves_the_output_untouched():
    """Backward compatibility: the new column and keys appear only when asked for."""

    matrix, _calibration = _matrix_and_calibration()
    result = fit_gls_consensus(matrix, ConsensusConfig(), baseline_start=START)

    assert "calibration_standard_error" not in result.consensus.columns
    assert result.diagnostics["calibration_se_supplied"] is False


def test_supplying_calibration_se_adds_a_column_without_changing_the_series():
    """It is reported, not folded into the estimate. value and standard_error must
    be identical to the run without it, or this stopped being a diagnostic."""

    matrix, calibration = _matrix_and_calibration()
    without = fit_gls_consensus(matrix, ConsensusConfig(), baseline_start=START)
    with_calibration = fit_gls_consensus(
        matrix, ConsensusConfig(), baseline_start=START, calibration_se=calibration
    )

    assert np.allclose(
        without.consensus["value"].to_numpy(dtype=float),
        with_calibration.consensus["value"].to_numpy(dtype=float),
    )
    assert np.allclose(
        without.consensus["standard_error"].to_numpy(dtype=float),
        with_calibration.consensus["standard_error"].to_numpy(dtype=float),
    )
    assert with_calibration.diagnostics["calibration_se_supplied"] is True
    assert (with_calibration.consensus["calibration_standard_error"] > 0).all()


def test_calibration_se_is_rescaled_with_the_values():
    """baseline_rescale multiplies every pull by a constant; an untransformed error
    would be compared against values on a different scale, which is exactly the
    class of unit bug 1.4.0 found in this quantity."""

    matrix, calibration = _matrix_and_calibration()
    # Put one pull on a wildly different raw scale. Rescaling should undo it in both
    # the values and the errors, leaving the propagated error close to the others.
    scaled_matrix = matrix.copy()
    scaled_calibration = calibration.copy()
    scaled_matrix["P001"] = scaled_matrix["P001"] * 50.0
    scaled_calibration["P001"] = scaled_calibration["P001"] * 50.0

    plain = fit_gls_consensus(
        matrix, ConsensusConfig(), baseline_start=START, calibration_se=calibration
    )
    scaled = fit_gls_consensus(
        scaled_matrix, ConsensusConfig(), baseline_start=START, calibration_se=scaled_calibration
    )

    assert scaled.diagnostics["median_calibration_se"] == pytest.approx(
        plain.diagnostics["median_calibration_se"], rel=0.05
    )

    # Without rescaling the error the diagnostic would be off by the scale factor.
    unscaled_error = fit_gls_consensus(
        scaled_matrix, ConsensusConfig(), baseline_start=START, calibration_se=calibration
    )
    assert unscaled_error.diagnostics["median_calibration_se"] != pytest.approx(
        plain.diagnostics["median_calibration_se"], rel=0.05
    )


def test_the_exceedance_diagnostic_can_fire():
    """A share that is zero on every input detects nothing.

    The consensus standard error scales with cross-pull disagreement while the
    calibration error does not, so shrinking the former must push the share up. Both
    ends are asserted: near-zero when the pulls disagree far more than the
    calibration error, and near-one when they barely disagree at all.
    """

    noisy_matrix, calibration = _matrix_and_calibration(pull_noise_sd=3.0)
    quiet_matrix, _ = _matrix_and_calibration(pull_noise_sd=0.02)

    noisy = fit_gls_consensus(
        noisy_matrix, ConsensusConfig(), baseline_start=START, calibration_se=calibration
    )
    quiet = fit_gls_consensus(
        quiet_matrix, ConsensusConfig(), baseline_start=START, calibration_se=calibration
    )

    assert noisy.diagnostics["calibration_se_exceeds_consensus_se_share"] < 0.05
    assert quiet.diagnostics["calibration_se_exceeds_consensus_se_share"] > 0.95


def test_propagation_uses_the_consensus_weights_not_a_plain_average():
    """Var(sum w_j x_j) = sum w_j^2 s_j^2 under independence, which is smaller than
    the average of the s_j. Getting this wrong would overstate by roughly sqrt(m)."""

    matrix, calibration = _matrix_and_calibration(n_pulls=5, calibration_sd=0.40)
    result = fit_gls_consensus(
        matrix, ConsensusConfig(), baseline_start=START, calibration_se=calibration
    )

    weights = result.weights.set_index("pull_id")["weight"]
    columns = list(result.aligned_matrix.columns)
    w = weights.loc[columns].to_numpy(dtype=float)
    # The calibration errors are on the rescaled scale, so read them off the result.
    reported = float(result.consensus["calibration_standard_error"].median())

    scale = float(result.diagnostics["median_calibration_se"])
    assert reported == pytest.approx(scale, rel=1e-9)
    # Independent propagation is strictly below the plain average of equal errors.
    per_pull = scale / np.sqrt(np.sum(w**2))
    assert reported < per_pull
    assert reported == pytest.approx(per_pull * np.sqrt(np.sum(w**2)), rel=1e-9)


def test_independence_across_pulls_is_flagged_as_an_assumption():
    """1.4.0 measured that chunks within one collection day are rescalings of a
    single served sample. Whether that extends across pulls is unknown, and if it
    does this propagation understates. The flag travels with the result."""

    matrix, calibration = _matrix_and_calibration()
    result = fit_gls_consensus(
        matrix, ConsensusConfig(), baseline_start=START, calibration_se=calibration
    )
    assert result.diagnostics["calibration_se_independent_across_pulls_assumed"] is True
