from __future__ import annotations

from datetime import date

import pytest

from racergt.config import QuerySpec, RacerGTConfig


@pytest.fixture
def small_config() -> RacerGTConfig:
    config = RacerGTConfig(
        query=QuerySpec(
            series_id="test",
            keyword="test keyword",
            geo="US",
            historical_start=date(2024, 1, 1),
            historical_end=date(2024, 8, 31),
            baseline_start=date(2024, 1, 1),
            baseline_end=date(2024, 8, 31),
        )
    )
    config.chunking.window_days = 90
    config.chunking.step_days = 30
    config.chunking.min_overlap_days = 10
    config.decision.min_unique_pulls = 3
    config.decision.min_spectral_effective_pulls = 1.2
    config.decision.min_detection_kappa = -1.0
    config.decision.min_level_generalizability = 0.0
    config.decision.min_innovation_generalizability = 0.0
    config.decision.max_convergence_mae_100 = 1.0
    config.decision.max_benchmark_standardized_rmse = 10.0
    return config
