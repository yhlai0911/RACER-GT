"""Can the factor diagnostics fail? Injected perturbations say what each detects.

Same discipline as test_diagnostic_power.py, applied to the error-corrected factor
model. Every diagnostic gets a perturbation designed to break it, because a
diagnostic that passes on real data is worth nothing until it has been shown capable
of failing.

Three of the assumptions this module makes are biased in the direction that flatters
the conclusion, so those get the sharpest tests:

- Omega is treated as a daily variance when upstream supplies a clipped proxy.
  Understating it leaves the loadings attenuated while the output still reads as
  corrected. test_understated_omega_* pins how that shows up, and how it does not.
- Omega is assumed diagonal across series. Correlated measurement error would be
  absorbed as a common factor, inflating PC1. test_cross_series_correlated_error
  records what the diagnostics do and do not see.
- PC1 is assumed to be the construct. GT series share large weekday effects, so it
  may be the calendar. Both the detection and its reverse control are tested.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from racergt.factor import IndefiniteCovarianceError, fit_error_corrected_factors

N_DAYS = 520
START = "2023-01-01"
TRUE_LOADINGS = (0.90, 0.80, 0.85, 0.70, 0.75, 0.65)
UNIQUE_SD = 0.45
SEED = 20260728


def _panel(
    error_sd: float = 0.40,
    reported_error_scale: float = 1.0,
    weekday_amplitude: float = 0.0,
    common_error_sd: float = 0.0,
    factor_amplitude: float = 1.0,
    add_zero_series: bool = False,
    seed: int = SEED,
) -> pd.DataFrame:
    """A K-series panel from one latent construct, with knobs for each perturbation.

    ``reported_error_scale`` scales the standard_error column away from the error
    actually injected, which is how an understated Omega is simulated.
    ``common_error_sd`` adds a measurement error component shared across series,
    violating the diagonal-Omega assumption.
    """

    rng = np.random.default_rng(seed)
    dates = pd.date_range(START, periods=N_DAYS, freq="D")
    factor = factor_amplitude * rng.normal(size=N_DAYS)
    weekday_effect = weekday_amplitude * np.sin(2 * np.pi * dates.dayofweek.to_numpy() / 7.0)
    shared_error = common_error_sd * rng.normal(size=N_DAYS)

    rows = []
    for index, loading in enumerate(TRUE_LOADINGS):
        signal = loading * factor + rng.normal(scale=UNIQUE_SD, size=N_DAYS)
        error = rng.normal(scale=error_sd, size=N_DAYS) if error_sd > 0 else np.zeros(N_DAYS)
        values = 50.0 + 10.0 * (signal + weekday_effect + error + shared_error)
        reported = 10.0 * error_sd * reported_error_scale
        for position, date in enumerate(dates):
            rows.append(
                {
                    "series_id": f"S{index}",
                    "historical_date": date,
                    "value": float(values[position]),
                    "standard_error": reported,
                }
            )

    if add_zero_series:
        mostly_zero = np.where(rng.random(N_DAYS) < 0.90, 0.0, rng.uniform(1.0, 5.0, N_DAYS))
        for position, date in enumerate(dates):
            rows.append(
                {
                    "series_id": "S_SPARSE",
                    "historical_date": date,
                    "value": float(mostly_zero[position]),
                    "standard_error": 1.0,
                }
            )

    return pd.DataFrame(rows)


def _true_signal_correlations() -> np.ndarray:
    """corr(series, factor) once measurement error is removed --- the estimand."""

    loadings = np.asarray(TRUE_LOADINGS, dtype=float)
    return loadings / np.sqrt(loadings**2 + UNIQUE_SD**2)


def _correlation_scale_loadings(result) -> np.ndarray:
    """PC1 loadings divided by the standard deviation of their own matrix."""

    diagonal = np.diag(result.corrected_covariance.to_numpy(dtype=float))
    return result.loadings.to_numpy(dtype=float)[:, 0] / np.sqrt(diagonal)


def test_correction_recovers_loadings_that_noise_attenuates():
    """Check 1: with Omega right, the corrected solution is closer to the truth."""

    result = fit_error_corrected_factors(_panel(error_sd=0.60))
    truth = _true_signal_correlations()

    corrected = np.abs(_correlation_scale_loadings(result))
    ratios = np.array([result.diagnostics["attenuation_ratio"][f"S{i}"] for i in range(6)])
    uncorrected = corrected * ratios

    assert np.mean(np.abs(corrected - truth)) < np.mean(np.abs(uncorrected - truth))
    assert np.all(ratios < 1.0)


def test_attenuation_ratio_is_exactly_one_without_measurement_error():
    """Check 5, part one: no error means nothing to correct, to floating point."""

    result = fit_error_corrected_factors(_panel(error_sd=0.0))
    ratios = np.array([result.diagnostics["attenuation_ratio"][f"S{i}"] for i in range(6)])
    assert np.allclose(ratios, 1.0, atol=1e-10)
    assert result.diagnostics["measurement_error_share"] == pytest.approx(0.0, abs=1e-12)


def test_zero_error_matches_plain_pca():
    """Check 5, part two: any difference from standard PCA is an implementation bug."""

    panel = _panel(error_sd=0.0)
    result = fit_error_corrected_factors(panel, n_factors=1)

    wide = panel.pivot(index="historical_date", columns="series_id", values="value")
    standardized = wide / wide.std(axis=0, ddof=1)
    values, vectors = np.linalg.eigh(standardized.cov(ddof=1).to_numpy(dtype=float))
    leading = vectors[:, np.argmax(values)] * np.sqrt(values.max())
    if leading.sum() < 0:
        leading = -leading

    assert np.allclose(result.loadings.to_numpy(dtype=float)[:, 0], leading, atol=1e-10)


def test_overstated_omega_is_reported_not_repaired():
    """Check 2: subtracting more than the observed covariance must not be smoothed over."""

    panel = _panel(error_sd=0.30)
    panel["standard_error"] = panel["standard_error"] * 6.0

    with pytest.raises(IndefiniteCovarianceError):
        fit_error_corrected_factors(panel)

    result = fit_error_corrected_factors(panel, allow_indefinite=True)
    assert result.diagnostics["corrected_covariance_is_psd"] is False
    assert result.diagnostics["min_eigenvalue_corrected"] < 0.0
    # The returned matrix still carries the negative eigenvalue: no PSD projection.
    eigenvalues = np.linalg.eigvalsh(result.corrected_covariance.to_numpy(dtype=float))
    assert eigenvalues.min() < 0.0


def test_weekday_effect_shows_up_in_pc1():
    """Check 3: a construct-free panel driven only by the calendar must be flagged."""

    result = fit_error_corrected_factors(
        _panel(error_sd=0.20, weekday_amplitude=1.20, factor_amplitude=0.0)
    )
    assert result.diagnostics["pc1_weekday_f_statistic"] > 50.0
    assert result.diagnostics["pc1_autocorr_lag7"] > 0.50


def test_weekday_diagnostic_stays_quiet_without_a_calendar_effect():
    """Check 8: the reverse control. A test that always fires detects nothing."""

    result = fit_error_corrected_factors(_panel(error_sd=0.20, weekday_amplitude=0.0))
    assert result.diagnostics["pc1_weekday_f_statistic"] < 5.0
    assert abs(result.diagnostics["pc1_autocorr_lag7"]) < 0.20


def test_mostly_zero_series_is_dropped_and_counted():
    """Check 4: a near-constant column would inflate the apparent common variance."""

    result = fit_error_corrected_factors(_panel(error_sd=0.30, add_zero_series=True))
    assert result.diagnostics["n_series_dropped_zero_share"] == 1
    assert result.diagnostics["series_dropped_zero_share"] == ["S_SPARSE"]
    assert "S_SPARSE" not in result.loadings.index
    # The preregistration hash covers what was requested, not what survived.
    assert result.diagnostics["n_series_requested"] == 7
    assert result.diagnostics["n_series_used"] == 6


def test_series_list_hash_covers_the_requested_set():
    """The hash must move when the keyword list moves, or it cannot preregister it."""

    base = fit_error_corrected_factors(_panel(error_sd=0.30))
    with_extra = fit_error_corrected_factors(_panel(error_sd=0.30, add_zero_series=True))
    assert base.diagnostics["series_list_sha256"] != with_extra.diagnostics["series_list_sha256"]


def test_understated_omega_leaves_a_detectable_residual_attenuation():
    """Check 6: under-correction must be distinguishable from full correction.

    Reporting half the true standard error subtracts a quarter of the true variance.
    The attenuation ratio moves toward one, so the diagnostic does respond to how much
    of Omega was actually removed.
    """

    honest = fit_error_corrected_factors(_panel(error_sd=0.60))
    understated = fit_error_corrected_factors(_panel(error_sd=0.60, reported_error_scale=0.50))

    honest_ratios = np.array([honest.diagnostics["attenuation_ratio"][f"S{i}"] for i in range(6)])
    understated_ratios = np.array(
        [understated.diagnostics["attenuation_ratio"][f"S{i}"] for i in range(6)]
    )

    assert np.all(understated_ratios > honest_ratios)
    assert np.mean(understated_ratios - honest_ratios) > 0.02
    assert np.all(understated_ratios < 1.0)


def test_understated_omega_cannot_be_detected_from_the_output_alone():
    """Check 6, the honest half: pin the limit so the ratio is not oversold.

    Every diagnostic is computed from the supplied Omega, so an Omega that is
    uniformly too small produces a self-consistent, entirely plausible-looking result.
    Nothing in the output says "this correction was insufficient" --- that verdict
    needs the true Omega, which is exactly what the researcher does not have. This is
    why omega_is_daily_variance travels with the result.
    """

    understated = fit_error_corrected_factors(_panel(error_sd=0.60, reported_error_scale=0.50))
    matched = fit_error_corrected_factors(_panel(error_sd=0.30))

    # Two panels, one honestly measured and one under-reported, land in the same place
    # on every published diagnostic. No threshold separates them.
    assert understated.diagnostics["corrected_covariance_is_psd"] is True
    assert matched.diagnostics["corrected_covariance_is_psd"] is True
    assert understated.diagnostics["measurement_error_share"] == pytest.approx(
        matched.diagnostics["measurement_error_share"], abs=0.05
    )
    assert understated.diagnostics["omega_is_daily_variance"] is False


def test_cross_series_correlated_error_is_absorbed_as_a_common_factor():
    """Check 7: the diagonal-Omega assumption, and what the diagnostics do about it.

    Measurement error shared across series is indistinguishable from a construct by
    construction --- it is common variation, and a factor model exists to find common
    variation. The result records the outcome so the number is never read as evidence
    that the assumption held.

    Minimum detectable effect: injecting a shared error of sd 0.50 alongside a
    per-series error of sd 0.40 raises the PC1 explained-variance ratio by about 4.5
    percentage points (0.801 to 0.846). The threshold below sits under that, so the
    assertion states what was measured rather than what would be convenient.
    """

    diagonal = fit_error_corrected_factors(_panel(error_sd=0.40))
    correlated = fit_error_corrected_factors(_panel(error_sd=0.40, common_error_sd=0.50))

    # It does damage: the shared error is counted as construct, so PC1 gains.
    assert correlated.explained_variance_ratio[0] > diagonal.explained_variance_ratio[0] + 0.03

    # And no published diagnostic distinguishes the two. measurement_error_share is
    # computed from the supplied diagonal Omega, which never saw the shared component.
    assert correlated.diagnostics["measurement_error_share"] < diagonal.diagnostics[
        "measurement_error_share"
    ] + 0.05
    assert correlated.diagnostics["corrected_covariance_is_psd"] is True
    # The only thing standing between this and a false construct is the flag itself.
    assert correlated.diagnostics["omega_offdiagonal_assumed_zero"] is True


def test_score_standard_errors_scale_with_the_supplied_error():
    """Score uncertainty must propagate, or the whole point of the module is lost."""

    small = fit_error_corrected_factors(_panel(error_sd=0.20), n_factors=1)
    large = fit_error_corrected_factors(_panel(error_sd=0.60), n_factors=1)
    assert large.scores["F1_se"].mean() > small.scores["F1_se"].mean()
    assert (small.scores["F1_se"] > 0).all()


def _two_factor_panel(error_sd: float, n_series: int = 8, seed: int = 11) -> pd.DataFrame:
    """Two orthogonal constructs, each loading on half the series."""

    rng = np.random.default_rng(seed)
    dates = pd.date_range(START, periods=600, freq="D")
    factors = rng.normal(size=(600, 2))
    loadings = np.zeros((n_series, 2))
    loadings[: n_series // 2, 0] = 0.80
    loadings[n_series // 2 :, 1] = 0.80

    rows = []
    for index in range(n_series):
        signal = factors @ loadings[index] + rng.normal(scale=UNIQUE_SD, size=600)
        error = rng.normal(scale=error_sd, size=600) if error_sd > 0 else np.zeros(600)
        values = 50.0 + 10.0 * (signal + error)
        for position, date in enumerate(dates):
            rows.append(
                {
                    "series_id": f"S{index}",
                    "historical_date": date,
                    "value": float(values[position]),
                    "standard_error": 10.0 * error_sd,
                }
            )
    return pd.DataFrame(rows)


def test_factor_count_is_a_property_of_the_data_not_the_noise_level():
    """The retained count must hold as measurement error grows, or the rule is noise.

    Kaiser's threshold of one is calibrated for a correlation matrix, whose average
    eigenvalue is one. Error correction lowers the whole spectrum, so carrying that
    one across would drop factors as the error share rises. Restating the rule on the
    corrected trace keeps the count at the truth from a clean panel up to an error
    share near one half.
    """

    for error_sd in (0.0, 0.30, 0.50, 0.70, 0.90):
        result = fit_error_corrected_factors(_two_factor_panel(error_sd=error_sd))
        assert result.diagnostics["n_factors"] == 2, error_sd
        assert result.diagnostics["eigenvalue_gap_ratio"] > 3.0, error_sd


def test_broken_stick_comparator_agrees_on_a_clean_two_factor_panel():
    """The stricter comparator must not contradict the retained count here.

    Broken-stick is sequential: it stops at the first component failing its expected
    share. Counting every eigenvalue above its own bound instead lets trailing noise
    back in and makes this look *less* strict than Kaiser, which is backwards. Pinned
    because that misreading produced a plausible-looking three on this panel.
    """

    for error_sd in (0.0, 0.50, 0.90):
        result = fit_error_corrected_factors(_two_factor_panel(error_sd=error_sd))
        assert result.diagnostics["n_factors_broken_stick"] == 2, error_sd


def test_error_dominated_panel_refuses_to_return_a_factor():
    """At some error level the series set stops supporting a factor. Say so, loudly."""

    with pytest.raises(IndefiniteCovarianceError, match="does not support a factor"):
        fit_error_corrected_factors(_two_factor_panel(error_sd=1.20))


def _write_manifest(directory, panel: pd.DataFrame, error_multiplier: float = 1.0):
    """Split a long panel into the per-series CSVs and manifest the CLI consumes."""

    rows = []
    for series_id, group in panel.groupby("series_id"):
        path = directory / f"{series_id}.csv"
        frame = group[["historical_date", "value", "standard_error"]].copy()
        frame["standard_error"] = frame["standard_error"] * error_multiplier
        frame.to_csv(path, index=False)
        rows.append({"series_id": series_id, "path": path.name})
    manifest = directory / "manifest.csv"
    pd.DataFrame(rows).to_csv(manifest, index=False)
    return manifest


def test_cli_exit_code_distinguishes_indefinite_from_success(tmp_path):
    """A never-failing exit code is a silent failure in any script that trusts it.

    Verified by running the same command on an input that must succeed and one that
    must not, rather than by reading the code path.
    """

    from typer.testing import CliRunner

    from racergt.cli import app

    runner = CliRunner()
    panel = _panel(error_sd=0.30)

    good_dir = tmp_path / "good"
    good_dir.mkdir()
    good = runner.invoke(
        app, ["factor", str(_write_manifest(good_dir, panel)), "--out", str(tmp_path / "res_good")]
    )
    assert good.exit_code == 0

    bad_dir = tmp_path / "bad"
    bad_dir.mkdir()
    bad_manifest = _write_manifest(bad_dir, panel, error_multiplier=8.0)
    bad = runner.invoke(app, ["factor", str(bad_manifest), "--out", str(tmp_path / "res_bad")])
    assert bad.exit_code == 4

    allowed = runner.invoke(
        app,
        [
            "factor",
            str(bad_manifest),
            "--out",
            str(tmp_path / "res_allowed"),
            "--allow-indefinite",
        ],
    )
    assert allowed.exit_code == 0


def test_result_saves_every_artefact(tmp_path):
    result = fit_error_corrected_factors(_panel(error_sd=0.30))
    paths = result.save(tmp_path)
    assert set(paths) == {
        "loadings",
        "scores",
        "eigenvalues",
        "corrected_covariance",
        "diagnostics",
    }
    for path in paths.values():
        assert path.exists() and path.stat().st_size > 0
