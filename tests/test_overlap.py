import numpy as np

from racergt.overlap import OverlapGraphCalibrator
from racergt.simulation import SimulationSettings, simulate_racergt_data


def test_overlap_calibration_recovers_shape(small_config):
    small_config.design.day_offsets = [0]
    small_config.design.streams = ["A", "B"]
    sim = simulate_racergt_data(
        small_config,
        SimulationSettings(random_seed=1, exact_duplicate_fraction=0.0, chunk_noise_sd=0.01),
    )
    pull = sim.raw_chunks[sim.raw_chunks["pull_id"] == "P001"]
    result = OverlapGraphCalibrator(
        small_config.calibration, small_config.chunking.min_overlap_days
    ).fit(pull, small_config.query.baseline_start, small_config.query.baseline_end)
    merged = result.full_series.merge(sim.truth, on="historical_date")
    corr = np.corrcoef(merged["value"], merged["true_index"])[0, 1]
    assert result.diagnostics["connected"]
    assert corr > 0.90
    assert np.isfinite(result.full_series["value"]).all()
