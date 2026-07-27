from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

import networkx as nx
import numpy as np
import pandas as pd
from numpy.typing import NDArray

from .config import CalibrationConfig


@dataclass
class EdgeEstimate:
    chunk_i: str
    chunk_j: str
    log_ratio: float
    variance: float
    robust_scale: float
    n_overlap: int
    n_usable: int
    mean_abs_residual: float


@dataclass
class CalibrationResult:
    pull_id: str
    series_id: str
    full_series: pd.DataFrame
    calibrated_observations: pd.DataFrame
    chunk_scales: pd.DataFrame
    edges: pd.DataFrame
    diagnostics: dict


class OverlapGraphError(RuntimeError):
    pass


def huber_location(
    values: NDArray[np.floating],
    c: float = 1.345,
    max_iter: int = 100,
    tol: float = 1e-8,
) -> tuple[float, float, float]:
    """Robust Huber location, robust scale, and approximate variance of location."""

    x = np.asarray(values, dtype=float)
    x = x[np.isfinite(x)]
    if x.size == 0:
        raise ValueError("No finite observations")
    if x.size == 1:
        return float(x[0]), 0.0, np.inf

    loc = float(np.median(x))
    mad = float(np.median(np.abs(x - loc)))
    scale = 1.4826 * mad
    if not np.isfinite(scale) or scale <= 1e-12:
        scale = float(np.std(x, ddof=1))
    if not np.isfinite(scale) or scale <= 1e-12:
        return loc, 0.0, 1e-12

    for _ in range(max_iter):
        u = (x - loc) / scale
        abs_u = np.abs(u)
        weights = np.ones_like(abs_u)
        mask = abs_u > c
        weights[mask] = c / abs_u[mask]
        new_loc = float(np.sum(weights * x) / np.sum(weights))
        if abs(new_loc - loc) <= tol * max(1.0, abs(loc)):
            loc = new_loc
            break
        loc = new_loc

    resid = x - loc
    mad = float(np.median(np.abs(resid)))
    robust_scale = max(1.4826 * mad, 1e-12)
    u = resid / robust_scale
    abs_u = np.abs(u)
    weights = np.ones_like(abs_u)
    mask = abs_u > c
    weights[mask] = c / abs_u[mask]
    n_eff = float(np.sum(weights) ** 2 / np.sum(weights**2))
    variance = robust_scale**2 / max(n_eff, 1.0)
    return loc, robust_scale, variance


def _select_reference(graph: nx.Graph, config: CalibrationConfig) -> str:
    if config.reference_strategy == "first":
        return sorted(graph.nodes)[0]
    if config.reference_strategy == "explicit":
        ref = str(config.explicit_reference_chunk)
        if ref not in graph:
            raise OverlapGraphError(f"Explicit reference chunk {ref!r} is absent")
        return ref
    weighted_degree = {
        node: sum(float(data.get("weight", 1.0)) for _, _, data in graph.edges(node, data=True))
        for node in graph.nodes
    }
    return max(weighted_degree, key=weighted_degree.get)


