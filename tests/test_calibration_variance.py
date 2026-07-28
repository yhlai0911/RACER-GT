"""Properties of the calibration stage's reported uncertainty and its variance.

Two invariants that no existing test covered, one of which was violated.

The reported standard error is a level-scale quantity, so multiplying every input
by a constant must multiply it by the same constant. The inverse-variance
aggregation built its formal term from log-scale precisions and left it
unconverted, which is invisible whenever cross-chunk disagreement dominates and
fatal on a date covered by a single chunk, where disagreement is zero by
definition and the whole standard error is the unconverted term. Those dates are
the two ends of every reconstructed series.

The second invariant is the one the manuscript now proves. Graph WLS weights are
edge precisions, so the covariance of the solution inverts a weighted graph
Laplacian and the variance of a scale relative to the reference is the effective
resistance between them. Rayleigh's monotonicity law then makes the full graph
weakly better than any spanning path through the same edges.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from racergt.config import CalibrationConfig
from racergt.overlap import OverlapGraphCalibrator

WINDOW_DAYS = 90
STEP_DAYS = 30
N_CHUNKS = 4
START = "2024-01-01"
END = "2024-07-31"


def _chunks(scale: float = 1.0) -> pd.DataFrame:
    """Four overlapping windows cut from one latent series, scaled by ``scale``.

    Normalization is switched off by the caller, so the multiplier survives into
    the reconstructed series and its standard error.
    """

    dates = pd.date_range(START, END, freq="D")
    day = np.arange(len(dates), dtype=float)
    latent = 40.0 + 18.0 * np.sin(day / 23.0) + 9.0 * np.cos(day / 7.0)
    signal = pd.Series(latent * scale, index=dates)

    rows = []
    for index in range(N_CHUNKS):
        start = dates[0] + pd.Timedelta(days=index * STEP_DAYS)
        end = start + pd.Timedelta(days=WINDOW_DAYS - 1)
        segment = signal.loc[start:end]
        for date_value, value in zip(segment.index, segment.to_numpy(), strict=True):
            rows.append(
                {
                    "series_id": "s",
                    "pull_id": "P001",
                    "chunk_id": f"C{index + 1:04d}",
                    "historical_date": date_value,
                    "value": float(value),
                    "collection_day": 0,
                    "stream_id": "A",
                    "replicate_id": "1",
                    "window_start": start,
                    "window_end": end,
                }
            )
    return pd.DataFrame(rows)


def _fit(scale: float):
    config = CalibrationConfig(normalization="none")
    return OverlapGraphCalibrator(config, min_overlap_days=10).fit(_chunks(scale))


def test_standard_error_scales_with_the_series():
    """A level-scale error must scale with a level-scale rescaling of the input."""

    base, scaled = _fit(1.0), _fit(10.0)
    merged = base.full_series.merge(
        scaled.full_series, on="historical_date", suffixes=("_1", "_10")
    )
    assert not merged.empty

    np.testing.assert_allclose(
        merged["value_10"], 10.0 * merged["value_1"], rtol=1e-9
    )
    np.testing.assert_allclose(
        merged["calibration_se_10"], 10.0 * merged["calibration_se_1"], rtol=1e-6
    )


def test_single_chunk_dates_do_not_report_the_smallest_error():
    """The ends of the series are the thinnest part, not the best measured.

    A plausibility guard rather than the regression test: on the real bitcoin
    data the unconverted variance made these dates look 36 times better measured
    than the rest, but on this small fixture the gap stays inside the bound, so
    only :func:`test_standard_error_scales_with_the_series` actually fails
    against the unfixed code. This one states the property that made the
    behaviour recognisable as wrong.
    """

    result = _fit(1.0)
    series = result.full_series
    relative = series["calibration_se"] / series["value"]
    alone = relative[series["n_contributing_chunks"] == 1]
    together = relative[series["n_contributing_chunks"] > 1]
    assert not alone.empty and not together.empty
    # Not required to be larger, but it cannot be an order of magnitude smaller.
    assert alone.median() > 0.1 * together.median()


def test_graph_variance_never_exceeds_the_spanning_path():
    """Rayleigh monotonicity, as a property of the reported diagnostics."""

    diagnostics = _fit(1.0).diagnostics
    graph = diagnostics["max_log_scale_variance"]
    path = diagnostics["sequential_max_log_scale_variance"]
    assert np.isfinite(path)
    assert graph <= path * (1.0 + 1e-12)
    assert diagnostics["calibration_variance_reduction"] >= 1.0 - 1e-12


def test_scale_variance_equals_effective_resistance():
    """Pin the estimator against an independent derivation, not against itself.

    Var(ell_j - ell_ref) is the effective resistance between the two nodes when
    each edge carries a conductance equal to its precision. Computing it from the
    Laplacian pseudo-inverse touches none of the estimator's own linear algebra,
    so agreement is evidence about the implementation rather than a tautology.
    """

    result = _fit(1.0)
    edges = result.edges
    nodes = sorted(set(edges["chunk_i"]) | set(edges["chunk_j"]))
    position = {node: i for i, node in enumerate(nodes)}
    reference = result.diagnostics["reference_chunk"]

    laplacian = np.zeros((len(nodes), len(nodes)))
    for row in edges.itertuples():
        i, j, weight = position[row.chunk_i], position[row.chunk_j], float(row.weight)
        laplacian[i, i] += weight
        laplacian[j, j] += weight
        laplacian[i, j] -= weight
        laplacian[j, i] -= weight
    pseudo = np.linalg.pinv(laplacian)

    reported = result.chunk_scales.set_index("chunk_id")["log_scale_variance"]
    for node in nodes:
        if node == reference:
            assert reported.loc[node] == 0.0
            continue
        contrast = np.zeros(len(nodes))
        contrast[position[node]] = 1.0
        contrast[position[reference]] = -1.0
        resistance = float(contrast @ pseudo @ contrast)
        assert abs(reported.loc[node] - resistance) <= 1e-12 * max(resistance, 1e-30)
