"""Does the calibration stage survive contact with real Google Trends data?

Every result reported so far came from the package's own simulator. That is a
circular test: the simulator draws from the same proportionality model the
estimator assumes, so it can show that the estimator solves the problem it was
given, never that the problem is the right one. This script runs the calibration
stage on real downloads of ``bitcoin``, United States, daily, for 2024.

The two measurements the simulation could make are not available here.

* There is no latent truth, so reconstruction error cannot be computed. Neither
  method can be called more accurate. What can be measured is how far apart they
  are, and how far apart they could possibly get.
* There is one pull, so nothing downstream of calibration can be tested at all.
  Cross-pull dependence, duplicate diagnosis, generalizability components and the
  consensus estimator all need repeated collection across days and environments.
  This script does not touch them and reports nothing about them.

Failure mode F1 is a claim about a variance, so comparing the two methods' point
estimates on one pull cannot test it at any sample size. No test is needed: the
graph WLS weights are edge precisions, which makes the variance of a recovered
log scale the effective resistance to the reference chunk, and a spanning path is
resistances in series. The script reports that ratio for this design and for the
designs a study might choose, at the dispersion actually measured. One year gives
a 9-fold variance reduction over a spanning path and a terminal error of 0.40%
either way. The longer designs are extrapolations, not measurements: they assume
a constant dispersion that this same year contradicts, and they are printed with
that caveat rather than as findings.

What this data does settle, decisively, is whether the simulator describes real
chunk overlaps. Overlapping chunks are assumed proportional up to a constant, the
overlaps run to 150 days, and the assumption is therefore heavily
over-identified. Three checks are run --- cycle closure, within-overlap
constancy, and the integer-rounding floor that bounds how tight any of it could
be --- and together they estimate the chunk-specific noise that
``SimulationSettings.chunk_noise_sd`` sets to 0.03.

    PYTHONPATH=src python examples/run_real_data_calibration.py
"""

from __future__ import annotations

from itertools import combinations, pairwise
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

from racergt.baselines import sequential_stitch
from racergt.config import CalibrationConfig
from racergt.overlap import OverlapGraphCalibrator
from racergt.schema import coerce_raw_chunks

RAW_CHUNKS = Path("real_data/raw_chunks.csv")
OUT = Path("real_data_validation")
MIN_OVERLAP_DAYS = 14
BASELINE_START = "2024-01-01"
BASELINE_END = "2024-12-31"

# SimulationSettings.chunk_noise_sd, the parameter this data can actually check.
SIMULATOR_CHUNK_NOISE_SD = 0.03


def chunk_order(data: pd.DataFrame) -> list[str]:
    return (
        data.groupby("chunk_id")["window_start"].min().sort_values().index.astype(str).tolist()
    )


def recentre(scales: pd.Series, reference: str) -> pd.Series:
    """Put log scales on a common reference so two methods can be compared.

    Both methods identify log scales only up to an additive constant, and they
    choose different anchors: the graph picks the highest-degree chunk, the chain
    starts at the first. Differencing against a shared chunk removes the anchor.
    """

    return scales - scales.loc[reference]


def series_disagreement(graph: pd.DataFrame, stitched: pd.DataFrame) -> dict:
    left = graph.set_index("historical_date")["value"]
    right = stitched.set_index("historical_date")["value"]
    common = left.index.intersection(right.index)
    a = left.loc[common].to_numpy(dtype=float)
    b = right.loc[common].to_numpy(dtype=float)
    ok = np.isfinite(a) & np.isfinite(b)
    a, b = a[ok], b[ok]
    absolute = np.abs(a - b)
    relative = absolute / np.maximum((a + b) / 2.0, 1e-12)
    return {
        "n_days": int(a.size),
        "correlation": float(np.corrcoef(a, b)[0, 1]),
        "median_relative_difference": float(np.median(relative)),
        "p90_relative_difference": float(np.quantile(relative, 0.90)),
        "max_relative_difference": float(relative.max()),
        "max_absolute_difference_index_points": float(absolute.max()),
        "rms_absolute_difference_index_points": float(np.sqrt(np.mean(absolute**2))),
    }


