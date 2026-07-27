import numpy as np
import pandas as pd
import pytest

from racergt.gstudy import generalizability_coefficients, run_gstudy


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


@pytest.mark.parametrize(
    ("n_days", "n_streams", "n_replicates"),
    [(3, 3, 1), (3, 3, 2), (7, 3, 2), (7, 3, 3)],
)
def test_coefficients_match_the_documented_formulas(n_days, n_streams, n_replicates):
    """Pin G and Phi to the formulas printed in the mathematical appendix.

    The appendix once divided sigma^2_TDS by n_d*n_s*n_r instead of n_d*n_s, which
    agrees with the code only when n_r == 1 and silently overstates G otherwise. The
    replicated grid below includes n_r > 1 so that reintroducing that error fails here
    rather than in a PDF nobody recompiles.
    """

    components = {"T": 100.0, "D": 1.0, "S": 1.0, "TD": 4.0, "TS": 3.0, "DS": 0.5,
                  "TDS": 6.0, "E": 8.0}
    relative = (
        components["TD"] / n_days
        + components["TS"] / n_streams
        + components["TDS"] / (n_days * n_streams)
        + components["E"] / (n_days * n_streams * n_replicates)
    )
    absolute = relative + (
        components["D"] / n_days
        + components["S"] / n_streams
        + components["DS"] / (n_days * n_streams)
    )
    expected_g = components["T"] / (components["T"] + relative)
    expected_phi = components["T"] / (components["T"] + absolute)

    observed = generalizability_coefficients(components, n_days, n_streams, n_replicates)
    assert observed["relative_error_variance"] == pytest.approx(relative)
    assert observed["absolute_error_variance"] == pytest.approx(absolute)
    assert observed["generalizability_coefficient"] == pytest.approx(expected_g)
    assert observed["dependability_coefficient"] == pytest.approx(expected_phi)

    # The collapsed form that used to appear in the appendix must stay distinguishable.
    collapsed = (
        components["TD"] / n_days
        + components["TS"] / n_streams
        + (components["TDS"] + components["E"]) / (n_days * n_streams * n_replicates)
    )
    if n_replicates == 1:
        assert collapsed == pytest.approx(relative)
    else:
        assert collapsed < relative
