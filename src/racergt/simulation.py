from __future__ import annotations

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
    for period, group in groups:
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

    pull_latent: dict[str, np.ndarray] = {}
    for row in schedule.itertuples(index=False):
        idiosyncratic = _ar1_noise(len(dates), 0.70, settings.retrieval_noise_sd, rng)
        log_error = (
            day_effect[row.collection_day]
            + stream_effect[row.stream_id]
            + settings.shared_day_noise_weight * shared_day_noise[row.collection_day]
            + (1.0 - settings.shared_day_noise_weight) * idiosyncratic
        )
        pull_latent[row.pull_id] = latent * np.exp(log_error)

    # Copy a fraction of entire latent realizations to emulate exact cache/version duplicates.
    n_pulls = len(schedule)
    n_duplicate = int(np.floor(settings.exact_duplicate_fraction * n_pulls))
    duplicate_targets = schedule["pull_id"].tolist()[-n_duplicate:] if n_duplicate else []
    source_candidates = schedule["pull_id"].tolist()[: max(n_pulls - n_duplicate, 1)]
    duplicate_source: dict[str, str] = {}
    for target in duplicate_targets:
        source = str(rng.choice(source_candidates))
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
                if pull_row.pull_id not in duplicate_source:
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