class OverlapGraphCalibrator:
    """Globally align separately normalized GT chunks using all usable overlaps.

    The positive-overlap model is

        log Y_jt - log Y_kt = ell_j - ell_k + nu_jkt.

    Pairwise robust locations become graph-edge measurements. A weighted graph
    least-squares problem estimates all relative log scales simultaneously, avoiding
    sequential error accumulation.
    """

    def __init__(self, config: CalibrationConfig, min_overlap_days: int = 14):
        self.config = config
        self.min_overlap_days = int(min_overlap_days)

    def _edge_estimates(self, data: pd.DataFrame) -> list[EdgeEstimate]:
        chunk_meta = (
            data.groupby("chunk_id")
            .agg(window_start=("window_start", "min"), window_end=("window_end", "max"))
            .sort_values("window_start")
        )
        chunks = chunk_meta.index.tolist()
        by_chunk = {
            cid: group.set_index("historical_date")["value"].sort_index()
            for cid, group in data.groupby("chunk_id")
        }
        edges: list[EdgeEstimate] = []

        for pos_i, cid_i in enumerate(chunks):
            end_i = chunk_meta.loc[cid_i, "window_end"]
            s_i = by_chunk[cid_i]
            for cid_j in chunks[pos_i + 1 :]:
                start_j = chunk_meta.loc[cid_j, "window_start"]
                if start_j > end_i:
                    break
                s_j = by_chunk[cid_j]
                common = s_i.index.intersection(s_j.index)
                if len(common) < self.min_overlap_days:
                    continue
                pair = pd.concat([s_i.loc[common], s_j.loc[common]], axis=1)
                pair.columns = ["i", "j"]
                usable = pair[
                    (pair["i"] >= self.config.min_value)
                    & (pair["j"] >= self.config.min_value)
                    & pair["i"].notna()
                    & pair["j"].notna()
                ]
                if len(usable) < self.min_overlap_days:
                    continue
                diffs = np.log(usable["i"].to_numpy()) - np.log(usable["j"].to_numpy())
                loc, scale, var = huber_location(
                    diffs,
                    c=self.config.huber_c,
                    max_iter=self.config.max_huber_iter,
                    tol=self.config.huber_tol,
                )
                var = max(float(var), self.config.edge_variance_floor)
                edges.append(
                    EdgeEstimate(
                        chunk_i=str(cid_i),
                        chunk_j=str(cid_j),
                        log_ratio=float(loc),
                        variance=var,
                        robust_scale=float(scale),
                        n_overlap=len(common),
                        n_usable=len(usable),
                        mean_abs_residual=float(np.mean(np.abs(diffs - loc))),
                    )
                )
        return edges

    def _solve_scales(
        self, chunks: Iterable[str], edges: list[EdgeEstimate]
    ) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
        nodes = sorted(set(map(str, chunks)))
        graph = nx.Graph()
        graph.add_nodes_from(nodes)
        for edge in edges:
            weight = min(1.0 / edge.variance, self.config.max_edge_weight)
            graph.add_edge(edge.chunk_i, edge.chunk_j, weight=weight)

        components = list(nx.connected_components(graph))
        if len(components) != 1 and not self.config.allow_disconnected:
            sizes = sorted((len(c) for c in components), reverse=True)
            raise OverlapGraphError(
                f"Overlap graph is disconnected ({len(components)} components; sizes={sizes})"
            )

        if len(components) != 1:
            # Retain the largest component only when explicitly allowed.
            largest = max(components, key=len)
            nodes = sorted(largest)
            graph = graph.subgraph(largest).copy()
            edges = [e for e in edges if e.chunk_i in largest and e.chunk_j in largest]

        reference = _select_reference(graph, self.config)
        free_nodes = [n for n in nodes if n != reference]
        index = {n: i for i, n in enumerate(free_nodes)}
        bmat = np.zeros((len(edges), len(free_nodes)), dtype=float)
        dvec = np.zeros(len(edges), dtype=float)
        weights = np.zeros(len(edges), dtype=float)

        for row, edge in enumerate(edges):
            if edge.chunk_i != reference:
                bmat[row, index[edge.chunk_i]] = 1.0
            if edge.chunk_j != reference:
                bmat[row, index[edge.chunk_j]] = -1.0
            dvec[row] = edge.log_ratio
            weights[row] = min(1.0 / edge.variance, self.config.max_edge_weight)

        if bmat.shape[1] == 0:
            estimates = {reference: 0.0}
            variances = {reference: 0.0}
            fitted = np.zeros_like(dvec)
            rank = 0
            condition = 1.0
        else:
            normal = bmat.T @ (weights[:, None] * bmat)
            rhs = bmat.T @ (weights * dvec)
            rank = int(np.linalg.matrix_rank(normal))
            if rank < normal.shape[0]:
                raise OverlapGraphError("Scale normal matrix is rank deficient")
            condition = float(np.linalg.cond(normal))
            beta = np.linalg.solve(normal, rhs)
            covariance = np.linalg.inv(normal)
            estimates = {reference: 0.0}
            variances = {reference: 0.0}
            for node, idx in index.items():
                estimates[node] = float(beta[idx])
                variances[node] = float(max(covariance[idx, idx], 0.0))
            fitted = bmat @ beta

        edge_rows = []
        for edge, fit in zip(edges, fitted, strict=True):
            row = edge.__dict__.copy()
            row["weight"] = min(1.0 / edge.variance, self.config.max_edge_weight)
            row["fitted_log_ratio"] = float(fit)
            row["graph_residual"] = float(edge.log_ratio - fit)
            edge_rows.append(row)
        edge_df = pd.DataFrame(edge_rows)

        scale_rows = []
        for node in nodes:
            log_scale = estimates[node]
            variance = variances[node]
            scale_rows.append(
                {
                    "chunk_id": node,
                    "log_scale": log_scale,
                    "log_scale_variance": variance,
                    "scale": float(np.exp(log_scale)),
                    "reference_chunk": reference,
                }
            )
        scales = pd.DataFrame(scale_rows)

        # An overlap whose log ratio has no dispersion carries no information about
        # the relative scale beyond the single number it reports. On real Google
        # Trends data this is not a pathology but a routine consequence of the
        # normalization: each chunk is divided by its own window maximum, so two
        # windows containing the same peak day are returned as the same integers
        # wherever they overlap. Such an edge still enters the fit, at whatever
        # weight edge_variance_floor and max_edge_weight happen to permit, which is
        # a numerical choice rather than a statistical one. Chunks joined by these
        # edges form a normalization group whose members share a scale exactly, so
        # the number of groups, not the number of chunks, bounds how much
        # independent scale information the pull contains. Reported, not acted on.
        zero_dispersion = [e for e in edges if e.robust_scale == 0.0]
        group_graph = nx.Graph()
        group_graph.add_nodes_from(nodes)
        group_graph.add_edges_from((e.chunk_i, e.chunk_j) for e in zero_dispersion)

        diagnostics = {
            "connected": len(components) == 1,
            "n_components": len(components),
            "component_sizes": sorted((len(c) for c in components), reverse=True),
            "n_nodes": len(nodes),
            "n_edges": len(edges),
            "n_zero_dispersion_edges": len(zero_dispersion),
            "n_informative_edges": len(edges) - len(zero_dispersion),
            "n_scale_groups": nx.number_connected_components(group_graph),
            "reference_chunk": reference,
            "normal_rank": rank,
            "normal_condition_number": condition,
            "weighted_edge_rmse": float(
                np.sqrt(np.average(edge_df["graph_residual"] ** 2, weights=edge_df["weight"]))
            )
            if not edge_df.empty
            else 0.0,
        }
        return scales, edge_df, diagnostics

    def fit(
        self,
        data: pd.DataFrame,
        baseline_start: pd.Timestamp | str | None = None,
        baseline_end: pd.Timestamp | str | None = None,
    ) -> CalibrationResult:
        required = {
            "series_id",
            "pull_id",
            "chunk_id",
            "historical_date",
            "value",
            "window_start",
            "window_end",
        }
        missing = required.difference(data.columns)
        if missing:
            raise ValueError(f"Missing calibration columns: {sorted(missing)}")
        if data["pull_id"].nunique() != 1 or data["series_id"].nunique() != 1:
            raise ValueError("fit expects exactly one series_id and one pull_id")

        frame = data.copy()
        frame["historical_date"] = pd.to_datetime(frame["historical_date"]).dt.normalize()
        frame["window_start"] = pd.to_datetime(frame["window_start"]).dt.normalize()
        frame["window_end"] = pd.to_datetime(frame["window_end"]).dt.normalize()
        frame["value"] = pd.to_numeric(frame["value"], errors="coerce").astype(float)
        pull_id = str(frame["pull_id"].iloc[0])
        series_id = str(frame["series_id"].iloc[0])

        edges = self._edge_estimates(frame)
        if not edges and frame["chunk_id"].nunique() > 1:
            raise OverlapGraphError("No usable overlap edges could be estimated")
        scales, edge_df, diagnostics = self._solve_scales(frame["chunk_id"].unique(), edges)
        calibrated = frame.merge(scales, on="chunk_id", how="inner", validate="many_to_one")
        correction = -calibrated["log_scale"]
        if self.config.lognormal_bias_correction:
            correction = correction - 0.5 * calibrated["log_scale_variance"]
        calibrated["calibrated_value"] = calibrated["value"] * np.exp(correction)

        base_edge_var = (
            float(np.median(edge_df["variance"]))
            if not edge_df.empty
            else self.config.edge_variance_floor
        )
        calibrated["observation_log_variance"] = (
            calibrated["log_scale_variance"] + base_edge_var
        ).clip(lower=self.config.edge_variance_floor)

        rows: list[dict] = []
        # Zeros survive only when every chunk covering a date reports zero. Averaging a
        # zero against a positive chunk yields a positive value, so a date that was
        # partly zero in the raw responses leaves the series positive. That is a
        # property of the aggregation rule, not an imputation decision, but it changes
        # what detection reliability is measured on, so it is counted and reported.
        zero_chunk_dates = 0
        zero_masked_dates = 0
        for historical_date, group in calibrated.groupby("historical_date", sort=True):
            values = group["calibrated_value"].to_numpy(dtype=float)
            variances = group["observation_log_variance"].to_numpy(dtype=float)
            raw_values = group["value"].to_numpy(dtype=float)
            had_zero_chunk = bool(np.any(raw_values == 0.0))
            finite = np.isfinite(values) & np.isfinite(variances)
            values = values[finite]
            variances = variances[finite]
            if values.size == 0:
                value = np.nan
                se = np.nan
                n_chunks = 0
            elif self.config.aggregation == "median":
                value = float(np.median(values))
                mad = float(np.median(np.abs(values - value)))
                se = 1.4826 * mad / np.sqrt(max(values.size, 1))
                n_chunks = int(values.size)
            elif self.config.aggregation == "huber":
                value, _robust_scale, var_loc = huber_location(
                    values,
                    c=self.config.huber_c,
                    max_iter=self.config.max_huber_iter,
                    tol=self.config.huber_tol,
                )
                se = float(np.sqrt(max(var_loc, 0.0)))
                n_chunks = int(values.size)
            else:
                weights = 1.0 / np.maximum(variances, self.config.edge_variance_floor)
                value = float(np.sum(weights * values) / np.sum(weights))
                # Delta-method component plus disagreement across overlapping chunks.
                formal_var = float(1.0 / np.sum(weights))
                disagreement = (
                    float(np.average((values - value) ** 2, weights=weights))
                    if values.size > 1
                    else 0.0
                )
                se = float(np.sqrt(max(formal_var + disagreement / max(values.size, 1), 0.0)))
                n_chunks = int(values.size)
            if had_zero_chunk:
                zero_chunk_dates += 1
                if np.isfinite(value) and value > 0:
                    zero_masked_dates += 1
            rows.append(
                {
                    "series_id": series_id,
                    "pull_id": pull_id,
                    "historical_date": historical_date,
                    "value": value,
                    "calibration_se": se,
                    "n_contributing_chunks": n_chunks,
                    "had_zero_chunk": had_zero_chunk,
                }
            )
        full = pd.DataFrame(rows)

        if self.config.normalization != "none":
            bstart = pd.Timestamp(baseline_start).normalize() if baseline_start is not None else full["historical_date"].min()
            bend = pd.Timestamp(baseline_end).normalize() if baseline_end is not None else full["historical_date"].max()
            mask = full["historical_date"].between(bstart, bend)
            if not mask.any():
                raise ValueError("Baseline period has no observations")
            if self.config.normalization == "max_100":
                denom = float(full.loc[mask, "value"].max())
            else:
                denom = float(full.loc[mask, "value"].mean())
            if not np.isfinite(denom) or denom <= 0:
                raise ValueError("Normalization denominator is non-positive")
            factor = 100.0 / denom
            full["value"] *= factor
            full["calibration_se"] *= abs(factor)
            calibrated["calibrated_value"] *= factor
            diagnostics["normalization_factor"] = factor
            diagnostics["normalization_baseline_start"] = str(bstart.date())
            diagnostics["normalization_baseline_end"] = str(bend.date())
        else:
            diagnostics["normalization_factor"] = 1.0

        diagnostics.update(
            {
                "pull_id": pull_id,
                "series_id": series_id,
                "n_historical_dates": int(full["historical_date"].nunique()),
                "mean_contributing_chunks": float(full["n_contributing_chunks"].mean()),
                "zero_share_raw": float((frame["value"] == 0).mean()),
                "n_dates_with_zero_chunk": zero_chunk_dates,
                "n_dates_zero_masked_by_aggregation": zero_masked_dates,
                "zero_masked_share": (
                    zero_masked_dates / zero_chunk_dates if zero_chunk_dates else 0.0
                ),
            }
        )
        return CalibrationResult(
            pull_id=pull_id,
            series_id=series_id,
            full_series=full,
            calibrated_observations=calibrated,
            chunk_scales=scales,
            edges=edge_df,
            diagnostics=diagnostics,
        )