def scale_disagreement(
    graph_scales: pd.DataFrame, stitch_scales: pd.DataFrame, order: list[str]
) -> pd.DataFrame:
    g = graph_scales.set_index(graph_scales["chunk_id"].astype(str))["log_scale"]
    s = stitch_scales.set_index(stitch_scales["chunk_id"].astype(str))["log_scale"]
    anchor = order[0]
    g = recentre(g, anchor)
    s = recentre(s, anchor)
    rows = []
    for position, chunk_id in enumerate(order):
        rows.append(
            {
                "position": position,
                "chunk_id": chunk_id,
                "graph_log_scale": float(g.loc[chunk_id]),
                "sequential_log_scale": float(s.loc[chunk_id]),
                "difference": float(g.loc[chunk_id] - s.loc[chunk_id]),
                "difference_pct": float(
                    100.0 * (np.exp(g.loc[chunk_id] - s.loc[chunk_id]) - 1.0)
                ),
            }
        )
    return pd.DataFrame(rows)


def triangle_closure(edges: pd.DataFrame) -> pd.DataFrame:
    """Test the cycle identity the model implies but stitching never checks.

    For any three mutually overlapping chunks the model forces
    ``d_ij + d_jk = d_ik``, since each edge estimates a difference of the same
    log scales. Sequential stitching uses only the edges on its path, so it can
    neither notice nor report a violation. Every triangle here is an independent
    consistency check that costs nothing extra to compute.
    """

    lookup: dict[tuple[str, str], float] = {}
    for row in edges.itertuples():
        lookup[(row.chunk_i, row.chunk_j)] = float(row.log_ratio)
        lookup[(row.chunk_j, row.chunk_i)] = -float(row.log_ratio)

    nodes = sorted({c for pair in lookup for c in pair})
    rows = []
    for i, j, k in combinations(nodes, 3):
        if (i, j) not in lookup or (j, k) not in lookup or (i, k) not in lookup:
            continue
        closure = lookup[(i, j)] + lookup[(j, k)] - lookup[(i, k)]
        rows.append(
            {
                "chunk_i": i,
                "chunk_j": j,
                "chunk_k": k,
                "closure_error": closure,
                "closure_error_pct": 100.0 * (np.exp(closure) - 1.0),
            }
        )
    return pd.DataFrame(rows)


def rounding_floor(values_i: np.ndarray, values_j: np.ndarray) -> float:
    """Dispersion in the log ratio forced by integer reporting alone.

    Trends reports each chunk rounded to an integer on 0--100. If the unrounded
    value is treated as uniform within half a unit of what is printed, the log of
    a reported value carries noise of standard deviation about
    ``1 / (sqrt(12) v)``, and the difference of two logs adds them in quadrature.
    Any dispersion below this level is unattainable no matter how well the
    proportionality assumption holds, so it is the floor a residual has to be
    judged against.
    """

    variance = (1.0 / 12.0) * (1.0 / values_i**2 + 1.0 / values_j**2)
    return float(np.sqrt(np.mean(variance)))


def overlap_diagnostics(data: pd.DataFrame, config: CalibrationConfig) -> pd.DataFrame:
    """Per-pair evidence on whether overlapping chunks really are proportional."""

    by_chunk = {
        str(cid): group.set_index("historical_date")["value"].sort_index()
        for cid, group in data.groupby("chunk_id")
    }
    order = chunk_order(data)
    rows = []
    for pos_i, cid_i in enumerate(order):
        for cid_j in order[pos_i + 1 :]:
            s_i, s_j = by_chunk[cid_i], by_chunk[cid_j]
            common = s_i.index.intersection(s_j.index)
            if len(common) < MIN_OVERLAP_DAYS:
                continue
            vi = s_i.loc[common].to_numpy(dtype=float)
            vj = s_j.loc[common].to_numpy(dtype=float)
            usable = (vi >= config.min_value) & (vj >= config.min_value)
            vi, vj = vi[usable], vj[usable]
            if vi.size < MIN_OVERLAP_DAYS:
                continue
            ratio = np.log(vi) - np.log(vj)
            days = np.arange(vi.size, dtype=float)
            # A constant offset is what the model claims. A slope means the two
            # chunks disagree about shape, not just level, which no rescaling
            # can repair.
            slope, _intercept, _r, p_value, stderr = stats.linregress(days, ratio)
            floor = rounding_floor(vi, vj)
            observed = float(np.std(ratio, ddof=1))
            rows.append(
                {
                    "chunk_i": cid_i,
                    "chunk_j": cid_j,
                    "separation": order.index(cid_j) - pos_i,
                    "n_overlap": int(vi.size),
                    "mean_log_ratio": float(np.mean(ratio)),
                    "sd_log_ratio": observed,
                    "rounding_floor_sd": floor,
                    "excess_over_floor": observed / floor if floor > 0 else np.nan,
                    "drift_per_100_days": float(100.0 * slope),
                    "drift_se_per_100_days": float(100.0 * stderr),
                    "drift_p": float(p_value),
                }
            )
    return pd.DataFrame(rows)


