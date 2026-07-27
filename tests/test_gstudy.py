import numpy as np
import pandas as pd

from racergt.gstudy import run_gstudy


def test_balanced_gstudy(small_config):
    rng = np.random.default_rng(3)
    rows = []
    dates = pd.date_range("2024-01-01", periods=120)
    truth = rng.normal(0, 5, len(dates))
    for d in range(3):
        for s in ["A", "B"]:
            for t, date in enumerate(dates):
                rows.append(
                    {
                        "historical_date": date,
                        "pull_id": f"D{d}{s}",
                        "collection_day": d,
                        "stream_id": s,
                        "replicate_id": "1",
                        "value": truth[t] + rng.normal(0, 1),
                    }
                )
    data = pd.DataFrame(rows)
    result = run_gstudy(data, "level", small_config.gstudy)
    assert 0 <= result.coefficients["generalizability_coefficient"] <= 1
    assert result.diagnostics["n_collection_days"] == 3
    assert set(result.variance_components["component"]) == {"T", "D", "S", "TD", "TS", "DS", "TDS", "E"}
