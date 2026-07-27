import numpy as np
from racergt import (
    calibrate_overlap_graph,
    covariance_adjusted_consensus,
    create_balanced_design,
    create_chunk_windows,
    run_replay,
    simulate_gt_chunks,
)

def test_balanced_design():
    design=create_balanced_design()
    assert len(design)==42
    assert design.groupby(["collection_day","stream"]).size().eq(2).all()

def test_chunk_overlap():
    windows=create_chunk_windows("2020-01-01","2020-12-31",window_days=120,step_days=60)
    assert len(windows)>=4
    assert (windows.window_start.iloc[1] <= windows.window_end.iloc[0])

def test_end_to_end_reconstruction():
    chunks,truth=simulate_gt_chunks(n_dates=240,n_pulls=9,seed=7)
    calibration=calibrate_overlap_graph(chunks)
    consensus=covariance_adjusted_consensus(calibration.reconstructed)
    assert calibration.connected
    assert consensus.series.consensus.notna().all()
    assert consensus.effective_pulls>=1

def test_replay_quality():
    metrics=run_replay(seed=42)
    assert np.isfinite(metrics["rmse"])
    assert metrics["correlation"]>0.9