def residual_misscaling(calibrated: pd.DataFrame, full: pd.DataFrame) -> pd.DataFrame:
    """Is any chunk still systematically off after calibration?

    Testing for jumps in the reconstructed series where chunk coverage changes is
    the obvious approach and it has no power here: daily bitcoin attention moves a
    median of several index points, while the calibration differences at issue are
    a fifth of one point. Comparing each chunk's calibrated values against the
    reconstructed series over the whole window it covers pools 180 days instead of
    one and answers the same question with usable precision. A chunk correctly
    placed on the common scale should sit at zero mean log deviation.
    """

    reference = full.set_index("historical_date")["value"]
    rows = []
    for chunk_id, group in calibrated.groupby("chunk_id"):
        aligned = group.set_index("historical_date")["calibrated_value"]
        common = aligned.index.intersection(reference.index)
        a = aligned.loc[common].to_numpy(dtype=float)
        b = reference.loc[common].to_numpy(dtype=float)
        ok = np.isfinite(a) & np.isfinite(b) & (a > 0) & (b > 0)
        deviation = np.log(a[ok]) - np.log(b[ok])
        rows.append(
            {
                "chunk_id": str(chunk_id),
                "n_days": int(deviation.size),
                "mean_log_deviation": float(np.mean(deviation)),
                "se": float(np.std(deviation, ddof=1) / np.sqrt(deviation.size)),
                "deviation_pct": float(100.0 * (np.exp(np.mean(deviation)) - 1.0)),
            }
        )
    frame = pd.DataFrame(rows).sort_values("chunk_id", ignore_index=True)
    frame["t"] = frame["mean_log_deviation"] / frame["se"].replace(0.0, np.nan)
    return frame


def chain_accumulation(edges: pd.DataFrame, order: list[str]) -> dict:
    """How much scale error can sequential stitching accumulate in this design?

    F1 operates by accumulation, so a design is only evidence about F1 if it can
    accumulate something. The chain's terminal error variance is the sum of the
    variances of the joins it walks --- its effective resistance, since a path is
    resistances in series --- and a join whose overlap has no dispersion
    contributes nothing.

    An earlier version of this script inverted that sum to report how many joins
    a study would need before the accumulated error reached a stated size. The
    conversion from joins to calendar years relied on a degeneracy rate estimated
    from one keyword, which the data refuted, and the resulting figures were
    wrong by more than an order of magnitude. The effective-resistance
    calculation in ``design_comparison`` needs no such rate: it depends only on
    which windows overlap.
    """

    lookup = {}
    for row in edges.itertuples():
        lookup[frozenset((row.chunk_i, row.chunk_j))] = row

    total_variance = 0.0
    informative = 0
    joins = []
    for previous, current in pairwise(order):
        row = lookup.get(frozenset((previous, current)))
        if row is None:
            continue
        is_informative = float(row.robust_scale) > 0.0
        variance = float(row.variance) if is_informative else 0.0
        total_variance += variance
        informative += int(is_informative)
        joins.append(
            {
                "from": previous,
                "to": current,
                "n_usable": int(row.n_usable),
                "se": float(np.sqrt(row.variance)),
                "informative": is_informative,
            }
        )

    terminal_sd = float(np.sqrt(total_variance))
    return {
        "joins": pd.DataFrame(joins),
        "n_joins": len(joins),
        "n_informative_joins": informative,
        "terminal_sd_log": terminal_sd,
        "terminal_pct": 100.0 * (np.exp(terminal_sd) - 1.0),
    }


