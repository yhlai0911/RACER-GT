"""How well can Sigma tell the pulls apart, and why the answer is bounded by m.

Residuals are each pull minus the daily central tendency of the pulls themselves,
so the subtrahend is correlated with what it is subtracted from. With a mean
subtrahend the consequence is exactly solvable. Writing e_j for pull j's error,

    r_j = e_j - (1/m) sum_k e_k,
    Var(r_j) = sigma_j^2 (1 - 2/m) + S/m^2,      S = sum_k sigma_k^2,

so as sigma_1 -> 0 with the rest at sigma, the ratio Sigma can report tends to

    (m^2 - m - 1)/(m - 1) = m - 1/(m - 1),

independently of how large the true ratio is. At m = 2 that is exactly 1: the two
residuals are r_1 = -r_2, so their variances cannot differ at all.

The bound is a property of centring on the sample, not of Google Trends, and it
sets what the covariance-adjusted stage can do before any data arrives.

These tests exist so that the bound is not rediscovered as a bug, and so that the
two obvious ways around it are not adopted without their costs: an external
reference has to beat the best pull to help, and iterating diverges.
"""

from __future__ import annotations

from itertools import pairwise

import numpy as np
import pytest

T = 120_000
SEED = 20260728


def _errors(m: int, sigma_lo: float = 1e-4, sigma_hi: float = 2.0, seed: int = SEED):
    sds = np.array([sigma_lo] + [sigma_hi] * (m - 1))
    return np.random.default_rng(seed).normal(size=(T, m)) * sds, sds


def _variance_ratio(residuals: np.ndarray) -> float:
    variances = residuals.var(axis=0, ddof=1)
    return float(variances.max() / variances.min())


def _saturation(m: int) -> float:
    return m - 1.0 / (m - 1)


@pytest.mark.parametrize("m", [3, 4, 5, 6, 8, 10])
def test_mean_subtrahend_saturates_at_the_analytic_bound(m):
    """The closed form, checked against simulation at a true ratio of 4e8."""

    errors, _ = _errors(m)
    residuals = errors - errors.mean(axis=1, keepdims=True)
    assert _variance_ratio(residuals) == pytest.approx(_saturation(m), rel=0.03)


def test_two_pulls_cannot_be_told_apart_at_all():
    """r_1 = -r_2 exactly, so no covariance estimate can distinguish them.

    The sharpest case of the bound and the easiest to verify: it holds identically,
    not approximately, whatever the true precisions are.
    """

    errors, _ = _errors(2)
    residuals = errors - errors.mean(axis=1, keepdims=True)
    assert np.allclose(residuals[:, 0], -residuals[:, 1], atol=1e-12)
    assert _variance_ratio(residuals) == pytest.approx(1.0, abs=1e-9)


def test_the_bound_does_not_move_when_the_true_ratio_moves():
    """The point of the result: the reported ratio is about m, not about the data."""

    m = 4
    reported = []
    for sigma_lo in (0.5, 0.05, 0.005, 0.0005):
        errors, _ = _errors(m, sigma_lo=sigma_lo)
        residuals = errors - errors.mean(axis=1, keepdims=True)
        reported.append(_variance_ratio(residuals))

    # True variance ratio spans four orders of magnitude across these settings.
    assert max(reported) / min(reported) < 2.0
    assert reported[-1] == pytest.approx(_saturation(m), rel=0.05)


def test_median_subtrahend_is_slightly_better_but_the_same_order():
    """The implementation uses the median. It buys a little, and not a different bound."""

    for m in (4, 6, 10):
        errors, _ = _errors(m)
        median_ratio = _variance_ratio(errors - np.median(errors, axis=1, keepdims=True))
        assert median_ratio > _saturation(m)
        assert median_ratio < 1.6 * _saturation(m)


def test_an_external_reference_helps_only_if_it_beats_the_best_pull():
    """Alternative one, with the condition that makes it useless here.

    Subtracting a reference independent of every pull gives
    Var(r_j) = sigma_j^2 + v, so the ratio is (sigma_max^2 + v)/(sigma_min^2 + v):
    unbounded as v -> 0, but collapsing toward one as v grows. The reference has to
    be more precise than the most precise pull, and daily Google Trends offers no
    such series --- the frequency benchmark is lower frequency by construction.
    """

    m = 4
    errors, sds = _errors(m, sigma_lo=0.05)
    rng = np.random.default_rng(99)
    true_ratio = float((sds.max() / sds.min()) ** 2)

    sharp = errors - rng.normal(size=(T, 1)) * 0.02
    blunt = errors - rng.normal(size=(T, 1)) * 1.00

    assert _variance_ratio(sharp) > 0.5 * true_ratio
    # A reference no better than the noisy pulls recovers nothing the median did not.
    assert _variance_ratio(blunt) < 3.0 * _saturation(m)


def test_iterating_the_weights_diverges():
    """Alternative two, and the reason weight_cap has to stay.

    Reweighting on the estimated Sigma shrinks the residual of whichever pull just
    gained weight, which raises its apparent precision, which raises its weight. The
    loop is positive feedback: the weight reaches one and the reported ratio grows
    without bound. The manuscript argues for the cap as the guard against weight
    concentrating on a single pull; that failure mode does not appear under the
    current Sigma, but it is exactly what appears the moment Sigma can discriminate.
    """

    m = 4
    errors, _ = _errors(m, sigma_lo=0.05)
    weights = np.full(m, 1.0 / m)

    ratios = []
    for _ in range(6):
        residuals = errors - (errors @ weights)[:, None]
        variances = residuals.var(axis=0, ddof=1)
        ratios.append(float(variances.max() / variances.min()))
        precision = 1.0 / variances
        weights = precision / precision.sum()

    assert weights.max() == pytest.approx(1.0, abs=1e-6)
    assert ratios[-1] > 1e6 * ratios[0]
    # Monotone, so this is feedback rather than a single bad step.
    assert all(b > a for a, b in pairwise(ratios))
