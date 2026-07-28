from __future__ import annotations

import warnings
from dataclasses import dataclass

import numpy as np
import pandas as pd

from .config import RacerGTConfig
from .design import generate_chunk_windows, generate_collection_schedule


@dataclass
class SimulationResult:
    raw_chunks: pd.DataFrame
    benchmark: pd.DataFrame
    truth: pd.DataFrame
    schedule: pd.DataFrame


@dataclass
class SimulationSettings:
    random_seed: int = 20260727
    latent_ar: float = 0.92
    latent_noise_sd: float = 1.8
    retrieval_noise_sd: float = 0.06
    chunk_noise_sd: float = 0.03
    day_effect_sd: float = 0.025
    stream_effect_sd: float = 0.020
    exact_duplicate_fraction: float = 0.10
    shared_day_noise_weight: float = 0.50
    benchmark_noise_sd: float = 1.2
    integer_rounding: bool = True
    # Dependence heterogeneity. With the settings above every pull carries the same
    # error structure, so the residual covariance is block-equicorrelated and its
    # minimum-variance weights are equal weights: GLS has nothing to exploit. These
    # two options place a subset of pulls behind one shared cache disturbance that
    # cuts across collection days and streams, so the dependence is neither uniform
    # nor recoverable from the design facets -- only from the residual covariance.
    # cache_cluster_fraction = 0 reproduces the homogeneous behaviour exactly.
    cache_cluster_fraction: float = 0.0
    cache_cluster_weight: float = 0.0
    # Variance heterogeneity. cache_cluster_* above makes pulls differ in how they
    # covary; this makes them differ in how noisy they are, which is the other thing
    # minimum-variance weights exist to exploit and the one the default design leaves
    # out. The value is the ratio of the largest to the smallest retrieval-noise
    # standard deviation, spread geometrically with geometric mean one, so the
    # overall noise level is redistributed rather than raised. Assignment is shuffled
    # across the schedule for the same reason cache membership is: aligned with a
    # collection day or a stream it would be a facet effect the G-study already
    # reports, not something only the residual covariance can see.
    # retrieval_noise_ladder = 1.0 reproduces the homogeneous behaviour exactly, and
    # consumes no random numbers, so existing results are bit-comparable.
    retrieval_noise_ladder: float = 1.0
    # Robustness control for the ladder. Trends normalizes each window to its own
    # maximum, so retrieval error is proportional by construction and the default
    # model is multiplicative. That is an argument, not a measurement, and the
    # argument happens to favour the estimator whose weights the ladder exists to
    # test. Setting this puts the same disturbance on the level scale instead:
    # latent * exp(x) ~= latent + latent * x, so scaling by the mean level keeps the
    # magnitude comparable while removing the dependence of error size on level.
    # False consumes no random numbers and reproduces the default exactly.
    additive_retrieval_noise: bool = False


def _ar1_noise(n: int, phi: float, sd: float, rng: np.random.Generator) -> np.ndarray:
    innovations = rng.normal(0.0, sd, size=n)
    x = np.zeros(n)
    for t in range(1, n):
        x[t] = phi * x[t - 1] + innovations[t]
    return x


def _latent_signal(dates: pd.DatetimeIndex, settings: SimulationSettings, rng: np.random.Generator) -> np.ndarray:
    n = len(dates)
    t = np.arange(n)
    signal = (
        30.0
        + 0.004 * t
        + 2.5 * np.sin(2 * np.pi * t / 7.0)
        + 4.0 * np.sin(2 * np.pi * t / 365.25)
        + _ar1_noise(n, settings.latent_ar, settings.latent_noise_sd, rng)
    )
    # Deterministic event-like attention spikes with asymmetric decay.
    centers = np.linspace(max(30, n * 0.15), max(31, n * 0.85), 6).astype(int)
    for idx, center in enumerate(centers):
        amplitude = 15 + 5 * (idx % 3)
        width = 2 + idx % 4
        signal += amplitude * np.exp(-np.maximum(t - center, 0) / (width * 2.0)) * (t >= center)
        signal += amplitude * np.exp(-((t - center) / width) ** 2)
    signal = np.maximum(signal, 0.2)
    return signal


def _period_benchmark(
    dates: pd.DatetimeIndex,
    truth: np.ndarray,
    freq: str,
    noise_sd: float,
    rng: np.random.Generator,
) -> pd.DataFrame:
    series = pd.Series(truth, index=dates)
    if freq == "weekly":
        groups = series.groupby(series.index.to_period("W-SUN"))
    elif freq == "monthly":
        groups = series.groupby(series.index.to_period("M"))
    else:
        raise ValueError(freq)
    rows = []
    for _period, group in groups:
        start = max(group.index.min(), dates.min())
        end = min(group.index.max(), dates.max())
        value = float(group.mean() + rng.normal(0.0, noise_sd))
        rows.append(
            {
                "frequency": freq,
                "period_start": start,
                "period_end": end,
                "value": value,
                "se": noise_sd,
            }
        )
    return pd.DataFrame(rows)


