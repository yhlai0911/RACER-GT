"""Self-contained RACER-GT research core.

The public repository keeps the acquisition layer replaceable.  This module
implements the statistical core used by the examples: balanced design,
request-window planning, global overlap-graph calibration, duplicate-aware
consensus reconstruction, and reproducible GT-shaped stress simulation.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Iterable, Sequence

import networkx as nx
import numpy as np
import pandas as pd
from scipy.optimize import minimize
from sklearn.covariance import LedoitWolf


@dataclass(frozen=True)
class CalibrationResult:
    reconstructed: pd.DataFrame
    offsets: pd.DataFrame
    edge_diagnostics: pd.DataFrame
    connected: bool


@dataclass(frozen=True)
class ConsensusResult:
    series: pd.DataFrame
    weights: pd.DataFrame
    effective_pulls: float


def create_balanced_design(
    collection_days: Sequence[int] = (0, 1, 2, 7, 14, 21, 30),
    streams: Sequence[str] = ("A", "B", "C"),
    replicates: int = 2,
    *,
    seed: int = 20260727,
) -> pd.DataFrame:
    """Create a cyclically order-balanced day × stream × replicate design."""
    if replicates < 1 or len(streams) < 2:
        raise ValueError("replicates>=1 and at least two streams are required")
    rng = np.random.default_rng(seed)
    shift0 = int(rng.integers(0, len(streams)))
    rows: list[dict[str, object]] = []
    streams = list(streams)
    for di, day in enumerate(collection_days):
        shift = (shift0 + di) % len(streams)
        base = streams[shift:] + streams[:shift]
        for rep in range(1, replicates + 1):
            order = base if rep % 2 else list(reversed(base))
            for position, stream in enumerate(order, 1):
                rows.append({
                    "pull_id": f"D{day}_S{stream}_R{rep}",
                    "collection_day": day,
                    "stream": stream,
                    "replicate": rep,
                    "execution_order": position,
                    "design_seed": seed,
                })
    return pd.DataFrame(rows)


def create_chunk_windows(
    start: str | pd.Timestamp,
    end: str | pd.Timestamp,
    *,
    window_days: int = 180,
    step_days: int = 60,
) -> pd.DataFrame:
    """Create fixed inclusive date windows with overlap cycles."""
    start = pd.Timestamp(start).normalize(); end = pd.Timestamp(end).normalize()
    if end < start or step_days < 1 or window_days < 2:
        raise ValueError("invalid historical interval or window settings")
    rows=[]; cursor=start; j=0
    while cursor <= end:
        right=min(cursor+pd.Timedelta(days=window_days-1), end)
        rows.append({"chunk_id":f"C{j:03d}","window_start":cursor,"window_end":right})
        if right == end: break
        cursor += pd.Timedelta(days=step_days); j += 1
    return pd.DataFrame(rows)


def expand_request_manifest(
    design: pd.DataFrame,
    windows: pd.DataFrame,
    *, keyword: str,
    geo: str = "",
    category: int = 0,
    search_property: str = "web",
) -> pd.DataFrame:
    """Cross a frozen acquisition design with a fixed chunk plan."""
    out = design.merge(windows, how="cross")
    out["keyword"] = keyword; out["geo"] = geo
    out["category"] = int(category); out["search_property"] = search_property
    out["request_id"] = out["pull_id"] + "__" + out["chunk_id"]
    fingerprint = sha256(
        out[["keyword","geo","category","search_property","window_start","window_end"]]
        .astype(str).to_csv(index=False).encode()
    ).hexdigest()
    out["query_fingerprint"] = fingerprint
    return out


def _robust_edge(values: np.ndarray) -> tuple[float, float]:
    values = values[np.isfinite(values)]
    med=float(np.median(values))
    mad=float(1.4826*np.median(np.abs(values-med))) if values.size else np.nan
    variance=max((mad**2)/max(values.size,1),1e-8)
    return med, variance


def calibrate_overlap_graph(
    chunks: pd.DataFrame,
    *,
    pseudocount: float = 0.5,
    minimum_overlap: int = 14,
) -> CalibrationResult:
    """Jointly estimate all chunk offsets using weighted graph least squares.

    Required columns are pull_id, chunk_id, date, value.  Values must be on
    the Google Trends 0–100 scale.  A disconnected overlap graph raises a
    ValueError because a single common scale is not identified.
    """
    required={"pull_id","chunk_id","date","value"}
    if not required.issubset(chunks):
        raise ValueError(f"missing columns: {sorted(required-set(chunks.columns))}")
    df=chunks.copy(); df["date"]=pd.to_datetime(df["date"]).dt.normalize()
    df["value"]=pd.to_numeric(df["value"],errors="raise").astype(float)
    if ((df.value<0)|(df.value>100)).any(): raise ValueError("GT values must be in [0,100]")
    df["node"]=df["pull_id"].astype(str)+"::"+df["chunk_id"].astype(str)
    nodes=sorted(df.node.unique()); node_index={n:i for i,n in enumerate(nodes)}
    edges=[]
    grouped={n:g.set_index("date")["value"] for n,g in df.groupby("node")}
    for i,a in enumerate(nodes):
        pa,ca=a.split("::",1)
        for b in nodes[i+1:]:
            pb,cb=b.split("::",1)
            # within-pull overlaps and same-window cross-pull links
            if not (pa==pb or ca==cb): continue
            joined=pd.concat([grouped[a],grouped[b]],axis=1,join="inner").dropna()
            joined.columns=["a","b"]
            positive=joined[(joined.a>0)&(joined.b>0)]
            if len(positive)<minimum_overlap: continue
            ratio=np.log(positive.a+pseudocount)-np.log(positive.b+pseudocount)
            estimate,variance=_robust_edge(ratio.to_numpy())
            edges.append((a,b,estimate,variance,len(positive)))
    graph=nx.Graph(); graph.add_nodes_from(nodes); graph.add_edges_from((a,b) for a,b,*_ in edges)
    connected=nx.is_connected(graph) if nodes else False
    if not connected: raise ValueError("disconnected overlap graph: common scale is not identified")
    reference=nodes[0]; free=[n for n in nodes if n!=reference]; col={n:i for i,n in enumerate(free)}
    B=np.zeros((len(edges),len(free))); d=np.zeros(len(edges)); w=np.zeros(len(edges))
    for e,(a,b,estimate,variance,_) in enumerate(edges):
        if a!=reference: B[e,col[a]]=1.0
        if b!=reference: B[e,col[b]]=-1.0
        d[e]=estimate; w[e]=1.0/variance
    normal=B.T@(w[:,None]*B); rhs=B.T@(w*d)
    theta=np.linalg.solve(normal,rhs)
    offsets={reference:0.0,**{n:float(theta[col[n]]) for n in free}}
    df["offset"] = df.node.map(offsets)
    df["calibrated"]=(df.value+pseudocount)*np.exp(-df.offset)-pseudocount
    reconstructed=(df.groupby(["pull_id","date"],as_index=False)
        .agg(value=("calibrated","median"),contributing_chunks=("chunk_id","nunique")))
    residual=d-B@theta
    edge_frame=pd.DataFrame(edges,columns=["node_a","node_b","log_ratio","variance","n_overlap"])
    edge_frame["residual"]=residual
    offset_frame=pd.DataFrame({"node":nodes,"offset":[offsets[n] for n in nodes]})
    return CalibrationResult(reconstructed,offset_frame,edge_frame,True)


def exact_duplicate_groups(matrix: pd.DataFrame, decimals: int = 10) -> list[list[str]]:
    """Return groups of exactly equal pull vectors after canonical rounding."""
    groups: dict[str,list[str]]={}
    for col in matrix.columns:
        arr=np.round(matrix[col].to_numpy(float),decimals)
        key=sha256(np.nan_to_num(arr,nan=np.inf).astype("<f8").tobytes()).hexdigest()
        groups.setdefault(key,[]).append(str(col))
    return [g for g in groups.values() if len(g)>1]


def covariance_adjusted_consensus(reconstructed: pd.DataFrame) -> ConsensusResult:
    """Estimate a duplicate-aware, covariance-adjusted convex consensus."""
    matrix=reconstructed.pivot(index="date",columns="pull_id",values="value").sort_index()
    matrix=matrix.dropna(axis=0,how="any")
    # collapse exact duplicates analytically while retaining the archive outside this function
    representatives=[]
    seen=set()
    for col in matrix.columns:
        key=sha256(np.round(matrix[col].to_numpy(),10).astype("<f8").tobytes()).hexdigest()
        if key not in seen: representatives.append(col); seen.add(key)
    X=matrix[representatives]
    common=X.median(axis=1)
    offsets=(X.sub(common,axis=0)).median(axis=0)
    residual=X.sub(offsets,axis=1).sub(X.sub(offsets,axis=1).median(axis=1),axis=0)
    covariance=LedoitWolf().fit(residual.to_numpy()).covariance_
    p=len(representatives)
    def objective(w: np.ndarray)->float: return float(w@covariance@w)
    result=minimize(objective,np.full(p,1/p),method="SLSQP",bounds=[(0,1)]*p,
        constraints={"type":"eq","fun":lambda w:np.sum(w)-1},options={"ftol":1e-12,"maxiter":2000})
    if not result.success: raise RuntimeError(result.message)
    weights=result.x
    consensus=X.to_numpy()@weights
    eff=float(1.0/np.sum(weights**2))
    series=pd.DataFrame({"date":X.index,"consensus":consensus,"n_unique_pulls":p,"effective_pulls":eff})
    weight_frame=pd.DataFrame({"pull_id":representatives,"weight":weights})
    return ConsensusResult(series,weight_frame,eff)


def simulate_gt_chunks(
    *, n_dates: int = 365, n_pulls: int = 12, seed: int = 42,
    window_days: int = 120, step_days: int = 60,
) -> tuple[pd.DataFrame,pd.DataFrame]:
    """Generate GT-like separately normalized chunks with known latent truth."""
    rng=np.random.default_rng(seed); dates=pd.date_range("2020-01-01",periods=n_dates)
    innovation=rng.normal(0,0.7,n_dates); latent=np.zeros(n_dates)
    for t in range(1,n_dates): latent[t]=0.96*latent[t-1]+innovation[t]
    latent=25+5*np.sin(np.arange(n_dates)*2*np.pi/7)+latent
    for center in rng.choice(np.arange(20,n_dates-20),size=max(3,n_dates//100),replace=False):
        latent += 25*np.exp(-0.5*((np.arange(n_dates)-center)/3.0)**2)
    latent=np.clip(latent,0.1,None)
    windows=create_chunk_windows(dates.min(),dates.max(),window_days=window_days,step_days=step_days)
    rows=[]
    for p in range(n_pulls):
        stream_bias=(p%3-1)*0.8; shared=rng.normal(0,1.0,n_dates)
        pull_signal=np.clip(latent+stream_bias+0.4*shared+rng.normal(0,1.0,n_dates),0,None)
        for _,win in windows.iterrows():
            mask=(dates>=win.window_start)&(dates<=win.window_end); vals=pull_signal[mask]
            scaled=100*vals/max(vals.max(),1e-9); observed=np.clip(np.rint(scaled+rng.normal(0,0.8,len(vals))),0,100)
            for date,value in zip(dates[mask],observed,strict=True):
                rows.append({"pull_id":f"P{p:03d}","chunk_id":win.chunk_id,"date":date,"value":value})
    truth=pd.DataFrame({"date":dates,"latent":100*latent/latent.max()})
    return pd.DataFrame(rows),truth


def run_replay(seed: int = 42) -> dict[str,float]:
    """Run an end-to-end reproducible stress validation."""
    chunks,truth=simulate_gt_chunks(seed=seed)
    calibrated=calibrate_overlap_graph(chunks)
    consensus=covariance_adjusted_consensus(calibrated.reconstructed)
    merged=truth.merge(consensus.series,on="date")
    # align the arbitrary common scale before evaluating shape recovery
    scale=float(np.dot(merged.latent,merged.consensus)/np.dot(merged.consensus,merged.consensus))
    estimate=scale*merged.consensus.to_numpy(); target=merged.latent.to_numpy()
    return {
        "rmse":float(np.sqrt(np.mean((estimate-target)**2))),
        "mae":float(np.mean(np.abs(estimate-target))),
        "correlation":float(np.corrcoef(estimate,target)[0,1]),
        "effective_pulls":consensus.effective_pulls,
    }


def save_manifest_csv(manifest: pd.DataFrame, path: str | Path) -> None:
    Path(path).parent.mkdir(parents=True,exist_ok=True); manifest.to_csv(path,index=False)