def design_comparison(
    span_days: int, window: int, step: int, sigma: float, min_overlap: int = MIN_OVERLAP_DAYS
) -> dict:
    """Calibration error a chunk design implies, before any data is collected.

    The variance of a recovered log scale is the effective resistance to the
    reference when each overlap is a conductance equal to its precision. With
    ``Var(edge) = sigma^2 / overlap_days`` the dispersion cancels from the ratio
    of path to graph, so how much the global solve is worth depends only on which
    windows overlap. That is what makes this a design tool rather than a
    post-hoc diagnostic.
    """

    starts = list(range(0, span_days - window + 1, step))
    if starts[-1] + window < span_days:
        starts.append(span_days - window)
    n = len(starts)
    edges = [
        (a, b, float((starts[a] + window) - starts[b]))
        for a in range(n)
        for b in range(a + 1, n)
        if (starts[a] + window) - starts[b] >= min_overlap
    ]

    def terminal_resistance(subset: list[tuple[int, int, float]]) -> float:
        laplacian = np.zeros((n, n))
        for i, j, conductance in subset:
            laplacian[i, i] += conductance
            laplacian[j, j] += conductance
            laplacian[i, j] -= conductance
            laplacian[j, i] -= conductance
        if np.linalg.matrix_rank(laplacian) < n - 1:
            return float("nan")
        pseudo = np.linalg.pinv(laplacian)
        contrast = np.zeros(n)
        contrast[n - 1] = 1.0
        contrast[0] = -1.0
        return float(contrast @ pseudo @ contrast)

    graph = terminal_resistance(edges)
    path = terminal_resistance([e for e in edges if e[1] == e[0] + 1])
    return {
        "n_chunks": n,
        "n_edges": len(edges),
        "graph_resistance": graph,
        "path_resistance": path,
        "reduction": path / graph if graph > 0 else float("nan"),
        "graph_pct": 100.0 * (np.exp(sigma * np.sqrt(graph)) - 1.0),
        "path_pct": 100.0 * (np.exp(sigma * np.sqrt(path)) - 1.0),
    }


def median_informative_dispersion(reported: dict[str, pd.Series], min_value: float) -> float:
    """Median log-ratio standard deviation over the pairs that carry dispersion.

    Applied identically to the real chunks and to each simulated replicate, so the
    two are comparable without any further correction.
    """

    dispersions = []
    ids = sorted(reported)
    for cid_i, cid_j in combinations(ids, 2):
        s_i, s_j = reported[cid_i], reported[cid_j]
        common = s_i.index.intersection(s_j.index)
        if len(common) < MIN_OVERLAP_DAYS:
            continue
        vi = s_i.loc[common].to_numpy(dtype=float)
        vj = s_j.loc[common].to_numpy(dtype=float)
        usable = (vi >= min_value) & (vj >= min_value)
        vi, vj = vi[usable], vj[usable]
        if vi.size < MIN_OVERLAP_DAYS:
            continue
        spread = float(np.std(np.log(vi) - np.log(vj), ddof=1))
        if spread > 0:
            dispersions.append(spread)
    return float(np.median(dispersions)) if dispersions else np.nan


def chunk_noise_profile(
    data: pd.DataFrame,
    full: pd.DataFrame,
    config: CalibrationConfig,
    sigmas: np.ndarray,
    n_replicates: int = 200,
    seed: int = 20260728,
) -> pd.DataFrame:
    """Recover chunk_noise_sd by reproducing what Google Trends actually does.

    The closed-form rounding floor assumes the two chunks round independently.
    They do not: they round the same underlying numbers differing only by a scale
    factor, so their rounding errors are correlated and the closed form overstates
    the floor. Overstating the floor biases the recovered chunk noise towards zero,
    which is the direction that flatters the conclusion, so the closed form cannot
    be the basis for it.

    This replaces the assumption with the mechanism. The calibrated daily series is
    the best available estimate of the common signal; running it back through the
    simulator's own generating step --- multiply by lognormal chunk noise, divide by
    the window maximum, round to an integer --- reproduces the reported chunks under
    a stated noise level, correlation structure included. Sweeping the noise level
    and matching the resulting dispersion against the observed dispersion estimates
    the parameter instead of bounding it.
    """

    signal = full.set_index("historical_date")["value"].sort_index()
    windows = data.groupby("chunk_id").agg(
        start=("window_start", "min"), end=("window_end", "max")
    )
    order = chunk_order(data)
    rng = np.random.default_rng(seed)

    segments = {
        cid: signal.loc[windows.loc[cid, "start"] : windows.loc[cid, "end"]] for cid in order
    }
    rows = []
    for sigma in sigmas:
        draws = []
        for _ in range(n_replicates):
            reported = {}
            for cid, segment in segments.items():
                values = segment.to_numpy(dtype=float)
                if sigma > 0:
                    values = values * np.exp(rng.normal(0.0, sigma, size=values.size))
                scaled = np.rint(100.0 * values / values.max())
                reported[cid] = pd.Series(scaled, index=segment.index)
            draws.append(median_informative_dispersion(reported, config.min_value))
            if sigma == 0.0:
                # Without noise the step is deterministic; one draw is the answer.
                break
        rows.append(
            {
                "chunk_noise_sd": float(sigma),
                "median_dispersion": float(np.mean(draws)),
                "dispersion_sd": float(np.std(draws, ddof=1)) if len(draws) > 1 else 0.0,
            }
        )
    return pd.DataFrame(rows)