def simulate_racergt_data(
    config: RacerGTConfig,
    settings: SimulationSettings | None = None,
) -> SimulationResult:
    settings = settings or SimulationSettings()
    rng = np.random.default_rng(settings.random_seed)
    dates = pd.date_range(config.query.historical_start, config.query.historical_end, freq="D")
    latent = _latent_signal(dates, settings, rng)
    baseline_mask = (dates >= pd.Timestamp(config.query.baseline_start)) & (
        dates <= pd.Timestamp(config.query.baseline_end)
    )
    truth_index = latent / latent[baseline_mask].mean() * 100.0
    truth = pd.DataFrame(
        {
            "historical_date": dates,
            "latent_search_intensity": latent,
            "true_index": truth_index,
        }
    )

    schedule = generate_collection_schedule(config, anchor_date="2026-07-27")
    chunks = generate_chunk_windows(
        config.query.historical_start,
        config.query.historical_end,
        config.chunking.window_days,
        config.chunking.step_days,
    )
    day_levels = sorted(schedule["collection_day"].unique())
    stream_levels = sorted(schedule["stream_id"].unique())
    day_effect = {d: rng.normal(0.0, settings.day_effect_sd) for d in day_levels}
    stream_effect = {s: rng.normal(0.0, settings.stream_effect_sd) for s in stream_levels}
    shared_day_noise = {
        d: _ar1_noise(len(dates), 0.85, settings.retrieval_noise_sd, rng) for d in day_levels
    }

    # Pulls served from a common cache share one disturbance. Membership is drawn at
    # random across the design rather than following a day or a stream, so the extra
    # dependence cannot be absorbed by the design facets and has to be found in the
    # residual covariance -- which is the situation the GLS weights exist for.
    cache_members: set[str] = set()
    cache_noise = np.zeros(len(dates))
    if settings.cache_cluster_fraction > 0 and settings.cache_cluster_weight > 0:
        all_ids = schedule["pull_id"].tolist()
        n_cache = round(settings.cache_cluster_fraction * len(all_ids))
        if n_cache >= 2:
            cache_members = set(rng.choice(all_ids, size=n_cache, replace=False).tolist())
            cache_noise = _ar1_noise(len(dates), 0.85, settings.retrieval_noise_sd, rng)

    # Per-pull noise scale. Exponents are symmetric about zero so their product is
    # one, leaving the geometric mean of the scales at one: the noise budget moves
    # between pulls instead of growing. Nothing is drawn when the ladder is 1.0, so
    # the default consumes the random stream identically to before this option.
    noise_scale: dict[str, float] = {}
    if settings.retrieval_noise_ladder != 1.0:
        exponents = np.linspace(-0.5, 0.5, len(schedule))
        rng.shuffle(exponents)
        noise_scale = {
            pull_id: float(settings.retrieval_noise_ladder**exponent)
            for pull_id, exponent in zip(schedule["pull_id"], exponents, strict=True)
        }

    pull_latent: dict[str, np.ndarray] = {}
    n_clipped = 0
    for row in schedule.itertuples(index=False):
        idiosyncratic = _ar1_noise(len(dates), 0.70, settings.retrieval_noise_sd, rng)
        retrieval = (
            settings.shared_day_noise_weight * shared_day_noise[row.collection_day]
            + (1.0 - settings.shared_day_noise_weight) * idiosyncratic
        )
        retrieval = retrieval * noise_scale.get(row.pull_id, 1.0)
        if row.pull_id in cache_members:
            w = settings.cache_cluster_weight
            retrieval = w * cache_noise + (1.0 - w) * retrieval
        log_error = day_effect[row.collection_day] + stream_effect[row.stream_id] + retrieval
        if settings.additive_retrieval_noise:
            level = latent + float(np.mean(latent)) * log_error
            # A level-scale disturbance can cross zero where the multiplicative one
            # cannot. Clipping is counted and warned about rather than silent: a
            # scenario that clips is no longer the additive control it claims to be,
            # because the clip is itself a nonlinearity in the level.
            n_clipped += int((level < 0.0).sum())
            pull_latent[row.pull_id] = np.maximum(level, 0.0)
        else:
            pull_latent[row.pull_id] = latent * np.exp(log_error)

    if n_clipped:
        warnings.warn(
            f"additive_retrieval_noise clipped {n_clipped} negative levels at "
            f"retrieval_noise_ladder={settings.retrieval_noise_ladder}. The clip is a "
            "nonlinearity in the level, so this run is no longer a purely additive "
            "control and should not be compared with the multiplicative case as "
            "though the only difference were the error scale.",
            RuntimeWarning,
            stacklevel=2,
        )

    # Copy a fraction of entire latent realizations to emulate exact cache/version
    # duplicates. Targets are drawn at random rather than taken from the tail of the
    # schedule: putting every duplicate in the last collection day would confound
    # duplication with the design cell, which is exactly the confound the duplicate
    # diagnostics are meant to detect. A duplicate's source must have been retrieved
    # earlier, otherwise the cached response does not exist yet and the copy would be
    # regenerated with fresh chunk noise instead of being byte-identical.
    all_pulls = schedule["pull_id"].tolist()
    n_pulls = len(all_pulls)
    n_duplicate = int(np.floor(settings.exact_duplicate_fraction * n_pulls))
    positions = {pull_id: index for index, pull_id in enumerate(all_pulls)}
    eligible_targets = all_pulls[1:]
    n_duplicate = min(n_duplicate, len(eligible_targets))
    duplicate_targets = (
        sorted(
            rng.choice(eligible_targets, size=n_duplicate, replace=False).tolist(),
            key=positions.get,
        )
        if n_duplicate
        else []
    )
    target_set = set(duplicate_targets)
    duplicate_source: dict[str, str] = {}
    for target in duplicate_targets:
        earlier = [
            pull_id
            for pull_id in all_pulls
            if positions[pull_id] < positions[target] and pull_id not in target_set
        ]
        if not earlier:
            continue
        source = str(rng.choice(earlier))
        duplicate_source[target] = source
        pull_latent[target] = pull_latent[source].copy()

    raw_rows: list[dict] = []
    raw_cache: dict[tuple[str, str], np.ndarray] = {}
    for pull_row in schedule.itertuples(index=False):
        pseries = pd.Series(pull_latent[pull_row.pull_id], index=dates)
        for chunk_row in chunks.itertuples(index=False):
            mask = (dates >= chunk_row.window_start) & (dates <= chunk_row.window_end)
            chunk_dates = dates[mask]
            cache_key = (duplicate_source.get(pull_row.pull_id, ""), chunk_row.chunk_id)
            if pull_row.pull_id in duplicate_source and cache_key in raw_cache:
                observed = raw_cache[cache_key].copy()
            else:
                q = pseries.loc[chunk_dates].to_numpy(dtype=float)
                q = q * np.exp(rng.normal(0.0, settings.chunk_noise_sd, size=len(q)))
                observed = 100.0 * q / np.max(q)
                if settings.integer_rounding:
                    observed = np.rint(observed)
                observed = np.clip(observed, 0.0, 100.0)
                raw_cache[(pull_row.pull_id, chunk_row.chunk_id)] = observed.copy()
            for date_value, value in zip(chunk_dates, observed, strict=True):
                raw_rows.append(
                    {
                        "series_id": config.query.series_id,
                        "pull_id": pull_row.pull_id,
                        "chunk_id": chunk_row.chunk_id,
                        "historical_date": date_value,
                        "value": float(value),
                        "collection_day": int(pull_row.collection_day),
                        "stream_id": str(pull_row.stream_id),
                        "replicate_id": str(pull_row.replicate_id),
                        "window_start": chunk_row.window_start,
                        "window_end": chunk_row.window_end,
                        "retrieved_at": pull_row.planned_start_time,
                        "keyword": config.query.keyword,
                        "geo": config.query.geo,
                        "category": config.query.category,
                        "search_property": config.query.search_property,
                        "language": config.query.language,
                        "protocol_hash": config.protocol_hash(),
                        "is_partial": False,
                        "simulated_duplicate_source": duplicate_source.get(pull_row.pull_id),
                    }
                )
    raw = pd.DataFrame(raw_rows)

    weekly = _period_benchmark(
        dates, truth_index, "weekly", settings.benchmark_noise_sd, rng
    )
    monthly = _period_benchmark(
        dates, truth_index, "monthly", settings.benchmark_noise_sd * 0.7, rng
    )
    benchmark = pd.concat([weekly, monthly], ignore_index=True)
    benchmark.insert(0, "series_id", config.query.series_id)
    return SimulationResult(raw_chunks=raw, benchmark=benchmark, truth=truth, schedule=schedule)
