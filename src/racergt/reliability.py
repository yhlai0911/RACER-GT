from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from .config import ConsensusConfig
from .consensus import fit_gls_consensus


@dataclass
class ReliabilityResult:
    summary: dict
    pairwise: pd.DataFrame
    convergence: pd.DataFrame
    dependence: pd.DataFrame

    def save(self, output_dir: str | Path) -> dict[str, Path]:
        output = Path(output_dir)
        output.mkdir(parents=True, exist_ok=True)
        paths = {
            "pairwise": output / "reliability_pairwise.csv",
            "convergence": output / "consensus_convergence.csv",
            "dependence": output / "day_stream_dependence.csv",
        }
        self.pairwise.to_csv(paths["pairwise"], index=False)
        self.convergence.to_csv(paths["convergence"], index=False)
        self.dependence.to_csv(paths["dependence"], index=False)
        return paths


def fleiss_kappa_binary(matrix: pd.DataFrame) -> float:
    observed = matrix.dropna(axis=0, how="any").to_numpy(dtype=float)
    if observed.shape[0] == 0 or observed.shape[1] < 2:
        return float("nan")
    binary = (observed > 0).astype(int)
    n = binary.shape[1]
    counts_1 = binary.sum(axis=1)
    counts_0 = n - counts_1
    p_i = (counts_0**2 + counts_1**2 - n) / (n * (n - 1))
    p_bar = float(np.mean(p_i))
    p1 = float(counts_1.sum() / (binary.shape[0] * n))
    p0 = 1.0 - p1
    p_e = p0**2 + p1**2
    return (p_bar - p_e) / (1.0 - p_e) if p_e < 1 else float("nan")


