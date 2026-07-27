from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
import statsmodels.api as sm


@dataclass
class EIVResult:
    coefficient: float
    standard_error: float
    t_value: float
    p_value: float
    reliability_ratio: float
    denominator_uncorrected: float
    denominator_corrected: float
    control_coefficients: pd.Series
    diagnostics: dict


def _as_2d_controls(controls: np.ndarray | pd.DataFrame | None, n: int) -> np.ndarray:
    if controls is None:
        return np.ones((n, 1), dtype=float)
    arr = np.asarray(controls, dtype=float)
    if arr.ndim == 1:
        arr = arr[:, None]
    if arr.shape[0] != n:
        raise ValueError("controls must have the same number of rows as y and x")
    if not np.allclose(arr[:, 0], 1.0):
        arr = np.column_stack([np.ones(n), arr])
    return arr


def _newey_west_long_run_variance(series: np.ndarray, max_lags: int) -> float:
    g = np.asarray(series, dtype=float)
    g = g - np.mean(g)
    n = len(g)
    gamma0 = float(g @ g / n)
    lrv = gamma0
    for lag in range(1, min(max_lags, n - 1) + 1):
        weight = 1.0 - lag / (max_lags + 1.0)
        gamma = float(g[lag:] @ g[:-lag] / n)
        lrv += 2.0 * weight * gamma
    return max(lrv, 0.0)


def reliability_corrected_ols(
    y: np.ndarray | pd.Series,
    x_observed: np.ndarray | pd.Series,
    measurement_error_variance: float | np.ndarray | pd.Series,
    controls: np.ndarray | pd.DataFrame | None = None,
    hac_lags: int = 7,
) -> EIVResult:
    """Correct attenuation for one noisy GT predictor with optional exact controls.

    The method residualizes y and the observed GT predictor on controls, then subtracts
    the expected measurement-error sum of squares from the predictor denominator.
    Under classical additive measurement error, the resulting moment estimator is
    consistent when the supplied error variance is correct.
    """

    yv = np.asarray(y, dtype=float).reshape(-1)
    xv = np.asarray(x_observed, dtype=float).reshape(-1)
    if len(yv) != len(xv):
        raise ValueError("y and x_observed must have equal length")
    n = len(yv)
    z = _as_2d_controls(controls, n)
    sigma_u2 = np.asarray(measurement_error_variance, dtype=float)
    if sigma_u2.ndim == 0:
        sigma_u2 = np.full(n, float(sigma_u2))
    sigma_u2 = sigma_u2.reshape(-1)
    if len(sigma_u2) != n or np.any(sigma_u2 < 0):
        raise ValueError("measurement_error_variance must be nonnegative and length n")

    finite = np.isfinite(yv) & np.isfinite(xv) & np.isfinite(sigma_u2) & np.isfinite(z).all(axis=1)
    yv, xv, sigma_u2, z = yv[finite], xv[finite], sigma_u2[finite], z[finite]
    n = len(yv)
    if n <= z.shape[1] + 2:
        raise ValueError("Insufficient observations")

    z_pinv = np.linalg.pinv(z)
    hat = z @ z_pinv
    m = np.eye(n) - hat
    yr = m @ yv
    xr = m @ xv
    denominator_uncorrected = float(xr @ xr)
    # For heteroskedastic measurement error, E[u'Mu] = trace(M Omega_u).
    correction = float(np.sum(np.diag(m) * sigma_u2))
    denominator_corrected = denominator_uncorrected - correction
    if denominator_corrected <= 0:
        raise ValueError(
            "Corrected predictor variance is non-positive; GT measurement error is too large "
            "for point identification under this model."
        )
    numerator = float(xr @ yr)
    beta = numerator / denominator_corrected

    error = yr - beta * xr
    # Corrected scalar moment: x_t e_t + beta * M_tt sigma_u,t^2.
    moment = xr * error + beta * np.diag(m) * sigma_u2
    lrv = _newey_west_long_run_variance(moment, hac_lags)
    derivative = denominator_corrected / n
    se = float(np.sqrt(lrv / n) / abs(derivative))
    t_value = beta / se if se > 0 else np.nan
    from scipy.stats import norm

    p_value = float(2.0 * norm.sf(abs(t_value))) if np.isfinite(t_value) else np.nan
    control_beta = np.linalg.lstsq(z, yv - beta * xv, rcond=None)[0]
    reliability_ratio = denominator_corrected / denominator_uncorrected
    names = ["intercept"] + [f"control_{i}" for i in range(1, z.shape[1])]
    return EIVResult(
        coefficient=float(beta),
        standard_error=se,
        t_value=float(t_value),
        p_value=p_value,
        reliability_ratio=float(reliability_ratio),
        denominator_uncorrected=denominator_uncorrected,
        denominator_corrected=denominator_corrected,
        control_coefficients=pd.Series(control_beta, index=names),
        diagnostics={
            "n_observations": n,
            "hac_lags": hac_lags,
            "measurement_error_correction": correction,
            "assumption": "classical additive GT measurement error independent of latent signal, outcome error, and controls",
        },
    )


def simex_ols(
    y: np.ndarray | pd.Series,
    x_observed: np.ndarray | pd.Series,
    measurement_error_sd: float | np.ndarray | pd.Series,
    controls: np.ndarray | pd.DataFrame | None = None,
    lambdas: tuple[float, ...] = (0.0, 0.5, 1.0, 1.5, 2.0),
    simulations: int = 200,
    random_seed: int = 20260727,
) -> dict:
    """Quadratic SIMEX correction for a single noisy GT predictor."""

    yv = np.asarray(y, dtype=float).reshape(-1)
    xv = np.asarray(x_observed, dtype=float).reshape(-1)
    n = len(yv)
    z = _as_2d_controls(controls, n)
    sd = np.asarray(measurement_error_sd, dtype=float)
    if sd.ndim == 0:
        sd = np.full(n, float(sd))
    sd = sd.reshape(-1)
    finite = np.isfinite(yv) & np.isfinite(xv) & np.isfinite(sd) & np.isfinite(z).all(axis=1)
    yv, xv, sd, z = yv[finite], xv[finite], sd[finite], z[finite]
    rng = np.random.default_rng(random_seed)
    design_base = z
    beta_by_lambda = []
    simulation_draws = []
    for lam in lambdas:
        estimates = []
        n_sim = 1 if lam == 0 else simulations
        for _ in range(n_sim):
            noise = np.zeros_like(xv) if lam == 0 else rng.normal(0.0, np.sqrt(lam) * sd)
            x_sim = xv + noise
            design = np.column_stack([design_base, x_sim])
            beta = np.linalg.lstsq(design, yv, rcond=None)[0][-1]
            estimates.append(float(beta))
        mean_beta = float(np.mean(estimates))
        beta_by_lambda.append(mean_beta)
        simulation_draws.extend(
            {"lambda": lam, "simulation": i + 1, "coefficient": val}
            for i, val in enumerate(estimates)
        )
    poly = np.polyfit(np.asarray(lambdas), np.asarray(beta_by_lambda), deg=2)
    corrected = float(np.polyval(poly, -1.0))
    return {
        "coefficient": corrected,
        "lambda_curve": pd.DataFrame({"lambda": lambdas, "mean_coefficient": beta_by_lambda}),
        "simulation_draws": pd.DataFrame(simulation_draws),
        "quadratic_coefficients": poly,
        "assumption": "known classical measurement-error standard deviation; quadratic extrapolation to lambda=-1",
    }
