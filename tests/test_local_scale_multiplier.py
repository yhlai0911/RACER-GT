"""What the per-day standard error's local multiplier estimates, and where it fails.

The consensus standard error is one global sqrt(w' Sigma w) times a per-day ratio
of median absolute deviations, clipped to [0.25, 4]. That looked like a heuristic
with no statistical content, and ticket 25 listed it as the item most likely to be
demoted. Deriving it first showed otherwise: if the residual covariance varies in
scale but not in shape, Sigma_t = c_t^2 Sigma, then the correct standard error is
exactly c_t times the global one, and M_t / M_bar is consistent for c_t because
the constant relating a median absolute deviation to a standard deviation cancels.

So the question is not whether it estimates something, but how well, and what
happens when the shape-invariance assumption fails. These tests pin both, and the
second is the unfavourable one: the median that makes the estimate robust also
makes it blind to a minority of pulls going noisy, and blindness there leaves the
standard error too small.
"""

from __future__ import annotations

import numpy as np
import pytest

N_DATES = 4000
CLIP = (0.25, 4.0)


def _multipliers(n_pulls: int, scale: np.ndarray, seed: int, noisy_pull_share: float = 1.0):
    """Reproduce consensus.py's construction: per-date MAD over its cross-date median.

    ``noisy_pull_share`` controls whether a date's extra noise hits every pull, which
    is the pure-scale case the proposition assumes, or only some of them, which is a
    change in the shape of Sigma_t.
    """

    rng = np.random.default_rng(seed)
    deviations = np.abs(rng.normal(size=(N_DATES, n_pulls)))
    affected = max(1, round(noisy_pull_share * n_pulls))
    deviations[:, :affected] *= scale[:, None]
    local = np.median(deviations, axis=1)
    return local / np.median(local)


def _auc(low: np.ndarray, high: np.ndarray) -> float:
    """Probability a randomly chosen high-noise date scores above a normal one."""

    stacked = np.concatenate([low, high])
    labels = np.concatenate([np.zeros(low.size), np.ones(high.size)])
    order = np.argsort(stacked)
    ranks = np.empty_like(order, dtype=float)
    ranks[order] = np.arange(1, stacked.size + 1)
    n_high = labels.sum()
    n_low = labels.size - n_high
    return float((ranks[labels == 1].sum() - n_high * (n_high + 1) / 2) / (n_low * n_high))


@pytest.mark.parametrize(
    ("n_pulls", "max_sd", "max_clip_share"),
    [(3, 0.70, 0.08), (9, 0.45, 0.01), (30, 0.25, 0.001)],
)
def test_multiplier_noise_without_any_real_variation(n_pulls, max_sd, max_clip_share):
    """With c_t identically one, every departure from one is estimation noise.

    Recorded because a reader seeing a per-day standard error vary by a third has
    to know how much of that is information. At m = 9 it is 0.38, and the clip
    binds on well under one percent of dates, which is why the bounds cost little
    at the design sizes recommended here.
    """

    raw = _multipliers(n_pulls, np.ones(N_DATES), seed=20260728)
    assert raw.std(ddof=1) < max_sd
    clipped_share = float(np.mean((raw < CLIP[0]) | (raw > CLIP[1])))
    assert clipped_share <= max_clip_share


@pytest.mark.parametrize(("n_pulls", "min_auc"), [(3, 0.80), (9, 0.95), (30, 0.99)])
def test_multiplier_detects_pure_scale_variation(n_pulls, min_auc):
    """Under the proposition's assumption it works, and increasingly well with m."""

    rng = np.random.default_rng(5)
    noisy = rng.random(N_DATES) < 0.20
    scale = np.where(noisy, 3.0, 1.0)
    raw = _multipliers(n_pulls, scale, seed=99)
    assert _auc(raw[~noisy], raw[noisy]) > min_auc


def test_power_falls_when_only_some_pulls_go_noisy():
    """The limitation, and its direction.

    A date where only a minority of pulls are noisy changes the shape of Sigma_t
    rather than its scale, which is outside the proposition. The median absorbs it,
    so power falls monotonically with the share of pulls affected. Undetected means
    the reported standard error stays too small, which is the direction that
    flatters any conclusion drawn from it.
    """

    rng = np.random.default_rng(5)
    noisy = rng.random(N_DATES) < 0.20
    scale = np.where(noisy, 3.0, 1.0)

    areas = []
    for share in (1.0, 0.5, 0.25):
        raw = _multipliers(9, scale, seed=11, noisy_pull_share=share)
        areas.append(_auc(raw[~noisy], raw[noisy]))

    assert areas[0] > 0.95
    assert areas == sorted(areas, reverse=True), areas
    # A fifth of the pulls going noisy is close to invisible.
    assert areas[-1] < 0.80


def test_the_consistency_constant_cancels_in_the_ratio():
    """Why no 1.4826 appears anywhere: it is in both terms of M_t / M_bar.

    Scaling every deviation by a constant must leave the multiplier untouched, or
    the estimate would depend on a unit choice.
    """

    rng = np.random.default_rng(3)
    deviations = np.abs(rng.normal(size=(N_DATES, 9)))

    def ratio(values: np.ndarray) -> np.ndarray:
        local = np.median(values, axis=1)
        return local / np.median(local)

    assert np.allclose(ratio(deviations), ratio(deviations * 1.4826))
    assert np.allclose(ratio(deviations), ratio(deviations * 0.001))