def _pairwise_reliability(matrix: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for a, b in combinations(matrix.columns, 2):
        pair = matrix[[a, b]].dropna()
        av = pair[a].to_numpy(dtype=float)
        bv = pair[b].to_numpy(dtype=float)
        if len(pair) < 3:
            pearson = spearman = innovation_corr = np.nan
        else:
            pearson = float(np.corrcoef(av, bv)[0, 1]) if np.std(av) > 0 and np.std(bv) > 0 else np.nan
            sp = spearmanr(av, bv).statistic
            spearman = float(sp) if np.isfinite(sp) else np.nan
            ia = np.diff(np.log1p(np.maximum(av, 0)))
            ib = np.diff(np.log1p(np.maximum(bv, 0)))
            innovation_corr = (
                float(np.corrcoef(ia, ib)[0, 1])
                if len(ia) > 2 and np.std(ia) > 0 and np.std(ib) > 0
                else np.nan
            )
        apos = av > 0
        bpos = bv > 0
        union = int(np.sum(apos | bpos))
        rows.append(
            {
                "pull_a": str(a),
                "pull_b": str(b),
                "n_common": int(len(pair)),
                "level_pearson": pearson,
                "level_spearman": spearman,
                "innovation_pearson": innovation_corr,
                "zero_nonzero_agreement": float(np.mean(apos == bpos)) if len(pair) else np.nan,
                "positive_jaccard": float(np.sum(apos & bpos) / union) if union else 1.0,
                "mae": float(np.mean(np.abs(av - bv))) if len(pair) else np.nan,
                "mae_100": float(np.mean(np.abs(av - bv)) / 100.0) if len(pair) else np.nan,
            }
        )
    return pd.DataFrame(rows)


def _dependence_table(pairwise: pd.DataFrame, metadata: pd.DataFrame | None) -> pd.DataFrame:
    if metadata is None or "pull_id" not in metadata.columns:
        return pd.DataFrame()
    meta = metadata.drop_duplicates("pull_id").copy()
    meta["pull_id"] = meta["pull_id"].astype(str)
    maps = meta.set_index("pull_id").to_dict(orient="index")
    data = pairwise.copy()
    data["same_day"] = data.apply(
        lambda r: maps.get(r["pull_a"], {}).get("collection_day")
        == maps.get(r["pull_b"], {}).get("collection_day"),
        axis=1,
    )
    data["same_stream"] = data.apply(
        lambda r: maps.get(r["pull_a"], {}).get("stream_id")
        == maps.get(r["pull_b"], {}).get("stream_id"),
        axis=1,
    )
    data["day_gap"] = data.apply(
        lambda r: abs(
            float(maps.get(r["pull_a"], {}).get("collection_day", np.nan))
            - float(maps.get(r["pull_b"], {}).get("collection_day", np.nan))
        ),
        axis=1,
    )
    rows = []
    for same_day in [True, False]:
        for same_stream in [True, False]:
            subset = data[(data["same_day"] == same_day) & (data["same_stream"] == same_stream)]
            if subset.empty:
                continue
            rows.append(
                {
                    "same_day": same_day,
                    "same_stream": same_stream,
                    "n_pairs": len(subset),
                    "mean_level_pearson": subset["level_pearson"].mean(),
                    "mean_innovation_pearson": subset["innovation_pearson"].mean(),
                    "mean_mae_100": subset["mae_100"].mean(),
                    "mean_positive_jaccard": subset["positive_jaccard"].mean(),
                }
            )
    return pd.DataFrame(rows)


def consensus_convergence(
    matrix: pd.DataFrame,
    metadata: pd.DataFrame | None,
    consensus_config: ConsensusConfig,
    baseline_start: pd.Timestamp | str | None = None,
    baseline_end: pd.Timestamp | str | None = None,
    minimum_pulls: int = 3,
) -> pd.DataFrame:
    columns = list(map(str, matrix.columns))
    if metadata is not None and "pull_id" in metadata.columns:
        meta = metadata.drop_duplicates("pull_id").copy()
        meta["pull_id"] = meta["pull_id"].astype(str)
        sort_cols = [c for c in ["collection_day", "stream_id", "replicate_id"] if c in meta.columns]
        ordered = meta.sort_values(sort_cols)["pull_id"].tolist()
        columns = [c for c in ordered if c in matrix.columns]
    records = []
    previous: np.ndarray | None = None
    for n in range(minimum_pulls, len(columns) + 1):
        subset_cols = columns[:n]
        result = fit_gls_consensus(
            matrix[subset_cols],
            consensus_config,
            metadata=metadata,
            baseline_start=baseline_start,
            baseline_end=baseline_end,
        )
        current = result.consensus["value"].to_numpy(dtype=float)
        if previous is None:
            mae = max_change = np.nan
        else:
            diff = np.abs(current - previous)
            mae = float(np.nanmean(diff))
            max_change = float(np.nanmax(diff))
        records.append(
            {
                "n_pulls": n,
                "last_pull_added": subset_cols[-1],
                "mae_from_previous": mae,
                "mae_100_from_previous": mae / 100.0 if np.isfinite(mae) else np.nan,
                "max_abs_change": max_change,
                "spectral_effective_pulls": result.diagnostics["spectral_effective_pulls"],
                "kish_effective_pulls": result.diagnostics["kish_effective_pulls"],
            }
        )
        previous = current
    return pd.DataFrame(records)


def assess_reliability(
    matrix: pd.DataFrame,
    metadata: pd.DataFrame | None,
    consensus_config: ConsensusConfig,
    baseline_start: pd.Timestamp | str | None = None,
    baseline_end: pd.Timestamp | str | None = None,
) -> ReliabilityResult:
    pairwise = _pairwise_reliability(matrix)
    convergence = consensus_convergence(
        matrix,
        metadata,
        consensus_config,
        baseline_start=baseline_start,
        baseline_end=baseline_end,
    )
    dependence = _dependence_table(pairwise, metadata)
    final_convergence = (
        convergence.iloc[-1]["mae_100_from_previous"] if not convergence.empty else np.nan
    )
    summary = {
        "detection_fleiss_kappa": fleiss_kappa_binary(matrix),
        "median_level_pearson": float(pairwise["level_pearson"].median()),
        "median_level_spearman": float(pairwise["level_spearman"].median()),
        "median_innovation_pearson": float(pairwise["innovation_pearson"].median()),
        "median_positive_jaccard": float(pairwise["positive_jaccard"].median()),
        "median_pairwise_mae_100": float(pairwise["mae_100"].median()),
        "final_convergence_mae_100": float(final_convergence),
    }
    return ReliabilityResult(
        summary=summary,
        pairwise=pairwise,
        convergence=convergence,
        dependence=dependence,
    )