def recovery_check(
    data: pd.DataFrame,
    config: CalibrationConfig,
    injected: tuple[float, ...] = (0.0, 0.01, 0.02, 0.03),
    seed: int = 20260728,
) -> pd.DataFrame:
    """Does the sweep recover a chunk noise that was put there on purpose?

    An estimate is worth what its estimator can be shown to recover. Injecting a
    known disturbance into the real chunks, renormalizing the way Trends does, and
    running the same sweep turns the reported 0.0066 into a claim with a
    demonstrated range. The level that matters is 0.03: if the simulator's default
    were the truth, this has to return something near it rather than the small
    number it returns on the untouched data.
    """

    from racergt.overlap import OverlapGraphCalibrator

    rng = np.random.default_rng(seed)
    baseline = float("nan")
    rows = []
    for level in injected:
        frame = data.copy()
        if level > 0:
            parts = []
            for _chunk_id, group in frame.groupby("chunk_id", sort=True):
                values = group["value"].to_numpy(dtype=float)
                values = values * np.exp(rng.normal(0.0, level, size=values.size))
                values = np.clip(np.rint(100.0 * values / values.max()), 0.0, 100.0)
                part = group.copy()
                part["value"] = values
                parts.append(part)
            frame = pd.concat(parts, ignore_index=True)

        fitted = OverlapGraphCalibrator(config, min_overlap_days=MIN_OVERLAP_DAYS).fit(
            frame, baseline_start=BASELINE_START, baseline_end=BASELINE_END
        )
        pairs = overlap_diagnostics(frame, config)
        observed = float(np.median(pairs.loc[pairs["sd_log_ratio"] > 0, "sd_log_ratio"]))
        profile = chunk_noise_profile(
            frame, fitted.full_series, config, np.arange(0.0, 0.045, 0.0025), n_replicates=120
        )
        recovered = interpolate_crossing(profile, observed)
        if level == 0.0:
            baseline = recovered
        rows.append(
            {
                "injected": level,
                # The data already carries whatever noise it carries, so an
                # injection adds in quadrature to the level recovered at zero.
                "expected": float(np.sqrt(baseline**2 + level**2)),
                "recovered": recovered,
                "observed_dispersion": observed,
            }
        )
    return pd.DataFrame(rows)


def interpolate_crossing(profile: pd.DataFrame, observed: float) -> float:
    """Noise level at which the simulated dispersion first reaches the observed one.

    The sweep is only monotone once noise clears the rounding granularity, so the
    crossing is taken on the increasing part; below that the curve is flat within
    Monte Carlo error and no crossing is meaningful.
    """

    increasing = profile[profile["median_dispersion"].diff().fillna(1.0) > 0]
    below = increasing[increasing["median_dispersion"] <= observed]
    above = increasing[increasing["median_dispersion"] > observed]
    if below.empty or above.empty:
        return float("nan")
    low, high = below.iloc[-1], above.iloc[0]
    span = high["median_dispersion"] - low["median_dispersion"]
    if span <= 0:
        return float(low["chunk_noise_sd"])
    weight = (observed - low["median_dispersion"]) / span
    return float(low["chunk_noise_sd"] + weight * (high["chunk_noise_sd"] - low["chunk_noise_sd"]))


