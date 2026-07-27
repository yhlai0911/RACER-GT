from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from .config import GStudyConfig

COMPONENT_NAMES = ["T", "D", "S", "TD", "TS", "DS", "TDS", "E"]


@dataclass
class GStudyResult:
    transformation: str
    anova: pd.DataFrame
    variance_components: pd.DataFrame
    coefficients: dict
    d_study: pd.DataFrame
    bootstrap: pd.DataFrame
    diagnostics: dict

    def save(self, output_dir: str | Path) -> dict[str, Path]:
        output = Path(output_dir)
        output.mkdir(parents=True, exist_ok=True)
        stem = self.transformation
        paths = {
            "anova": output / f"gstudy_{stem}_anova.csv",
            "components": output / f"gstudy_{stem}_variance_components.csv",
            "d_study": output / f"gstudy_{stem}_dstudy.csv",
            "bootstrap": output / f"gstudy_{stem}_bootstrap.csv",
        }
        self.anova.to_csv(paths["anova"], index=False)
        self.variance_components.to_csv(paths["components"], index=False)
        self.d_study.to_csv(paths["d_study"], index=False)
        self.bootstrap.to_csv(paths["bootstrap"], index=False)
        return paths


def transform_complete_pulls(data: pd.DataFrame, transformation: str) -> pd.DataFrame:
    required = {
        "historical_date",
        "pull_id",
        "collection_day",
        "stream_id",
        "replicate_id",
        "value",
    }
    missing = required.difference(data.columns)
    if missing:
        raise ValueError(f"Missing G-study columns: {sorted(missing)}")
    frame = data.copy()
    frame["historical_date"] = pd.to_datetime(frame["historical_date"]).dt.normalize()
    frame["value"] = pd.to_numeric(frame["value"], errors="coerce").astype(float)
    if transformation == "level":
        frame["g_value"] = frame["value"]
    elif transformation == "detection":
        frame["g_value"] = (frame["value"] > 0).astype(float)
    elif transformation == "innovation":
        frame = frame.sort_values(["pull_id", "historical_date"])
        frame["g_value"] = frame.groupby("pull_id", sort=False)["value"].transform(
            lambda s: np.log1p(s).diff()
        )
    else:
        raise ValueError(f"Unknown transformation: {transformation}")
    frame = frame.dropna(subset=["g_value"])

    # Keep only dates observed in every day x stream x replicate combination.
    expected = (
        frame[["collection_day", "stream_id", "replicate_id"]]
        .drop_duplicates()
        .shape[0]
    )
    counts = frame.groupby("historical_date")["pull_id"].nunique()
    common_dates = counts[counts == expected].index
    return frame[frame["historical_date"].isin(common_dates)].copy()


def _balanced_layout(frame: pd.DataFrame) -> tuple[int, int, int, int]:
    t_levels = frame["historical_date"].nunique()
    d_levels = frame["collection_day"].nunique()
    s_levels = frame["stream_id"].nunique()
    cell_counts = frame.groupby(["historical_date", "collection_day", "stream_id"]).size()
    if cell_counts.empty or cell_counts.nunique() != 1:
        raise ValueError("G-study requires an equal number of replicates in every T x D x S cell")
    r_levels = int(cell_counts.iloc[0])
    expected_cells = t_levels * d_levels * s_levels
    if len(cell_counts) != expected_cells:
        raise ValueError("G-study design is not fully crossed across T, D, and S")
    expected_rows = expected_cells * r_levels
    if len(frame) != expected_rows:
        raise ValueError("Unexpected duplicate or missing observations in balanced design")
    return t_levels, d_levels, s_levels, r_levels


