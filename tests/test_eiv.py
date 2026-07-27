import numpy as np

from racergt.eiv import reliability_corrected_ols


def test_eiv_reduces_attenuation():
    rng = np.random.default_rng(4)
    n = 3000
    x_true = rng.normal(size=n)
    sigma_u = 0.8
    x_obs = x_true + rng.normal(0, sigma_u, n)
    y = 2.0 * x_true + rng.normal(0, 1, n)
    naive = np.linalg.lstsq(np.column_stack([np.ones(n), x_obs]), y, rcond=None)[0][1]
    corrected = reliability_corrected_ols(y, x_obs, sigma_u**2, hac_lags=0)
    assert abs(corrected.coefficient - 2.0) < abs(naive - 2.0)