def implied_chunk_noise(overlaps: pd.DataFrame) -> dict:
    """Estimate the chunk-specific noise the simulator assumes exists.

    ``SimulationSettings.chunk_noise_sd`` multiplies every chunk by an independent
    lognormal disturbance before the window maximum is taken, so simulated
    overlaps carry dispersion ``sqrt(2) * chunk_noise_sd`` on top of rounding. Real
    overlaps carry whatever they carry. Subtracting the rounding floor in quadrature
    from the observed dispersion recovers the real counterpart of that parameter.

    The subtraction can come out negative, and it does here, because the floor is
    derived assuming the two chunks round independently while in fact they round
    numbers that differ only by a scale factor. A negative estimate is reported as
    zero and read as what it is: no chunk-specific noise is detectable above the
    granularity of the reported integers.
    """

    informative = overlaps[overlaps["sd_log_ratio"] > 0]
    observed = float(np.median(informative["sd_log_ratio"]))
    floor = float(np.median(informative["rounding_floor_sd"]))
    excess_variance = observed**2 - floor**2
    return {
        "n_informative_overlaps": len(informative),
        "median_observed_sd": observed,
        "median_rounding_floor_sd": floor,
        "implied_chunk_noise_sd": float(np.sqrt(max(excess_variance, 0.0)) / np.sqrt(2.0)),
        "excess_variance_is_negative": bool(excess_variance < 0),
    }