def _anova_and_components(
    frame: pd.DataFrame,
    clip_negative: bool,
) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    a, b, c, r = _balanced_layout(frame)
    keys = ["historical_date", "collection_day", "stream_id"]
    cell = frame.groupby(keys, as_index=False)["g_value"].mean()
    # Construct a dense a x b x c array in deterministic order.
    t_vals = sorted(cell["historical_date"].unique())
    d_vals = sorted(cell["collection_day"].unique())
    s_vals = sorted(cell["stream_id"].astype(str).unique())
    t_map = {v: i for i, v in enumerate(t_vals)}
    d_map = {v: i for i, v in enumerate(d_vals)}
    s_map = {v: i for i, v in enumerate(s_vals)}
    arr = np.empty((a, b, c), dtype=float)
    for row in cell.itertuples(index=False):
        arr[t_map[row.historical_date], d_map[row.collection_day], s_map[str(row.stream_id)]] = row.g_value

    grand = float(arr.mean())
    mt = arr.mean(axis=(1, 2))
    md = arr.mean(axis=(0, 2))
    ms = arr.mean(axis=(0, 1))
    mtd = arr.mean(axis=2)
    mts = arr.mean(axis=1)
    mds = arr.mean(axis=0)

    ss_t = b * c * float(np.sum((mt - grand) ** 2))
    ss_d = a * c * float(np.sum((md - grand) ** 2))
    ss_s = a * b * float(np.sum((ms - grand) ** 2))
    ss_td = c * float(
        np.sum((mtd - mt[:, None] - md[None, :] + grand) ** 2)
    )
    ss_ts = b * float(
        np.sum((mts - mt[:, None] - ms[None, :] + grand) ** 2)
    )
    ss_ds = a * float(
        np.sum((mds - md[:, None] - ms[None, :] + grand) ** 2)
    )
    residual = (
        arr
        - mtd[:, :, None]
        - mts[:, None, :]
        - mds[None, :, :]
        + mt[:, None, None]
        + md[None, :, None]
        + ms[None, None, :]
        - grand
    )
    ss_tds = float(np.sum(residual**2))

    df = {
        "T": a - 1,
        "D": b - 1,
        "S": c - 1,
        "TD": (a - 1) * (b - 1),
        "TS": (a - 1) * (c - 1),
        "DS": (b - 1) * (c - 1),
        "TDS": (a - 1) * (b - 1) * (c - 1),
    }
    ss = {
        "T": ss_t,
        "D": ss_d,
        "S": ss_s,
        "TD": ss_td,
        "TS": ss_ts,
        "DS": ss_ds,
        "TDS": ss_tds,
    }
    ms = {name: ss[name] / df[name] if df[name] > 0 else np.nan for name in ss}

    if r > 1:
        merged = frame.merge(cell, on=keys, suffixes=("", "_cell"), validate="many_to_one")
        ss_e = float(np.sum((merged["g_value"] - merged["g_value_cell"]) ** 2))
        df_e = a * b * c * (r - 1)
        ms_e = ss_e / df_e
    else:
        ss_e = 0.0
        df_e = 0
        ms_e = 0.0

    raw = {
        "E": ms_e,
        "TDS": ms["TDS"] - ms_e / r if r > 1 else ms["TDS"],
        "TD": (ms["TD"] - ms["TDS"]) / c,
        "TS": (ms["TS"] - ms["TDS"]) / b,
        "DS": (ms["DS"] - ms["TDS"]) / a,
        "T": (ms["T"] - ms["TD"] - ms["TS"] + ms["TDS"]) / (b * c),
        "D": (ms["D"] - ms["TD"] - ms["DS"] + ms["TDS"]) / (a * c),
        "S": (ms["S"] - ms["TS"] - ms["DS"] + ms["TDS"]) / (a * b),
    }
    constrained = {name: max(float(raw[name]), 0.0) if clip_negative else float(raw[name]) for name in COMPONENT_NAMES}

    anova_rows = [
        {"source": name, "sum_sq": ss[name], "df": df[name], "mean_sq": ms[name]}
        for name in ["T", "D", "S", "TD", "TS", "DS", "TDS"]
    ]
    anova_rows.append({"source": "E", "sum_sq": ss_e, "df": df_e, "mean_sq": ms_e})
    anova = pd.DataFrame(anova_rows)
    component_rows = [
        {
            "component": name,
            "raw_variance": float(raw[name]),
            "variance": float(constrained[name]),
            "clipped": bool(clip_negative and raw[name] < 0),
        }
        for name in COMPONENT_NAMES
    ]
    components = pd.DataFrame(component_rows)
    diagnostics = {
        "n_historical_dates": a,
        "n_collection_days": b,
        "n_streams": c,
        "n_replicates": r,
        "replicate_error_separable": r > 1,
        "grand_mean": grand,
    }
    return anova, components, diagnostics


def generalizability_coefficients(
    components: dict[str, float],
    n_days: int,
    n_streams: int,
    n_replicates: int,
) -> dict[str, float]:
    t = components["T"]
    relative_error = (
        components["TD"] / n_days
        + components["TS"] / n_streams
        + components["TDS"] / (n_days * n_streams)
        + components["E"] / (n_days * n_streams * n_replicates)
    )
    absolute_error = relative_error + (
        components["D"] / n_days
        + components["S"] / n_streams
        + components["DS"] / (n_days * n_streams)
    )
    g = t / (t + relative_error) if (t + relative_error) > 0 else np.nan
    phi = t / (t + absolute_error) if (t + absolute_error) > 0 else np.nan
    return {
        "relative_error_variance": float(relative_error),
        "absolute_error_variance": float(absolute_error),
        "generalizability_coefficient": float(g),
        "dependability_coefficient": float(phi),
    }


