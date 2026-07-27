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


def test_sequential_stitch_matches_the_graph_without_noise(small_config):
    """Pin the baseline implementation to the estimator it is compared against.

    With no chunk noise, no rounding, and the lognormal correction disabled, a
    spanning path and the full graph must recover the same scales: every edge is
    exact, so how they are combined cannot matter. If this drifts, the comparison
    in the manuscript is measuring an implementation difference rather than the
    difference between sequential and global calibration.
    """

    from racergt.baselines import sequential_stitch
    from racergt.schema import coerce_raw_chunks
    from racergt.simulation import SimulationSettings, simulate_racergt_data

    simulation = simulate_racergt_data(
        small_config,
        SimulationSettings(
            random_seed=5,
            chunk_noise_sd=0.0,
            integer_rounding=False,
            exact_duplicate_fraction=0.0,
        ),
    )
    data = coerce_raw_chunks(simulation.raw_chunks)
    one_pull = data[data["pull_id"] == sorted(data["pull_id"].unique())[0]]
    calibration = small_config.calibration.model_copy(
        update={"lognormal_bias_correction": False}
    )

    graph = OverlapGraphCalibrator(
        calibration, min_overlap_days=small_config.chunking.min_overlap_days
    ).fit(
        one_pull,
        baseline_start=small_config.query.baseline_start,
        baseline_end=small_config.query.baseline_end,
    )
    stitched = sequential_stitch(
        one_pull,
        calibration,
        min_overlap_days=small_config.chunking.min_overlap_days,
        baseline_start=small_config.query.baseline_start,
        baseline_end=small_config.query.baseline_end,
    )
    merged = graph.full_series.merge(
        stitched.full_series, on="historical_date", suffixes=("_graph", "_seq")
    )
    assert np.max(np.abs(merged["value_graph"] - merged["value_seq"])) < 1e-8
