import numpy as np
import pandas as pd

from racergt.consensus import fit_design_weighted_consensus, fit_gls_consensus
from racergt.duplicates import diagnose_duplicates


def test_duplicate_detection_and_gls(small_config):
    rng = np.random.default_rng(2)
    truth = np.linspace(20, 80, 200)
    # A and B are an exact duplicated, high-noise realization. C and D are
    # lower-noise independent realizations. A naive mean overweights A/B.
    a = truth + rng.normal(0, 5, 200)
    b = a.copy()
    c = truth + rng.normal(0, 0.7, 200)
    d = truth + rng.normal(0, 0.7, 200)
    matrix = pd.DataFrame({"A": a, "B": b, "C": c, "D": d})
    diag = diagnose_duplicates(matrix, small_config.duplicates)
    assert not diag.exact_groups.empty
    result = fit_gls_consensus(matrix, small_config.consensus)
    assert result.diagnostics["n_unique_pulls"] == 3
    assert np.isclose(result.weights["weight"].sum(), 1.0)
    simple = matrix.mean(axis=1).to_numpy()
    gls = result.consensus["value"].to_numpy()
    # Both are baseline-normalized by the estimator; compare after same normalization.
    truth_scaled = truth / truth.mean() * 100
    simple_scaled = simple / simple.mean() * 100
    assert np.mean((gls - truth_scaled) ** 2) < np.mean((simple_scaled - truth_scaled) ** 2)


def test_design_weighted_consensus_equal_cells_not_equal_pulls():
    dates = pd.date_range("2024-01-01", periods=2, freq="D")
    matrix = pd.DataFrame(
        {
            "A1": [80.0, 120.0],
            "A2": [80.0, 120.0],
            "B1": [100.0, 100.0],
        },
        index=dates,
    )
    metadata = pd.DataFrame(
        {
            "pull_id": ["A1", "A2", "B1"],
            "collection_day": [0, 0, 1],
            "stream_id": ["A", "A", "A"],
            "replicate_id": ["1", "2", "1"],
        }
    )
    result = fit_design_weighted_consensus(matrix, metadata)
    assert result.diagnostics["n_design_cells"] == 2
    assert np.allclose(result.consensus["value"], [90.0, 110.0])
    assert np.isclose(result.cell_weights["target_weight"].sum(), 1.0)
