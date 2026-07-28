"""The variance-heterogeneity option: does it do what it claims, and only that.

The default Monte Carlo gives every pull the same error structure, so the
minimum-variance weights are equal weights by construction and covariance
adjustment has nothing to exploit. `retrieval_noise_ladder` varies how noisy the
pulls are, which is the other thing those weights exist for.

Three properties have to hold or the scenario is not what the manuscript says it
is: the default has to reproduce the previous behaviour exactly, the noise budget
has to move between pulls rather than grow, and the assignment must not line up
with a design facet -- heterogeneity along collection day or stream is a facet
effect the G-study already reports, not something only the residual covariance can
see.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from scipy import stats

from racergt.simulation import SimulationSettings, simulate_racergt_data

LADDER = 12.0
SEED = 4242


def _simulate(config, **overrides):
    return simulate_racergt_data(
        config, SimulationSettings(random_seed=SEED, exact_duplicate_fraction=0.0, **overrides)
    )


def _pull_dispersion(raw: pd.DataFrame) -> pd.Series:
    """Per-pull spread about the cross-pull median, as a proxy for its noise scale."""

    wide = raw.pivot_table(
        index="historical_date", columns="pull_id", values="value", aggfunc="mean"
    )
    residuals = wide.sub(wide.median(axis=1), axis=0)
    return residuals.std(axis=0, ddof=1)


def test_default_ladder_reproduces_the_previous_behaviour_exactly(small_config):
    """Not approximately. A new option that perturbs the random stream would
    silently invalidate every published Monte Carlo number."""

    default = _simulate(small_config)
    explicit_one = _simulate(small_config, retrieval_noise_ladder=1.0)

    pd.testing.assert_frame_equal(default.raw_chunks, explicit_one.raw_chunks)
    pd.testing.assert_frame_equal(default.truth, explicit_one.truth)


def test_ladder_spreads_the_pull_noise(small_config):
    """The point of the option, stated as a ratio the diagnostics could see."""

    homogeneous = _pull_dispersion(_simulate(small_config).raw_chunks)
    laddered = _pull_dispersion(_simulate(small_config, retrieval_noise_ladder=LADDER).raw_chunks)

    assert homogeneous.max() / homogeneous.min() < 3.0
    assert laddered.max() / laddered.min() > 2.0 * (homogeneous.max() / homogeneous.min())


def test_ladder_redistributes_rather_than_raises_the_noise_budget(small_config):
    """Exponents are symmetric about zero, so the geometric mean of the scales is
    one. Without this the heterogeneous scenarios would simply be noisier, and any
    RMSE difference would be confounded with the noise level."""

    homogeneous = _pull_dispersion(_simulate(small_config).raw_chunks)
    laddered = _pull_dispersion(_simulate(small_config, retrieval_noise_ladder=LADDER).raw_chunks)

    ratio = float(np.exp(np.log(laddered).mean()) / np.exp(np.log(homogeneous).mean()))
    assert 0.75 < ratio < 1.35


def test_ladder_is_not_aligned_with_the_design_facets(small_config):
    """Heterogeneity that follows collection day or stream is a facet effect the
    G-study already decomposes. Only heterogeneity the facets cannot explain is
    something the residual covariance has to find, so the assignment is shuffled
    and this test is what holds that in place."""

    simulation = _simulate(small_config, retrieval_noise_ladder=LADDER)
    dispersion = _pull_dispersion(simulation.raw_chunks)

    facets = (
        simulation.raw_chunks[["pull_id", "collection_day", "stream_id"]]
        .drop_duplicates("pull_id")
        .set_index("pull_id")
    )
    aligned = facets.join(dispersion.rename("dispersion")).dropna()

    for facet in ("collection_day", "stream_id"):
        groups = [g["dispersion"].to_numpy() for _, g in aligned.groupby(facet) if len(g) > 1]
        if len(groups) < 2:
            continue
        _, p_value = stats.f_oneway(*groups)
        assert p_value > 0.05, f"noise scale tracks {facet} (p={p_value:.4f})"


def test_additive_noise_default_reproduces_the_multiplicative_behaviour(small_config):
    """The control must be opt-in and cost nothing when off."""

    default = _simulate(small_config, retrieval_noise_ladder=LADDER)
    explicit = _simulate(
        small_config, retrieval_noise_ladder=LADDER, additive_retrieval_noise=False
    )
    pd.testing.assert_frame_equal(default.raw_chunks, explicit.raw_chunks)


def test_additive_noise_changes_the_series_without_changing_its_level(small_config):
    """It is a different error scale, not a different signal."""

    multiplicative = _simulate(small_config, retrieval_noise_ladder=LADDER).raw_chunks
    additive = _simulate(
        small_config, retrieval_noise_ladder=LADDER, additive_retrieval_noise=True
    ).raw_chunks

    assert not np.allclose(
        multiplicative["value"].to_numpy(float), additive["value"].to_numpy(float)
    )
    assert additive["value"].mean() == pytest.approx(multiplicative["value"].mean(), rel=0.10)


def test_clipping_in_the_additive_control_is_warned_about_not_silent():
    """A clipped run is a nonlinearity the multiplicative case does not have, so it
    is no longer the control it claims to be. Silence would let it be compared as
    though the only difference were the error scale."""

    from datetime import date

    from racergt.config import QuerySpec, RacerGTConfig

    config = RacerGTConfig(
        query=QuerySpec(
            series_id="clip",
            keyword="k",
            geo="US",
            historical_start=date(2024, 1, 1),
            historical_end=date(2024, 12, 31),
            baseline_start=date(2024, 1, 1),
            baseline_end=date(2024, 12, 31),
        )
    )
    config.design.day_offsets = [0, 1, 7]
    config.design.streams = ["A", "B", "C"]
    config.chunking.window_days = 120
    config.chunking.step_days = 30
    config.chunking.min_overlap_days = 14

    with pytest.warns(RuntimeWarning, match="no longer a purely additive control"):
        simulate_racergt_data(
            config,
            SimulationSettings(
                random_seed=1200,
                exact_duplicate_fraction=0.10,
                retrieval_noise_ladder=40.0,
                additive_retrieval_noise=True,
            ),
        )


def test_ladder_below_one_is_the_same_spread_as_its_reciprocal(small_config):
    """A ladder is a ratio, so 1/k and k describe the same design. Guards against
    an implementation that only widens in one direction."""

    up = _pull_dispersion(_simulate(small_config, retrieval_noise_ladder=LADDER).raw_chunks)
    down = _pull_dispersion(_simulate(small_config, retrieval_noise_ladder=1 / LADDER).raw_chunks)

    assert up.max() / up.min() == pytest.approx(down.max() / down.min(), rel=0.35)
