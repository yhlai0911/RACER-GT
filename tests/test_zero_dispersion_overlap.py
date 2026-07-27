"""Pin the diagnostic that real Google Trends data required and the simulator cannot produce.

Trends divides each chunk by the maximum inside that chunk's own window. Two
windows containing the same peak day are therefore divided by the same number and,
after rounding to integers, are identical wherever they overlap. The overlap then
carries no dispersion and the edge built from it says nothing about relative scale
beyond the single value it reports, yet it still enters the weighted fit at
whatever weight ``edge_variance_floor`` and ``max_edge_weight`` allow.

``simulate_racergt_data`` multiplies every chunk by continuous lognormal noise
before taking that maximum, so it never generates this case. The fixtures below
apply the Trends rule directly to a latent series, which is the smallest
construction that reproduces it. No CSV is added: the data generating process is
written out in the test, as elsewhere in this suite.
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


def _dates() -> pd.DatetimeIndex:
    return pd.date_range(START, END, freq="D")


def _reported_chunks(signal: pd.Series) -> pd.DataFrame:
    """Cut one latent series into windows and normalize each the way Trends does."""

    rows = []
    for index in range(N_CHUNKS):
        start = signal.index[0] + pd.Timedelta(days=index * STEP_DAYS)
        end = start + pd.Timedelta(days=WINDOW_DAYS - 1)
        segment = signal.loc[start:end]
        reported = np.rint(100.0 * segment.to_numpy() / segment.to_numpy().max())
        for date_value, value in zip(segment.index, reported, strict=True):
            rows.append(
                {
                    "series_id": "peak",
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


def _fit(signal: pd.Series):
    return OverlapGraphCalibrator(CalibrationConfig(), min_overlap_days=10).fit(
        _reported_chunks(signal), baseline_start=START, baseline_end=END
    )


def test_shared_peak_produces_zero_dispersion_edges_and_fewer_scale_groups():
    dates = _dates()
    day = np.arange(len(dates), dtype=float)
    peak_position = float((pd.Timestamp("2024-02-15") - dates[0]).days)
    # One dominant spike early enough that the first two windows both contain it
    # and later windows do not, so the window maximum switches exactly once.
    latent = (
        20.0
        + 5.0 * np.sin(day / 30.0)
        + 60.0 * np.exp(-(((day - peak_position) / 6.0) ** 2))
    )
    result = _fit(pd.Series(latent, index=dates))
    diagnostics = result.diagnostics

    assert diagnostics["connected"]
    assert diagnostics["n_nodes"] == N_CHUNKS
    assert diagnostics["n_zero_dispersion_edges"] >= 1
    assert (
        diagnostics["n_informative_edges"]
        == diagnostics["n_edges"] - diagnostics["n_zero_dispersion_edges"]
    )
    # Chunks tied by such an edge share one scale, so groups fall below chunks.
    assert diagnostics["n_scale_groups"] < diagnostics["n_nodes"]

    zero_dispersion = result.edges[result.edges["robust_scale"] == 0.0]
    assert (zero_dispersion["log_ratio"].abs() < 1e-12).all()


def test_distinct_maxima_leave_every_edge_informative():
    """The mirror case, so the diagnostic cannot be trivially always-on.

    A strictly increasing series puts every window's maximum at its own final day.
    No two windows share a normalizing value, so no overlap is degenerate.
    """

    dates = _dates()
    day = np.arange(len(dates), dtype=float)
    result = _fit(pd.Series(10.0 + 0.4 * day, index=dates))

    assert result.diagnostics["connected"]
    assert result.diagnostics["n_zero_dispersion_edges"] == 0
    assert result.diagnostics["n_scale_groups"] == result.diagnostics["n_nodes"]
