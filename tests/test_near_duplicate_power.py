"""Pin that the near-duplicate rule detects nothing beyond exact duplicates.

The manuscript describes a near-duplicate dependence graph built from residuals
after removing the common signal, and the acceptance rule reads
max_component_share off it. Injecting the dependence that graph exists to find --
a third of the pulls served from one shared cache disturbance -- moves nothing.

The reason is structural rather than a matter of tuning. The conjunction requires
exact_cell_agreement >= 0.90, and the diagnostic runs on calibrated values, which
are continuous: two pulls that are not the same object agree on no cell at all. So
the raw rule is false for every non-exact pair regardless of the correlation and
MAE thresholds, and near-duplicate status requires the raw rule.

Pinned rather than fixed here, following test_per_chunk_deviation_never_responds:
a diagnostic with no power must not keep being reported as though it had some.
Ticket 26 decides what replaces it.
"""

from __future__ import annotations

import warnings

import numpy as np
import pytest

from racergt.config import DuplicateConfig, RacerGTConfig
from racergt.duplicates import diagnose_duplicates
from racergt.pipeline import RacerGTPipeline
from racergt.schema import wide_pull_matrix
from racergt.simulation import SimulationSettings, simulate_racergt_data


@pytest.fixture
def dependent_matrix(small_config: RacerGTConfig):
    """A batch where a third of the pulls share one cache disturbance."""

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        simulation = simulate_racergt_data(
            small_config,
            SimulationSettings(
                random_seed=42,
                exact_duplicate_fraction=0.10,
                cache_cluster_fraction=0.33,
                cache_cluster_weight=0.60,
            ),
        )
        result = RacerGTPipeline(small_config).fit(simulation.raw_chunks, simulation.benchmark)
    return wide_pull_matrix(result.complete_pulls)


def test_exact_cell_agreement_is_unreachable_on_calibrated_values(dependent_matrix):
    """The condition that makes the conjunction unsatisfiable, measured directly.

    Calibration multiplies each pull by a continuous scale, so cells coincide only
    for pulls that are the same object. The threshold is 0.90 and the maximum
    attainable value among non-identical pairs is zero.
    """

    diagnostics = diagnose_duplicates(dependent_matrix, DuplicateConfig())
    pairs = diagnostics.pairwise_metrics
    non_exact = pairs[~pairs["exact_vector"].astype(bool)]

    assert len(non_exact) > 100, "need a real spread of pairs for this to mean anything"
    assert float(non_exact["exact_cell_agreement"].max()) == 0.0


def test_detection_does_not_respond_to_any_threshold(dependent_matrix):
    """Zero power, shown by sweeping every threshold that could plausibly bind."""

    baseline = diagnose_duplicates(dependent_matrix, DuplicateConfig()).summary
    edges = baseline["n_near_duplicate_edges"]

    for raw_threshold in (0.90, 0.95, 0.9999):
        summary = diagnose_duplicates(
            dependent_matrix, DuplicateConfig(raw_correlation_threshold=raw_threshold)
        ).summary
        assert summary["n_near_duplicate_edges"] == edges

    for residual_threshold in (0.70, 0.90, 0.999):
        summary = diagnose_duplicates(
            dependent_matrix, DuplicateConfig(residual_correlation_threshold=residual_threshold)
        ).summary
        assert summary["n_near_duplicate_edges"] == edges

    for mae_threshold in (0.02, 1.0, 5.0):
        summary = diagnose_duplicates(
            dependent_matrix, DuplicateConfig(mae_100_threshold=mae_threshold)
        ).summary
        assert summary["n_near_duplicate_edges"] == edges


def test_the_injected_dependence_is_real_and_visible_elsewhere(small_config):
    """The dependence exists; it is the rule that cannot see it.

    Without this the previous test would be consistent with there being nothing to
    detect. The residual correlations rise when the cache cluster is injected, so
    the signal is present in exactly the quantity the residual rule reads.
    """

    def max_residual_correlation(**settings) -> float:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            simulation = simulate_racergt_data(
                small_config, SimulationSettings(random_seed=42, **settings)
            )
            result = RacerGTPipeline(small_config).fit(
                simulation.raw_chunks, simulation.benchmark
            )
        matrix = wide_pull_matrix(result.complete_pulls)
        pairs = diagnose_duplicates(matrix, DuplicateConfig()).pairwise_metrics
        non_exact = pairs[~pairs["exact_vector"].astype(bool)]
        return float(np.nanmax(non_exact["residual_pearson"].to_numpy(dtype=float)))

    independent = max_residual_correlation(exact_duplicate_fraction=0.10)
    clustered = max_residual_correlation(
        exact_duplicate_fraction=0.10, cache_cluster_fraction=0.33, cache_cluster_weight=0.60
    )
    assert clustered > independent + 0.05

    # Both sit below the 0.95 residual threshold, so that condition blocks the rule
    # too, independently of exact_cell_agreement. Measured at 0.74 and 0.84 here.
    assert clustered < DuplicateConfig().residual_correlation_threshold


def test_every_reported_component_comes_from_exact_duplicates(dependent_matrix):
    """max_component_share feeds decision.py, so what it measures matters.

    With the near-duplicate rule inert, the components it reports are the exact
    duplicate groups, which hash comparison already identifies precisely.
    """

    diagnostics = diagnose_duplicates(dependent_matrix, DuplicateConfig())
    pairs = diagnostics.pairwise_metrics
    flagged = pairs[pairs["near_duplicate"].astype(bool)]

    assert len(flagged) > 0, "expected the exact duplicates to be flagged"
    assert flagged["exact_vector"].astype(bool).all(), (
        "a non-exact pair was flagged; the rule may have gained power and this "
        "test, along with ticket 26, needs revisiting"
    )
