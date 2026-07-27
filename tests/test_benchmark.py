import numpy as np
import pandas as pd

from racergt.benchmark import temporal_benchmark


def test_exact_temporal_benchmark(small_config):
    dates = pd.date_range("2024-01-01", periods=28)
    preliminary = pd.DataFrame({"historical_date": dates, "value": np.linspace(10, 20, 28)})
    benchmark = pd.DataFrame(
        {
            "period_start": [dates[0], dates[14]],
            "period_end": [dates[13], dates[27]],
            "value": [15.0, 25.0],
            "se": [1.0, 1.0],
        }
    )
    cfg = small_config.benchmark.model_copy(update={"mode": "exact", "preserve_nonnegative": False})
    result = temporal_benchmark(preliminary, benchmark, cfg)
    means = [
        result.series.loc[:13, "value"].mean(),
        result.series.loc[14:, "value"].mean(),
    ]
    assert np.allclose(means, [15, 25], atol=1e-7)