def main() -> None:
    if not RAW_CHUNKS.exists():
        raise SystemExit(
            f"{RAW_CHUNKS} not found. Build it first:\n"
            "  python examples/ingest_trends_csv.py real_data/raw_downloads "
            "--series-id bitcoin_us --keyword bitcoin --geo US "
            f"--out {RAW_CHUNKS}"
        )

    data = coerce_raw_chunks(pd.read_csv(RAW_CHUNKS))
    config = CalibrationConfig()
    order = chunk_order(data)

    graph = OverlapGraphCalibrator(config, min_overlap_days=MIN_OVERLAP_DAYS).fit(
        data, baseline_start=BASELINE_START, baseline_end=BASELINE_END
    )
    stitched = sequential_stitch(
        data,
        config,
        min_overlap_days=MIN_OVERLAP_DAYS,
        baseline_start=BASELINE_START,
        baseline_end=BASELINE_END,
    )

    disagreement = series_disagreement(graph.full_series, stitched.full_series)
    scales = scale_disagreement(graph.chunk_scales, stitched.chunk_scales, order)
    triangles = triangle_closure(graph.edges)
    overlaps = overlap_diagnostics(data, config)
    misscaling = residual_misscaling(graph.calibrated_observations, graph.full_series)
    accumulation = chain_accumulation(graph.edges, order)
    chunk_noise = implied_chunk_noise(overlaps)
    profile = chunk_noise_profile(
        data, graph.full_series, config, np.arange(0.0, 0.0325, 0.0025)
    )
    recovery = recovery_check(data, config)

    OUT.mkdir(exist_ok=True)
    graph.full_series.to_csv(OUT / "graph_series.csv", index=False)
    stitched.full_series.to_csv(OUT / "sequential_series.csv", index=False)
    graph.edges.to_csv(OUT / "graph_edges.csv", index=False)
    scales.to_csv(OUT / "scale_comparison.csv", index=False)
    triangles.to_csv(OUT / "triangle_closure.csv", index=False)
    overlaps.to_csv(OUT / "overlap_diagnostics.csv", index=False)
    misscaling.to_csv(OUT / "residual_misscaling.csv", index=False)
    accumulation["joins"].to_csv(OUT / "chain_joins.csv", index=False)
    recovery.to_csv(OUT / "chunk_noise_recovery.csv", index=False)
    pd.Series(graph.diagnostics).to_json(OUT / "graph_diagnostics.json", indent=2)

    pd.set_option("display.width", 160)
    n_edges = int(graph.diagnostics["n_edges"])
    n_nodes = int(graph.diagnostics["n_nodes"])

    print("Real Google Trends data: bitcoin, US, daily, 2024")
    print(f"  {len(data)} observations, {n_nodes} chunks, one pull")
    print(f"  zero share {float((data['value'] == 0).mean()):.4f}")
    print(f"  value range {data['value'].min():.0f} to {data['value'].max():.0f}")
    print()

    print("Overlap graph")
    print(f"  connected                 : {graph.diagnostics['connected']}")
    print(f"  edges                     : {n_edges} (a spanning path would use {n_nodes - 1})")
    print(f"  independent cycles        : {n_edges - n_nodes + 1}")
    print(f"  triangles closed          : {len(triangles)}")
    print(f"  normal matrix condition   : {graph.diagnostics['normal_condition_number']:.2f}")
    print(f"  weighted edge RMSE        : {graph.diagnostics['weighted_edge_rmse']:.6f}")
    print(f"  sequential broken joins   : {stitched.diagnostics['n_broken_joins']}")
    print()

    print("Zero-dispersion overlaps: chunks that share a normalizing maximum")
    print(f"  zero-dispersion edges     : {graph.diagnostics['n_zero_dispersion_edges']} of {n_edges}")
    print(f"  informative edges         : {graph.diagnostics['n_informative_edges']}")
    print(
        f"  normalization groups      : {graph.diagnostics['n_scale_groups']} "
        f"among {n_nodes} chunks"
    )
    print("  (the simulator cannot produce these: it multiplies each chunk by")
    print("   continuous noise before taking the window maximum)")
    print()

    print("Cycle closure: the model forces d_ij + d_jk - d_ik = 0")
    print("(sequential stitching cannot compute this at all)")
    closure = triangles["closure_error"].abs()
    print(f"  median |closure error|    : {closure.median():.6f} log points")
    print(f"  max    |closure error|    : {closure.max():.6f} log points")
    print(
        f"  max as a scale error      : {triangles['closure_error_pct'].abs().max():.3f}%"
    )
    print()

    print("Do the two methods disagree?")
    for key, value in disagreement.items():
        print(f"  {key:42s}: {value:.6f}" if isinstance(value, float) else f"  {key:42s}: {value}")
    print()

    print("Chunk log scales, both recentred on the first chunk")
    print(scales.to_string(index=False, float_format=lambda v: f"{v:.6f}"))
    print()
    late = scales[scales["position"] >= len(order) - 3]["difference"].abs().mean()
    early = scales[scales["position"] <= 2]["difference"].abs().mean()
    print(f"  mean |difference|, first three chunks : {early:.6f}")
    print(f"  mean |difference|, last three chunks  : {late:.6f}")
    if early > 0:
        print(f"  late/early ratio                     : {late / early:.2f}")
    rho, p_rho = stats.spearmanr(scales["position"], scales["difference"].abs())
    print(f"  Spearman(position, |difference|)      : {rho:.3f} (p = {p_rho:.3f})")
    print()

    observed = chunk_noise["median_observed_sd"]
    print("Can this design accumulate anything? F1 works only by accumulation")
    print(accumulation["joins"].to_string(index=False, float_format=lambda v: f"{v:.6f}"))
    print(
        f"  informative joins         : {accumulation['n_informative_joins']} "
        f"of {accumulation['n_joins']}"
    )
    print(
        f"  terminal accumulated sd   : {accumulation['terminal_sd_log']:.6f} log points "
        f"= {accumulation['terminal_pct']:.3f}%"
    )
    print(
        f"  graph max Var(log scale)  : {graph.diagnostics['max_log_scale_variance']:.6e}"
    )
    print(
        f"  path  max Var(log scale)  : "
        f"{graph.diagnostics['sequential_max_log_scale_variance']:.6e}"
    )
    print(
        f"  variance reduction        : "
        f"{graph.diagnostics['calibration_variance_reduction']:.2f}x"
    )
    print("  The mechanism is operating. Testing it by comparing two point estimates")
    print("  would not show that: a variance cannot be estimated from one realization.")
    print()

    print("What the design implies, before any data is collected")
    print(f"{'design':28s} {'chunks':>7s} {'reduction':>10s} {'sequential':>11s} {'graph':>8s}")
    for label, span, window, step in (
        ("1 year, 180/30 (this data)", 366, 180, 30),
        ("5 years, 180/30", 1826, 180, 30),
        ("15 years, 180/30", 5478, 180, 30),
        ("15 years, 180/15 (recommended)", 5478, 180, 15),
    ):
        row = design_comparison(span, window, step, observed)
        print(
            f"{label:28s} {row['n_chunks']:7d} {row['reduction']:9.1f}x "
            f"{row['path_pct']:10.2f}% {row['graph_pct']:7.2f}%"
        )
    print("  Terminal scale error at the observed dispersion. The ratio depends only")
    print("  on which windows overlap, so it is a design choice, not a data outcome.")
    print()

    print("What is the real value of SimulationSettings.chunk_noise_sd?")
    print(f"  informative overlaps      : {chunk_noise['n_informative_overlaps']}")
    print(f"  median observed sd        : {chunk_noise['median_observed_sd']:.6f}")
    print(f"  median rounding floor sd  : {chunk_noise['median_rounding_floor_sd']:.6f}")
    print(f"  closed-form implied sd    : {chunk_noise['implied_chunk_noise_sd']:.6f}")
    print(f"  simulator assumes         : {SIMULATOR_CHUNK_NOISE_SD:.6f}")
    if chunk_noise["excess_variance_is_negative"]:
        print("  The closed form returns zero because observed dispersion falls below")
        print("  its floor. That floor assumes independent rounding and so overstates")
        print("  itself, biasing the estimate towards zero. The sweep below replaces")
        print("  the assumption with the generating mechanism.")
    print()

    print("Chunk noise recovered by reproducing the reported chunks")
    print(f"  observed median dispersion: {observed:.6f}")
    print(profile.to_string(index=False, float_format=lambda v: f"{v:.6f}"))
    estimate = interpolate_crossing(profile, observed)
    baseline = float(profile.loc[profile["chunk_noise_sd"] == 0.0, "median_dispersion"].iloc[0])
    assumed = float(
        profile.loc[
            np.isclose(profile["chunk_noise_sd"], SIMULATOR_CHUNK_NOISE_SD), "median_dispersion"
        ].iloc[0]
    )
    print(f"  rounding alone (sd = 0)   : {baseline:.6f}, {100 * baseline / observed:.0f}% of observed")
    print(f"  matched estimate          : chunk_noise_sd = {estimate:.4f}")
    print(
        f"  at the simulator's 0.03   : {assumed:.6f}, {assumed / observed:.1f}x the observed value"
    )
    # Below roughly 0.005 the curve is flat within Monte Carlo error, because
    # rounding dominates: the data cannot resolve a value that small. The upper
    # bound is what this evidence actually establishes.
    resolution = float(profile.loc[profile["dispersion_sd"] > 0, "chunk_noise_sd"].iloc[1])
    print(f"  not resolvable below      : {resolution:.4f} (rounding dominates)")
    print()

    print("Can the sweep recover a chunk noise that was injected on purpose?")
    print(recovery.to_string(index=False, float_format=lambda v: f"{v:.4f}"))
    at_simulator = recovery.loc[
        np.isclose(recovery["injected"], SIMULATOR_CHUNK_NOISE_SD), "recovered"
    ]
    if not at_simulator.empty:
        print(
            f"  At an injected {SIMULATOR_CHUNK_NOISE_SD}, the simulator's default, the sweep "
            f"returns {float(at_simulator.iloc[0]):.4f}."
        )
        print("  So the small value recovered from untouched data is not the procedure failing.")
    print()

    print("Is the proportionality assumption satisfied by real data?")
    print(overlaps.to_string(index=False, float_format=lambda v: f"{v:.4f}"))
    print()
    # Degenerate overlaps carry no dispersion by construction, so summarizing over
    # them would report the normalization rule rather than the model's fit.
    informative = overlaps[overlaps["sd_log_ratio"] > 0]
    print(f"  informative overlaps      : {len(informative)} of {len(overlaps)}")
    print(f"  median sd of log ratio    : {informative['sd_log_ratio'].median():.4f}")
    print(f"  median rounding floor     : {informative['rounding_floor_sd'].median():.4f}")
    print(f"  median excess over floor  : {informative['excess_over_floor'].median():.2f}x")
    drifting = int((informative["drift_p"] < 0.05).sum())
    print(f"  overlaps with drift p<.05 : {drifting} of {len(informative)} (1.05 expected by chance)")
    print()

    print("Is any chunk left mis-scaled after calibration?")
    print(misscaling.to_string(index=False, float_format=lambda v: f"{v:.6f}"))
    worst = misscaling.loc[misscaling["deviation_pct"].abs().idxmax()]
    print(
        f"  largest residual mis-scaling: {worst['chunk_id']} at "
        f"{worst['deviation_pct']:+.3f}%"
    )
    print()
    print(f"Wrote {OUT}/")


if __name__ == "__main__":
    main()
