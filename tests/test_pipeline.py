import numpy as np

from racergt.pipeline import RacerGTPipeline
from racergt.simulation import SimulationSettings, simulate_racergt_data


def test_end_to_end_pipeline(small_config):
    small_config.design.day_offsets = [0, 1, 7]
    small_config.design.streams = ["A", "B"]
    small_config.decision.min_unique_pulls = 2
    small_config.consensus.weight_cap = 0.8
    sim = simulate_racergt_data(
        small_config,
        SimulationSettings(random_seed=5, exact_duplicate_fraction=0.0, chunk_noise_sd=0.02),
    )
    result = RacerGTPipeline(small_config).fit(sim.raw_chunks, sim.benchmark)
    merged = result.final_series.merge(sim.truth, on="historical_date")
    corr = np.corrcoef(merged["value"], merged["true_index"])[0, 1]
    assert corr > 0.85
    assert result.audit.passed
    assert len(result.calibrations) == 6
    assert result.decision.status in {"PASS", "FAIL", "REVIEW"}
