"""Can the calibration diagnostics fail? Injected perturbations say what each detects.

A diagnostic that passes on real data is worth nothing until it has been shown
capable of failing. Injecting a known perturbation into one chunk and re-running
turns each check into a statement about minimum detectable effect, and it caught
one that cannot fail at all.

Multiplying a chunk by a constant is absorbed entirely into its estimated log
scale, so the calibrated values are unchanged and any check built on them returns
the same number for a 2% error and a 20% one. A uniform rescale is the parameter,
not a violation of the model, so this is correct behaviour --- but it means
per-chunk deviation from the reconstructed series is not evidence about model fit
and must not be reported as though it were.

Cycle closure and the within-overlap drift test are built on quantities a single
scale cannot absorb, and both respond.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from racergt.config import CalibrationConfig
from racergt.overlap import OverlapGraphCalibrator

WINDOW_DAYS = 120
STEP_DAYS = 30
N_CHUNKS = 5
START = "2024-01-01"
END = "2024-09-30"
TARGET = "C0003"


def _chunks(perturbation=None) -> pd.DataFrame:
    """Overlapping windows from one latent series, optionally distorting TARGET.

    ``perturbation`` maps a day offset within the chunk to a multiplicative
    factor, so a caller can inject a rescale, a trend, or a wave.
    """

    dates = pd.date_range(START, END, freq="D")
    day = np.arange(len(dates), dtype=float)
    signal = pd.Series(50.0 + 20.0 * np.sin(day / 29.0) + 8.0 * np.cos(day / 11.0), index=dates)

    rows = []
    for index in range(N_CHUNKS):
        chunk_id = f"C{index + 1:04d}"
        start = dates[0] + pd.Timedelta(days=index * STEP_DAYS)
        end = start + pd.Timedelta(days=WINDOW_DAYS - 1)
        segment = signal.loc[start:end]
        values = segment.to_numpy(dtype=float)
        if perturbation is not None and chunk_id == TARGET:
            values = values * perturbation(np.arange(values.size, dtype=float))
        # Trends normalizes each window by its own maximum.
        values = np.rint(100.0 * values / values.max())
        for date_value, value in zip(segment.index, values, strict=True):
            rows.append(
                {
                    "series_id": "s",
                    "pull_id": "P001",
                    "chunk_id": chunk_id,
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


def _closure_and_deviation(perturbation=None) -> tuple[float, float]:
    """Maximum triangle-closure error and maximum per-chunk log deviation."""

    result = OverlapGraphCalibrator(CalibrationConfig(), min_overlap_days=10).fit(
        _chunks(perturbation), baseline_start=START, baseline_end=END
    )

    lookup: dict[tuple[str, str], float] = {}
    for row in result.edges.itertuples():
        lookup[(row.chunk_i, row.chunk_j)] = float(row.log_ratio)
        lookup[(row.chunk_j, row.chunk_i)] = -float(row.log_ratio)
    nodes = sorted({c for pair in lookup for c in pair})
    closures = [
        abs(lookup[(i, j)] + lookup[(j, k)] - lookup[(i, k)])
        for n, i in enumerate(nodes)
        for m, j in enumerate(nodes[n + 1 :], n + 1)
        for k in nodes[m + 1 :]
        if (i, j) in lookup and (j, k) in lookup and (i, k) in lookup
    ]

    reference = result.full_series.set_index("historical_date")["value"]
    deviations = []
    for _chunk_id, group in result.calibrated_observations.groupby("chunk_id"):
        aligned = group.set_index("historical_date")["calibrated_value"]
        common = aligned.index.intersection(reference.index)
        a = aligned.loc[common].to_numpy(dtype=float)
        b = reference.loc[common].to_numpy(dtype=float)
        ok = (a > 0) & (b > 0) & np.isfinite(a) & np.isfinite(b)
        deviations.append(abs(float(np.mean(np.log(a[ok]) - np.log(b[ok])))))

    return max(closures), max(deviations)


def test_uniform_rescale_is_invisible_to_every_check():
    """The parameter, not a violation: it must be absorbed and it must be exact."""

    baseline_closure, baseline_deviation = _closure_and_deviation()
    for factor in (1.05, 1.20, 2.00):
        closure, deviation = _closure_and_deviation(lambda days, f=factor: np.full(days.size, f))
        assert abs(closure - baseline_closure) < 1e-9
        assert abs(deviation - baseline_deviation) < 1e-9


def test_cycle_closure_responds_to_a_trend():
    """A drifting scale is not a scale, so closure must break."""

    baseline, _ = _closure_and_deviation()
    trended, _ = _closure_and_deviation(lambda days: np.exp(0.05 * days / 100.0))
    assert trended > 2.0 * baseline


def test_per_chunk_deviation_never_responds():
    """Pin the zero-power finding so the number is never reported as evidence."""

    _, baseline = _closure_and_deviation()
    _, trended = _closure_and_deviation(lambda days: np.exp(0.10 * days / 100.0))
    _, waved = _closure_and_deviation(
        lambda days: np.exp(0.10 * np.sin(2 * np.pi * days / 60.0))
    )
    # It moves at most trivially, and never in proportion to a 10% distortion.
    assert trended < baseline + 0.05
    assert waved < baseline + 0.05
