"""Factor analysis of GT indices whose measurement error variance is supplied.

A construct is rarely one keyword. The established practice in finance is to pick a
set of conceptually related terms, build an index for each, and take the first
principal component (Da, Engelberg and Gao 2015; Baker and Wurgler 2006). PCA,
however, assumes the inputs carry no measurement error, and Google Trends does. Noisy
inputs attenuate loadings and let the error covariance leak into the components.

RACER-GT is the one GT construction tool that emits a per-day standard error, so the
error variance can be subtracted before the eigendecomposition:

    E[S] = Lambda Lambda' + Psi + Omega_bar,   S_tilde = S - Omega_bar

Two things this module deliberately refuses to do. It does not project an indefinite
S_tilde back onto the PSD cone: under a correct model with a correct Omega the
expectation is Lambda Lambda' + Psi, which is positive semidefinite, so an indefinite
result says Omega is too large relative to the observed covariance rather than being a
numerical inconvenience to smooth over. And it does not pretend the supplied Omega is
a true daily variance: see the omega_* diagnostics.

The first component is not automatically the construct. GT series share large weekday
and holiday effects, and PC1 captures whatever varies most in common, so it may well
be "Mondays plus Christmas". Baker and Wurgler orthogonalized against macro variables
for exactly this reason. Version 1.0 does not orthogonalize; it reports
pc1_weekday_f_statistic and pc1_autocorr_lag7 so the question cannot be skipped.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

FACTOR_REQUIRED_COLUMNS = {"series_id", "historical_date", "value", "standard_error"}

# The upstream consensus multiplies a single global standard error by a local MAD
# ratio clipped to these bounds (consensus.py). Recovering the exact clip is not
# possible from the output alone, but a per-day SE sitting on either bound relative to
# the series median is evidence the clip was binding, which is what omega_clip_share
# reports. Keep these in sync with ConsensusConfig's implementation.
_UPSTREAM_CLIP_BOUNDS = (0.25, 4.0)
_ZERO_TOLERANCE = 1e-12


class IndefiniteCovarianceError(ValueError):
    """Raised when S - Omega_bar is not positive semidefinite.

    This is a result, not a failure mode to be repaired, but it says something
    narrower than it first appears. Under a correct model with a correct Omega the
    expectation of the corrected covariance is Lambda Lambda' + Psi, which is
    positive semidefinite, so this cannot happen. Losing semidefiniteness is
    therefore evidence that Omega is too large relative to the observed covariance:
    an overstated measurement error, a misspecified model, or finite-sample
    variation in S. It is not by itself evidence that the series set cannot support
    a factor.
    """


@dataclass
class FactorResult:
    loadings: pd.DataFrame
    scores: pd.DataFrame
    eigenvalues: np.ndarray
    explained_variance_ratio: np.ndarray
    corrected_covariance: pd.DataFrame
    diagnostics: dict

    def save(self, output_dir: str | Path) -> dict[str, Path]:
        output = Path(output_dir)
        output.mkdir(parents=True, exist_ok=True)
        paths = {
            "loadings": output / "factor_loadings.csv",
            "scores": output / "factor_scores.csv",
            "eigenvalues": output / "factor_eigenvalues.csv",
            "corrected_covariance": output / "error_corrected_covariance.csv",
            "diagnostics": output / "factor_diagnostics.json",
        }
        self.loadings.to_csv(paths["loadings"], index=True)
        self.scores.to_csv(paths["scores"], index=True)
        # Every eigenvalue is written, not just the retained ones: the discarded tail
        # is the evidence for how many factors there are, and a reader second-guessing
        # n_factors needs it. Only the retained factors have an explained-variance
        # ratio, so the column is padded rather than truncating the eigenvalues.
        ratios = np.full(len(self.eigenvalues), np.nan)
        ratios[: len(self.explained_variance_ratio)] = self.explained_variance_ratio
        pd.DataFrame(
            {
                "factor": [f"F{i + 1}" for i in range(len(self.eigenvalues))],
                "eigenvalue": self.eigenvalues,
                "explained_variance_ratio": ratios,
                "retained": np.arange(len(self.eigenvalues)) < len(self.explained_variance_ratio),
            }
        ).to_csv(paths["eigenvalues"], index=False)
        self.corrected_covariance.to_csv(paths["corrected_covariance"], index=True)
        paths["diagnostics"].write_text(
            json.dumps(self.diagnostics, indent=2, sort_keys=True, default=str),
            encoding="utf-8",
        )
        return paths


def _series_list_hash(series_ids: list[str]) -> str:
    """Hash the requested series set so a keyword list can be preregistered.

    Taken before any screening, because the preregistered object is what the
    researcher chose, not what survived the zero-share filter.
    """

    payload = json.dumps(sorted(series_ids), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _select_n_factors(eigenvalues: np.ndarray, total_variance: float) -> int:
    """Keep components explaining more than one average variable's worth of variance.

    Kaiser's rule is usually quoted as "eigenvalue above one", but the one is not a
    constant of nature: on a correlation matrix every diagonal entry is one, the trace
    is K, and the average eigenvalue is therefore exactly one. The argument is "keep
    what beats an average variable", and the number one is what that argument evaluates
    to on that particular matrix.

    Error correction breaks that calibration. The diagonal of S - Omega_bar is
    1 - omega_k, its trace is K(1 - mean omega), and its average eigenvalue is below
    one. Carrying the threshold of one across from the uncorrected matrix would keep
    systematically too few factors, and the factors it drops do not vanish --- they
    land in the residual and are read as series-specific noise.

    So the rule is restated on the matrix actually being decomposed: keep components
    above tr(S_tilde)/K. That is Kaiser's own argument applied to the right trace, and
    it is scale free, so standardizing changes nothing. Sensitivity to this choice is
    reported through n_factors_broken_stick and eigenvalue_gap_ratio rather than
    hidden.
    """

    if eigenvalues.size == 0:
        return 1
    threshold = total_variance / eigenvalues.size
    return max(1, int((eigenvalues > threshold).sum()))


def _broken_stick_count(eigenvalues: np.ndarray, total_variance: float) -> int:
    """Factors a broken-stick null would keep --- a deliberately stricter comparator.

    Break a stick of length tr(S_tilde) at K-1 uniform random points and the expected
    j-th longest piece is (tr/K) sum_{i=j}^{K} 1/i. It is the analytic stand-in for
    parallel analysis and it is known to be conservative, which is the point: reported
    next to the retained count, it shows whether the factor count is a property of the
    data or of the rule that was picked.
    """

    k = eigenvalues.size
    if k == 0:
        return 0
    expected = np.array(
        [total_variance * float(np.sum(1.0 / np.arange(j, k + 1))) / k for j in range(1, k + 1)]
    )
    # Sequential, not a count. The expected pieces shrink fast (the last is tr/K^2), so
    # counting every eigenvalue that clears its own bound lets the trailing noise
    # eigenvalues back in and makes this comparator look less strict than Kaiser, which
    # it is not. Stop at the first component that fails.
    below = np.flatnonzero(eigenvalues <= expected)
    return int(below[0]) if below.size else k


def _weekday_f_statistic(scores: np.ndarray, dates: pd.DatetimeIndex) -> float:
    """F statistic for regressing a component on weekday dummies.

    Under the null that the component is unrelated to the day of week this is an
    F(6, n-7) variate. A large value means the component is at least partly a calendar
    artefact rather than the construct.
    """

    n = scores.size
    if n < 15:
        return float("nan")
    dummies = pd.get_dummies(pd.Series(dates.dayofweek, dtype="category"), drop_first=True)
    design = np.column_stack([np.ones(n), dummies.to_numpy(dtype=float)])
    q = design.shape[1] - 1
    if n - design.shape[1] <= 0:
        return float("nan")
    coefficients, *_ = np.linalg.lstsq(design, scores, rcond=None)
    rss_full = float(np.sum((scores - design @ coefficients) ** 2))
    rss_null = float(np.sum((scores - scores.mean()) ** 2))
    if rss_full <= _ZERO_TOLERANCE:
        return float("inf") if rss_null > _ZERO_TOLERANCE else float("nan")
    return ((rss_null - rss_full) / q) / (rss_full / (n - design.shape[1]))


def _autocorrelation(values: np.ndarray, lag: int) -> float:
    if values.size <= lag + 2:
        return float("nan")
    a = values[:-lag]
    b = values[lag:]
    if np.std(a) <= _ZERO_TOLERANCE or np.std(b) <= _ZERO_TOLERANCE:
        return float("nan")
    return float(np.corrcoef(a, b)[0, 1])


def _clip_share(standard_errors: pd.DataFrame) -> float:
    """Fraction of per-day standard errors sitting on the upstream clip bounds.

    Heuristic, not an exact recovery. The upstream multiplier has median close to one,
    so the series median standard error approximates the unclipped base; days whose
    ratio to that median lands on a bound are days the clip was binding. Reported so a
    reader can see how often the supplied Omega was constrained rather than estimated.
    """

    ratios = standard_errors.divide(standard_errors.median(axis=0), axis=1)
    on_bound = np.zeros(ratios.shape, dtype=bool)
    for bound in _UPSTREAM_CLIP_BOUNDS:
        on_bound |= np.isclose(ratios.to_numpy(dtype=float), bound, rtol=1e-6, atol=1e-9)
    finite = np.isfinite(ratios.to_numpy(dtype=float))
    if not finite.any():
        return float("nan")
    return float(on_bound[finite].mean())


def _principal_decomposition(
    covariance: np.ndarray, n_factors: int
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Eigendecomposition ordered by descending eigenvalue.

    Returns all eigenvalues alongside the leading vectors and loadings, because the
    discarded eigenvalues carry the evidence for how many factors there are.
    """

    values, vectors = np.linalg.eigh(0.5 * (covariance + covariance.T))
    order = np.argsort(values)[::-1]
    values = values[order]
    vectors = vectors[:, order]
    lead_values = values[:n_factors]
    lead_vectors = vectors[:, :n_factors]
    loadings = lead_vectors * np.sqrt(np.maximum(lead_values, 0.0))
    return values, lead_vectors, loadings


