from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from itertools import combinations
from pathlib import Path

import networkx as nx
import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from .config import DuplicateConfig
from .schema import vector_to_bytes


@dataclass
class DuplicateDiagnostics:
    exact_groups: pd.DataFrame
    pairwise_metrics: pd.DataFrame
    components: pd.DataFrame
    membership: pd.DataFrame
    residual_matrix: pd.DataFrame
    summary: dict

    def save(self, output_dir: str | Path) -> dict[str, Path]:
        output = Path(output_dir)
        output.mkdir(parents=True, exist_ok=True)
        paths = {
            "exact_groups": output / "exact_duplicate_groups.csv",
            "pairwise_metrics": output / "pairwise_similarity.csv",
            "components": output / "near_duplicate_components.csv",
            "membership": output / "near_duplicate_membership.csv",
            "residuals": output / "pull_residuals.csv",
            "summary": output / "duplicate_summary.json",
        }
        self.exact_groups.to_csv(paths["exact_groups"], index=False)
        self.pairwise_metrics.to_csv(paths["pairwise_metrics"], index=False)
        self.components.to_csv(paths["components"], index=False)
        self.membership.to_csv(paths["membership"], index=False)
        self.residual_matrix.to_csv(paths["residuals"], index=True)
        paths["summary"].write_text(json.dumps(self.summary, indent=2, default=str), encoding="utf-8")
        return paths


def _vector_hash(series: pd.Series, decimals: int) -> str:
    return hashlib.sha256(vector_to_bytes(series.to_numpy(), decimals=decimals)).hexdigest()


def _safe_corr(x: np.ndarray, y: np.ndarray) -> float:
    if len(x) < 2 or np.std(x) <= 1e-15 or np.std(y) <= 1e-15:
        return float("nan")
    return float(np.corrcoef(x, y)[0, 1])


def _pair_metrics(
    a: pd.Series,
    b: pd.Series,
    residual_a: pd.Series,
    residual_b: pd.Series,
    tolerance: float,
) -> dict:
    pair = pd.concat([a, b, residual_a, residual_b], axis=1).dropna()
    pair.columns = ["a", "b", "ra", "rb"]
    if pair.empty:
        return {
            "n_common": 0,
            "raw_pearson": np.nan,
            "raw_spearman": np.nan,
            "residual_pearson": np.nan,
            "exact_cell_agreement": np.nan,
            "mae": np.nan,
            "mae_100": np.nan,
            "smape": np.nan,
            "zero_nonzero_agreement": np.nan,
            "positive_jaccard": np.nan,
        }
    av = pair["a"].to_numpy(dtype=float)
    bv = pair["b"].to_numpy(dtype=float)
    rav = pair["ra"].to_numpy(dtype=float)
    rbv = pair["rb"].to_numpy(dtype=float)
    raw_pearson = _safe_corr(av, bv)
    spearman = spearmanr(av, bv, nan_policy="omit").statistic
    residual_corr = _safe_corr(rav, rbv)
    exact = float(np.mean(np.abs(av - bv) <= tolerance))
    mae = float(np.mean(np.abs(av - bv)))
    denom = np.abs(av) + np.abs(bv)
    smape_terms = np.where(denom > tolerance, 2.0 * np.abs(av - bv) / denom, 0.0)
    smape = float(np.mean(smape_terms))
    apos = av > 0
    bpos = bv > 0
    zero_nonzero = float(np.mean(apos == bpos))
    union = int(np.sum(apos | bpos))
    jaccard = float(np.sum(apos & bpos) / union) if union else 1.0
    return {
        "n_common": len(pair),
        "raw_pearson": raw_pearson,
        "raw_spearman": float(spearman) if np.isfinite(spearman) else np.nan,
        "residual_pearson": residual_corr,
        "exact_cell_agreement": exact,
        "mae": mae,
        "mae_100": mae / 100.0,
        "smape": smape,
        "zero_nonzero_agreement": zero_nonzero,
        "positive_jaccard": jaccard,
    }