def make_d_study(
    components: dict[str, float],
    day_grid: list[int],
    stream_grid: list[int],
    replicate_grid: list[int],
) -> pd.DataFrame:
    rows = []
    for nd in day_grid:
        for ns in stream_grid:
            for nr in replicate_grid:
                row = {"n_days": nd, "n_streams": ns, "n_replicates": nr}
                row.update(generalizability_coefficients(components, nd, ns, nr))
                rows.append(row)
    return pd.DataFrame(rows)


def _sample_block_indices(n: int, block_length: int, rng: np.random.Generator) -> np.ndarray:
    if block_length <= 0:
        raise ValueError("block_length must be positive")
    starts = rng.integers(0, max(n - block_length + 1, 1), size=int(np.ceil(n / block_length)))
    indices = np.concatenate([np.arange(s, min(s + block_length, n)) for s in starts])
    if len(indices) < n:
        extra = rng.integers(0, n, size=n - len(indices))
        indices = np.concatenate([indices, extra])
    return indices[:n]


def _block_bootstrap(
    frame: pd.DataFrame,
    config: GStudyConfig,
    n_days: int,
    n_streams: int,
    n_replicates: int,
) -> pd.DataFrame:
    if config.bootstrap_replications <= 0:
        return pd.DataFrame()
    dates = np.array(sorted(frame["historical_date"].unique()))
    rng = np.random.default_rng(config.random_seed)
    records = []
    for b in range(config.bootstrap_replications):
        idx = _sample_block_indices(len(dates), min(config.block_length, len(dates)), rng)
        sampled_parts = []
        for new_t, old_idx in enumerate(idx):
            part = frame[frame["historical_date"] == dates[old_idx]].copy()
            part["historical_date"] = pd.Timestamp("2000-01-01") + pd.Timedelta(days=int(new_t))
            sampled_parts.append(part)
        sampled = pd.concat(sampled_parts, ignore_index=True)
        _, comp_df, _ = _anova_and_components(sampled, config.clip_negative_components)
        comp = comp_df.set_index("component")["variance"].to_dict()
        coeff = generalizability_coefficients(comp, n_days, n_streams, n_replicates)
        record = {"bootstrap_id": b + 1, **{f"var_{k}": v for k, v in comp.items()}, **coeff}
        records.append(record)
    return pd.DataFrame(records)


def run_gstudy(
    data: pd.DataFrame,
    transformation: str,
    config: GStudyConfig,
    d_day_grid: list[int] | None = None,
    d_stream_grid: list[int] | None = None,
    d_replicate_grid: list[int] | None = None,
) -> GStudyResult:
    transformed = transform_complete_pulls(data, transformation)
    anova, components_df, diagnostics = _anova_and_components(
        transformed, config.clip_negative_components
    )
    components = components_df.set_index("component")["variance"].to_dict()
    nd = diagnostics["n_collection_days"]
    ns = diagnostics["n_streams"]
    nr = diagnostics["n_replicates"]
    coefficients = generalizability_coefficients(components, nd, ns, nr)

    day_grid = d_day_grid or sorted({1, 2, 3, nd, max(nd + 2, 7)})
    stream_grid = d_stream_grid or sorted({1, 2, ns, max(ns + 1, 4)})
    replicate_grid = d_replicate_grid or sorted({1, nr, max(nr + 1, 2)})
    d_study = make_d_study(components, day_grid, stream_grid, replicate_grid)
    bootstrap = _block_bootstrap(transformed, config, nd, ns, nr)
    if not bootstrap.empty:
        for key in ["generalizability_coefficient", "dependability_coefficient"]:
            coefficients[f"{key}_ci_lower_95"] = float(bootstrap[key].quantile(0.025))
            coefficients[f"{key}_ci_upper_95"] = float(bootstrap[key].quantile(0.975))
    diagnostics["transformation"] = transformation
    diagnostics["block_bootstrap_replications"] = config.bootstrap_replications
    return GStudyResult(
        transformation=transformation,
        anova=anova,
        variance_components=components_df,
        coefficients=coefficients,
        d_study=d_study,
        bootstrap=bootstrap,
        diagnostics=diagnostics,
    )


def run_all_gstudies(data: pd.DataFrame, config: GStudyConfig) -> dict[str, GStudyResult]:
    return {
        transformation: run_gstudy(data, transformation, config)
        for transformation in config.transformations
    }