def fit_error_corrected_factors(
    series: pd.DataFrame,
    n_factors: int | None = None,
    error_variance: pd.DataFrame | None = None,
    standardize: bool = True,
    max_zero_share: float = 0.50,
    allow_indefinite: bool = False,
    psd_tolerance: float = 1e-8,
) -> FactorResult:
    """Extract factors from GT indices after subtracting known measurement error.

    ``series`` is long, one row per series_id x historical_date, with the columns in
    FACTOR_REQUIRED_COLUMNS. The standard_error column is what ConsensusResult emits;
    the caller attaches a series_id to each consensus series.

    ``error_variance`` overrides that column with externally estimated variances, wide
    with historical_date as index and series_id as columns. Users of the official
    Trends API need this route: the API supplies no standard error, so Omega has to
    come from somewhere else.

    Raises IndefiniteCovarianceError when the corrected covariance loses positive
    semidefiniteness, unless ``allow_indefinite`` is set. The result is still returned
    in that case, with the diagnostics recording what happened.
    """

    missing = FACTOR_REQUIRED_COLUMNS.difference(series.columns)
    if missing:
        raise ValueError(f"Missing factor input columns: {sorted(missing)}")

    frame = series.copy()
    frame["historical_date"] = pd.to_datetime(frame["historical_date"]).dt.normalize()
    frame["series_id"] = frame["series_id"].astype(str)
    requested_ids = sorted(frame["series_id"].unique().tolist())
    if len(requested_ids) < 2:
        raise ValueError("At least two series are required for a factor model")

    values = frame.pivot(index="historical_date", columns="series_id", values="value")
    errors = frame.pivot(index="historical_date", columns="series_id", values="standard_error")

    # Screen before the date intersection: a series that is mostly zeros contributes a
    # near-constant column, which inflates the apparent common variance of whatever it
    # is paired with. Low search volume is a property of the keyword, not of the day.
    zero_shares = (values.abs() <= _ZERO_TOLERANCE).mean(axis=0)
    kept = zero_shares[zero_shares <= max_zero_share].index.tolist()
    dropped = sorted(set(values.columns).difference(kept))
    if len(kept) < 2:
        raise ValueError(
            f"Only {len(kept)} series survive the zero-share screen at "
            f"max_zero_share={max_zero_share}; a factor model needs at least two"
        )
    values = values[kept]
    errors = errors[kept]

    if error_variance is not None:
        supplied = error_variance.copy()
        supplied.index = pd.to_datetime(supplied.index).normalize()
        missing_series = set(kept).difference(supplied.columns)
        if missing_series:
            raise ValueError(f"error_variance lacks series: {sorted(missing_series)}")
        variances = supplied[kept]
        omega_source = "supplied"
    else:
        variances = errors**2
        omega_source = "consensus_se"

    n_days_before = len(values)
    combined = pd.concat({"value": values, "variance": variances}, axis=1).dropna(axis=0)
    if len(combined) < len(kept) + 2:
        raise ValueError(
            f"Only {len(combined)} days are jointly complete across {len(kept)} series"
        )
    aligned_values = combined["value"]
    aligned_variance = combined["variance"]
    dates = pd.DatetimeIndex(aligned_values.index)

    # Standardizing rescales the measurement error with the data, so Omega stays on the
    # same footing as S. Using the observed (uncorrected) standard deviation keeps the
    # corrected diagonal interpretable as one minus the error share.
    scales = aligned_values.std(axis=0, ddof=1)
    if (scales <= _ZERO_TOLERANCE).any():
        raise ValueError("Every series must have positive variation over the sample")
    if standardize:
        work_values = aligned_values.divide(scales, axis=1)
        work_variance = aligned_variance.divide(scales**2, axis=1)
    else:
        work_values = aligned_values
        work_variance = aligned_variance

    sample_covariance = work_values.cov(ddof=1)
    mean_omega = work_variance.mean(axis=0)
    corrected = sample_covariance.to_numpy(dtype=float) - np.diag(mean_omega.to_numpy(dtype=float))
    corrected = 0.5 * (corrected + corrected.T)

    all_values = np.linalg.eigvalsh(corrected)
    min_eigenvalue = float(all_values.min())
    is_psd = bool(min_eigenvalue >= -psd_tolerance)

    sorted_values = np.sort(all_values)[::-1]
    corrected_trace = float(np.trace(corrected))
    resolved_n_factors = (
        _select_n_factors(sorted_values, corrected_trace)
        if n_factors is None
        else int(n_factors)
    )
    if not 1 <= resolved_n_factors <= len(kept):
        raise ValueError(f"n_factors must be between 1 and {len(kept)}")

    eigenvalues, vectors, loadings = _principal_decomposition(corrected, resolved_n_factors)
    _, _, raw_loadings = _principal_decomposition(
        sample_covariance.to_numpy(dtype=float), resolved_n_factors
    )

    # Sign is not identified by the eigendecomposition. Anchor both solutions the same
    # way so the attenuation ratio compares like with like rather than a sign flip.
    for column in range(resolved_n_factors):
        if loadings[:, column].sum() < 0:
            loadings[:, column] *= -1.0
            vectors[:, column] *= -1.0
        if raw_loadings[:, column].sum() < 0:
            raw_loadings[:, column] *= -1.0

    centred = work_values.to_numpy(dtype=float) - work_values.to_numpy(dtype=float).mean(axis=0)
    lead_eigenvalues = np.maximum(eigenvalues[:resolved_n_factors], _ZERO_TOLERANCE)
    scores = (centred @ vectors) / np.sqrt(lead_eigenvalues)

    # Propagate the per-day error into the scores: with f_t = V'(y_t - ybar)/sqrt(lam),
    # Var(f_t) = V' Omega_t V / lam, and Omega_t is diagonal by assumption.
    squared_vectors = vectors**2
    score_variance = (work_variance.to_numpy(dtype=float) @ squared_vectors) / lead_eigenvalues
    score_errors = np.sqrt(np.maximum(score_variance, 0.0))

    factor_names = [f"F{i + 1}" for i in range(resolved_n_factors)]
    scores_frame = pd.DataFrame(scores, index=dates, columns=factor_names)
    for index, name in enumerate(factor_names):
        scores_frame[f"{name}_se"] = score_errors[:, index]
    scores_frame.index.name = "historical_date"

    loadings_frame = pd.DataFrame(loadings, index=kept, columns=factor_names)
    loadings_frame.index.name = "series_id"

    positive_total = float(np.sum(np.maximum(eigenvalues, 0.0)))
    explained = (
        np.maximum(eigenvalues[:resolved_n_factors], 0.0) / positive_total
        if positive_total > _ZERO_TOLERANCE
        else np.full(resolved_n_factors, np.nan)
    )

    # Compare the two solutions on the correlation scale, not the covariance scale. A
    # noisy matrix simply has more variance to hand out, so its raw loadings are
    # mechanically larger and their ratio to the corrected ones comes out above one ---
    # the opposite sign to the effect being measured. Dividing each loading by the
    # standard deviation implied by its own matrix puts both on the "correlation
    # between series and factor" scale, where classical attenuation is a ratio below
    # one and equals one exactly when there is no measurement error.
    raw_diagonal = np.diag(sample_covariance.to_numpy(dtype=float))
    corrected_diagonal = np.diag(corrected)
    attenuation_ratio: dict[str, float | None] = {}
    for index, series_id in enumerate(kept):
        raw_var = float(raw_diagonal[index])
        corrected_var = float(corrected_diagonal[index])
        # A non-positive corrected variance means the subtracted error exceeds this
        # series' observed variance. There is no correlation scale to speak of, and
        # reporting a number here would hide that.
        if raw_var <= _ZERO_TOLERANCE or corrected_var <= _ZERO_TOLERANCE:
            attenuation_ratio[series_id] = None
            continue
        corrected_scaled = float(loadings[index, 0]) / np.sqrt(corrected_var)
        if abs(corrected_scaled) <= _ZERO_TOLERANCE:
            attenuation_ratio[series_id] = None
            continue
        raw_scaled = float(raw_loadings[index, 0]) / np.sqrt(raw_var)
        attenuation_ratio[series_id] = float(raw_scaled / corrected_scaled)

    trace_s = float(np.trace(sample_covariance.to_numpy(dtype=float)))
    measurement_error_share = (
        float(mean_omega.sum() / trace_s) if trace_s > _ZERO_TOLERANCE else float("nan")
    )

    # How much of the retained count is the data and how much is the rule. The same
    # threshold applied to the uncorrected matrix isolates what the error correction
    # changed; broken-stick is a stricter rule on the same matrix; the gap ratio says
    # whether the cut sits in a real gap in the spectrum or in the middle of a slope.
    uncorrected_values = np.sort(np.linalg.eigvalsh(sample_covariance.to_numpy(dtype=float)))[::-1]
    n_factors_uncorrected = _select_n_factors(uncorrected_values, trace_s)
    n_factors_broken_stick = _broken_stick_count(sorted_values, corrected_trace)
    gap_ratio = (
        float(sorted_values[resolved_n_factors - 1] / sorted_values[resolved_n_factors])
        if resolved_n_factors < len(kept) and sorted_values[resolved_n_factors] > _ZERO_TOLERANCE
        else float("inf")
    )

    diagnostics = {
        "corrected_covariance_is_psd": is_psd,
        "min_eigenvalue_corrected": min_eigenvalue,
        "measurement_error_share": measurement_error_share,
        "attenuation_ratio": attenuation_ratio,
        "n_series_dropped_zero_share": len(dropped),
        "series_dropped_zero_share": dropped,
        "pc1_weekday_f_statistic": _weekday_f_statistic(scores[:, 0], dates),
        "pc1_autocorr_lag7": _autocorrelation(scores[:, 0], 7),
        # Omega provenance. The consensus standard error is a single global
        # sqrt(w' Sigma w) times a local MAD ratio clipped to [0.25, 4.0], so it is a
        # proxy for a daily variance, not a daily variance. Understating Omega leaves
        # the loadings attenuated while the output still looks corrected, so the
        # provenance travels with the result rather than living in a docstring.
        "omega_source": omega_source,
        "omega_is_daily_variance": omega_source == "supplied",
        "omega_clip_share": (
            _clip_share(errors.loc[dates]) if omega_source == "consensus_se" else float("nan")
        ),
        "omega_offdiagonal_assumed_zero": True,
        "series_list_sha256": _series_list_hash(requested_ids),
        "n_series_requested": len(requested_ids),
        "n_series_used": len(kept),
        "n_days_used": len(dates),
        "n_days_dropped_incomplete": int(n_days_before - len(dates)),
        "n_factors": resolved_n_factors,
        "n_factors_supplied": n_factors is not None,
        "n_factors_rule": "mean_eigenvalue_of_corrected",
        "n_factors_uncorrected_same_rule": n_factors_uncorrected,
        "n_factors_broken_stick": n_factors_broken_stick,
        "eigenvalue_gap_ratio": gap_ratio,
        "standardized": standardize,
        "max_zero_share": max_zero_share,
    }

    if not is_psd and not allow_indefinite:
        raise IndefiniteCovarianceError(
            f"Corrected covariance has minimum eigenvalue {min_eigenvalue:.6g}; "
            f"measurement error explains {measurement_error_share:.1%} of total variance. "
            "Under a correct model this cannot happen, so the supplied Omega is too "
            "large relative to the observed covariance -- overstated measurement "
            "error, a misspecified model, or finite-sample variation in S. "
            "Pass allow_indefinite=True to inspect the solution anyway."
        )

    return FactorResult(
        loadings=loadings_frame,
        scores=scores_frame,
        eigenvalues=eigenvalues,
        explained_variance_ratio=explained,
        corrected_covariance=pd.DataFrame(corrected, index=kept, columns=kept),
        diagnostics=diagnostics,
    )
