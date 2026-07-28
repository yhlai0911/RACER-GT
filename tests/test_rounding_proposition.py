"""Numerical checks for the rounding proposition in the mathematical appendix.

Trends returns integers after dividing by a per-chunk window maximum, so the
rounding error on a date is a function of the fractional part of alpha_c q_t with
alpha_c = 100 / M_c. Two chunks sharing a maximum produce identical errors; two
with an irrational ratio of maxima produce asymptotically uncorrelated ones. The
effective number of independent roundings is therefore the number of distinct
maxima rather than the number of chunks.

These pin the proposition and, as importantly, the caveat attached to it. A
stronger claim -- that any two distinct maxima are no worse than independent --
was drafted and is false: a maximum ratio of exactly three correlates the errors
at +0.33. The caveat exists because the simulation refuted the stronger version.
"""

from __future__ import annotations

import numpy as np
import pytest

N_DRAWS = 200_000
SEED = 20260728
BASE_MAX = 97.0


def _served_volume(seed: int = SEED) -> np.ndarray:
    return np.random.default_rng(seed).uniform(20.0, 80.0, size=N_DRAWS)


def _rounding_error(volume: np.ndarray, window_max: float) -> np.ndarray:
    scaled = 100.0 * volume / window_max
    return np.rint(scaled) - scaled


def test_rounding_error_has_variance_one_twelfth():
    """Part (i): uniform on [-1/2, 1/2) once the scaled volume equidistributes."""

    errors = _rounding_error(_served_volume(), BASE_MAX)
    assert errors.var(ddof=1) == pytest.approx(1.0 / 12.0, rel=0.01)
    assert errors.min() >= -0.5 and errors.max() < 0.5


def test_equal_maxima_give_identical_errors():
    """Part (ii): identical, not merely correlated. The pair carries one term."""

    volume = _served_volume()
    first = _rounding_error(volume, BASE_MAX)
    second = _rounding_error(volume, BASE_MAX)
    assert np.array_equal(first, second)


def test_irrational_ratio_of_maxima_decorrelates():
    """Part (iii): Weyl's criterion, checked at three irrational ratios."""

    volume = _served_volume()
    reference = _rounding_error(volume, BASE_MAX)
    for ratio in (np.sqrt(2), np.pi / 2, np.e / 2):
        other = _rounding_error(volume, BASE_MAX * ratio)
        assert abs(float(np.corrcoef(reference, other)[0, 1])) < 0.01


def test_effective_count_is_distinct_maxima_not_chunk_count():
    """Part (iv): the same g gives the same variance whatever n is.

    This is the operative claim. Averaging eight chunks that share two maxima is
    exactly as good as averaging two, and no better.
    """

    volume = _served_volume()
    irrationals = BASE_MAX * np.array([1.0, np.sqrt(2), np.sqrt(3), np.sqrt(7)])

    variances = {}
    for n_chunks, n_groups in ((2, 2), (4, 2), (8, 2), (4, 4), (8, 4)):
        maxima = np.repeat(irrationals[:n_groups], n_chunks // n_groups)
        stacked = np.column_stack([_rounding_error(volume, m) for m in maxima])
        variances[(n_chunks, n_groups)] = float(stacked.mean(axis=1).var(ddof=1))

    for n_groups in (2, 4):
        target = 1.0 / (12.0 * n_groups)
        same_group = [v for (_n, g), v in variances.items() if g == n_groups]
        for value in same_group:
            assert value == pytest.approx(target, rel=0.06)
        # Identical across chunk counts, not merely close to the target.
        assert max(same_group) - min(same_group) < 1e-9


def test_the_stronger_claim_is_false_and_the_caveat_is_needed():
    """Pin the refutation, so the general-position caveat is never dropped.

    The drafted claim was that only equal maxima hurt, since low-order rational
    ratios were observed to correlate negatively, which helps. A ratio of three
    correlates +0.33, so distinct maxima are not automatically at least as good as
    independent ones and g is a proxy rather than a bound.
    """

    volume = _served_volume()
    reference = _rounding_error(volume, BASE_MAX)

    positive = float(np.corrcoef(reference, _rounding_error(volume, BASE_MAX * 3.0))[0, 1])
    negative = float(np.corrcoef(reference, _rounding_error(volume, BASE_MAX * 2.0))[0, 1])

    assert positive > 0.2, "ratio 3 must correlate positively or the caveat is unmotivated"
    assert negative < -0.1, "ratio 2 must correlate negatively, which is what misled the draft"


def test_near_equal_maxima_behave_like_equal_ones():
    """The failure mode is continuous: maxima need not coincide exactly to hurt."""

    volume = _served_volume()
    reference = _rounding_error(volume, BASE_MAX)
    nearly = _rounding_error(volume, BASE_MAX * 1.001)
    assert float(np.corrcoef(reference, nearly)[0, 1]) > 0.5