def diagnose_duplicates(
    matrix: pd.DataFrame,
    config: DuplicateConfig,
    metadata: pd.DataFrame | None = None,
) -> DuplicateDiagnostics:
    """Diagnose exact and near-duplicate pulls without outcome-guided deletion.

    Near-duplicate dependence is assessed after removing a preliminary common signal and
    a pull-specific additive bias. Exact groups are retained in the audit record.
    """

    if matrix.shape[1] < 2:
        raise ValueError("At least two pulls are required")
    matrix = matrix.sort_index().copy()
    preliminary = matrix.median(axis=1, skipna=True)
    raw_residuals = matrix.sub(preliminary, axis=0)
    pull_bias = raw_residuals.mean(axis=0, skipna=True)
    residuals = raw_residuals.sub(pull_bias, axis=1)

    hash_rows = []
    for pull_id in matrix.columns:
        hash_rows.append(
            {
                "pull_id": str(pull_id),
                "vector_hash": _vector_hash(matrix[pull_id], config.hash_decimals),
            }
        )
    hashes = pd.DataFrame(hash_rows)
    groups = []
    for group_no, (digest, group) in enumerate(hashes.groupby("vector_hash"), start=1):
        members = sorted(group["pull_id"].tolist())
        if len(members) > 1:
            groups.append(
                {
                    "exact_group_id": f"E{group_no:03d}",
                    "vector_hash": digest,
                    "size": len(members),
                    "members": json.dumps(members),
                }
            )
    exact_groups = pd.DataFrame(
        groups, columns=["exact_group_id", "vector_hash", "size", "members"]
    )

    pair_rows: list[dict] = []
    graph = nx.Graph()
    graph.add_nodes_from(map(str, matrix.columns))
    for pull_a, pull_b in combinations(matrix.columns, 2):
        metrics = _pair_metrics(
            matrix[pull_a],
            matrix[pull_b],
            residuals[pull_a],
            residuals[pull_b],
            config.exact_tolerance,
        )
        enough = metrics["n_common"] >= config.min_pair_observations
        raw_rule = (
            enough
            and np.isfinite(metrics["raw_pearson"])
            and metrics["raw_pearson"] >= config.raw_correlation_threshold
            and metrics["exact_cell_agreement"] >= config.exact_cell_agreement_threshold
            and metrics["mae_100"] <= config.mae_100_threshold
            and metrics["positive_jaccard"] >= config.positive_jaccard_threshold
        )
        residual_rule = (
            enough
            and np.isfinite(metrics["residual_pearson"])
            and metrics["residual_pearson"] >= config.residual_correlation_threshold
            and metrics["mae_100"] <= config.mae_100_threshold
        )
        near_duplicate = bool(raw_rule and (residual_rule if config.use_residual_rule else True))
        exact_vector = bool(
            hashes.loc[hashes["pull_id"] == str(pull_a), "vector_hash"].iloc[0]
            == hashes.loc[hashes["pull_id"] == str(pull_b), "vector_hash"].iloc[0]
        )
        row = {
            "pull_a": str(pull_a),
            "pull_b": str(pull_b),
            **metrics,
            "raw_rule": bool(raw_rule),
            "residual_rule": bool(residual_rule),
            "near_duplicate": near_duplicate,
            "exact_vector": exact_vector,
        }
        pair_rows.append(row)
        if near_duplicate or exact_vector:
            graph.add_edge(str(pull_a), str(pull_b), **row)
    pairwise = pd.DataFrame(pair_rows)

    meta_map: dict[str, dict] = {}
    if metadata is not None and "pull_id" in metadata.columns:
        for row in metadata.drop_duplicates("pull_id").to_dict(orient="records"):
            meta_map[str(row["pull_id"])] = row

    component_rows: list[dict] = []
    membership_rows: list[dict] = []
    nontrivial_components = [c for c in nx.connected_components(graph) if len(c) > 1]
    for idx, members_set in enumerate(
        sorted(nontrivial_components, key=lambda c: (-len(c), sorted(c))), start=1
    ):
        members = sorted(members_set)
        sub = graph.subgraph(members).copy()
        component_id = f"N{idx:03d}"
        density = float(nx.density(sub))
        diameter = int(nx.diameter(sub)) if nx.is_connected(sub) and len(sub) > 1 else 0
        pairs = pairwise[
            pairwise.apply(
                lambda row, members=members: row["pull_a"] in members
                and row["pull_b"] in members,
                axis=1,
            )
        ]
        clique_size = max((len(c) for c in nx.find_cliques(sub)), default=1)
        articulation = sorted(nx.articulation_points(sub)) if len(sub) > 2 else []
        days = sorted(
            {
                meta_map[m].get("collection_day")
                for m in members
                if m in meta_map and meta_map[m].get("collection_day") is not None
            }
        )
        streams = sorted(
            {
                str(meta_map[m].get("stream_id"))
                for m in members
                if m in meta_map and meta_map[m].get("stream_id") is not None
            }
        )
        component_rows.append(
            {
                "component_id": component_id,
                "size": len(members),
                "share_of_pulls": len(members) / matrix.shape[1],
                "edge_count": sub.number_of_edges(),
                "density": density,
                "diameter": diameter,
                "max_clique_size": clique_size,
                "articulation_points": json.dumps(articulation),
                "min_raw_pearson": float(pairs["raw_pearson"].min()) if not pairs.empty else np.nan,
                "min_residual_pearson": float(pairs["residual_pearson"].min())
                if not pairs.empty
                else np.nan,
                "max_mae_100": float(pairs["mae_100"].max()) if not pairs.empty else np.nan,
                "members": json.dumps(members),
                "collection_days": json.dumps(days),
                "streams": json.dumps(streams),
            }
        )
        for member in members:
            row = {
                "component_id": component_id,
                "pull_id": member,
                "degree": int(sub.degree(member)),
                "is_articulation": member in articulation,
            }
            row.update({k: v for k, v in meta_map.get(member, {}).items() if k != "pull_id"})
            membership_rows.append(row)

    components = pd.DataFrame(component_rows)
    membership = pd.DataFrame(membership_rows)
    max_component_share = float(components["share_of_pulls"].max()) if not components.empty else 0.0
    summary = {
        "n_pulls": int(matrix.shape[1]),
        "n_exact_duplicate_groups": len(exact_groups),
        "n_exact_duplicate_members": int(exact_groups["size"].sum()) if not exact_groups.empty else 0,
        "n_near_duplicate_components": len(components),
        "max_component_share": max_component_share,
        "n_near_duplicate_edges": int(graph.number_of_edges()),
        "preliminary_signal": "cross-pull median",
        "residual_definition": "pull - cross-pull median - pull mean residual",
    }
    return DuplicateDiagnostics(
        exact_groups=exact_groups,
        pairwise_metrics=pairwise,
        components=components,
        membership=membership,
        residual_matrix=residuals,
        summary=summary,
    )
