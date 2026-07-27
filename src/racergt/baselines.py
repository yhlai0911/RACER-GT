"""Reference implementations of alternative construction methods.

Nothing here is part of the RACER-GT estimator. These are the methods RACER-GT
claims to improve on, implemented so that the claim can be tested rather than
asserted. Each one reuses RACER-GT's own edge estimator and aggregation, so a
difference in accuracy comes from the method under comparison and not from an
incidental difference in tuning.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import pairwise

import numpy as np
import pandas as pd

from .config import CalibrationConfig
from .overlap import huber_location


@dataclass
class StitchResult:
    full_series: pd.DataFrame
    chunk_scales: pd.DataFrame
    diagnostics: dict


def sequential_stitch(
    data: pd.DataFrame,
    config: CalibrationConfig,
    min_overlap_days: int = 14,
    baseline_start: pd.Timestamp | str | None = None,
    baseline_end: pd.Timestamp | str | None = None,
) -> StitchResult:
    """Sequential stitching of overlapping chunks, the conventional reassembly.

    Chunks are ordered in time and joined pairwise: chunk 2 is rescaled onto
    chunk 1, chunk 3 onto the rescaled chunk 2, and so on. This is what the
    applied literature usually does with multi-window Google Trends downloads,
    and it is the procedure that the manuscript's failure mode F1 argues against:
    with estimated log-scale corrections, the calibrated value of chunk J carries
    the accumulated error of every preceding join, so the variance of that error
    grows along the chain.

    The edge estimator, the minimum-value gate, and the within-day aggregation
    are identical to those used by :class:`~racergt.overlap.OverlapGraphCalibrator`.
    The only difference is that this function walks a spanning path while the
    graph calibrator solves all usable overlaps jointly. Any accuracy gap is
    therefore attributable to that choice alone.
    """

    frame = data.copy()
    frame["historical_date"] = pd.to_datetime(frame["historical_date"]).dt.normalize()
    frame["window_start"] = pd.to_datetime(frame["window_start"]).dt.normalize()
    frame["value"] = pd.to_numeric(frame["value"], errors="coerce").astype(float)
    pull_id = str(frame["pull_id"].iloc[0])
    series_id = str(frame["series_id"].iloc[0])

    order = (
        frame.groupby("chunk_id")["window_start"].min().sort_values().index.astype(str).tolist()
    )
    by_chunk = {
        str(cid): group.set_index("historical_date")["value"].sort_index()
        for cid, group in frame.groupby("chunk_id")
    }

    # Walk the chain, accumulating log scales relative to the first chunk.
    log_scales = {order[0]: 0.0}
    joins, broken = [], 0
    for previous, current in pairwise(order):
        left, right = by_chunk[previous], by_chunk[current]
        common = left.index.intersection(right.index)
        usable = [
            d
            for d in common
            if left.loc[d] >= config.min_value and right.loc[d] >= config.min_value
        ]
        if len(usable) < min_overlap_days:
            # The chain is broken. Sequential stitching has no way to recover a
            # scale across a gap, which is itself part of the comparison: the
            # graph calibrator would still identify it through a longer overlap.
            broken += 1
            log_scales[current] = log_scales[previous]
            joins.append({"from": previous, "to": current, "n_usable": len(usable), "delta": np.nan})
            continue
        ratios = np.log(left.loc[usable].to_numpy(dtype=float)) - np.log(
            right.loc[usable].to_numpy(dtype=float)
        )
        delta, _scale, _variance = huber_location(
            ratios, c=config.huber_c, max_iter=config.max_huber_iter, tol=config.huber_tol
        )
        # delta estimates ell_previous - ell_current, so the chain subtracts it.
        log_scales[current] = log_scales[previous] - float(delta)
        joins.append(
            {"from": previous, "to": current, "n_usable": len(usable), "delta": float(delta)}
        )

    calibrated = frame.copy()
    calibrated["chunk_id"] = calibrated["chunk_id"].astype(str)
    calibrated["log_scale"] = calibrated["chunk_id"].map(log_scales)
    calibrated["calibrated_value"] = calibrated["value"] * np.exp(-calibrated["log_scale"])

    # Equal-weight within-day aggregation: sequential stitching carries no
    # per-chunk variance estimate to weight by, which is part of what it gives up.
    daily = (
        calibrated.groupby("historical_date", as_index=False)["calibrated_value"]
        .mean()
        .rename(columns={"calibrated_value": "value"})
    )
    daily.insert(0, "pull_id", pull_id)
    daily.insert(0, "series_id", series_id)

    if config.normalization != "none":
        start = (
            pd.Timestamp(baseline_start).normalize()
            if baseline_start is not None
            else daily["historical_date"].min()
        )
        end = (
            pd.Timestamp(baseline_end).normalize()
            if baseline_end is not None
            else daily["historical_date"].max()
        )
        mask = daily["historical_date"].between(start, end)
        denominator = (
            float(daily.loc[mask, "value"].max())
            if config.normalization == "max_100"
            else float(daily.loc[mask, "value"].mean())
        )
        if not np.isfinite(denominator) or denominator <= 0:
            raise ValueError("Normalization denominator is non-positive")
        daily["value"] *= 100.0 / denominator

    scales = pd.DataFrame(
        {"chunk_id": list(log_scales), "log_scale": list(log_scales.values())}
    )
    diagnostics = {
        "method": "sequential_stitch",
        "pull_id": pull_id,
        "n_chunks": len(order),
        "n_joins": len(joins),
        "n_broken_joins": broken,
        # The chain length is the number of joins whose error the last chunk carries.
        "chain_length": len(order) - 1,
    }
    return StitchResult(full_series=daily, chunk_scales=scales, diagnostics=diagnostics)
