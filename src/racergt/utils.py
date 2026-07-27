"""Internal numerical utilities."""
from __future__ import annotations
import hashlib
from collections.abc import Iterable
import numpy as np
import pandas as pd

def stable_vector_hash(values: Iterable[float], decimals: int = 12) -> str:
    arr=np.asarray(list(values),dtype=float); arr=np.round(arr,decimals=decimals)
    encoded=np.where(np.isnan(arr),np.inf,arr).astype("<f8",copy=False).tobytes()
    return hashlib.sha256(encoded).hexdigest()

def robust_mad(x: np.ndarray, *, scale_to_sd: bool=True) -> float:
    x=np.asarray(x,dtype=float); x=x[np.isfinite(x)]
    if x.size==0: return np.nan
    mad=np.median(np.abs(x-np.median(x)))
    return float(1.4826*mad if scale_to_sd else mad)

def huber_location(x: np.ndarray,c: float=1.345,max_iter: int=100)->float:
    x=np.asarray(x,dtype=float); x=x[np.isfinite(x)]
    if x.size==0: return np.nan
    mu=float(np.median(x)); scale=robust_mad(x)
    if not np.isfinite(scale) or scale<=1e-12: return mu
    for _ in range(max_iter):
        r=(x-mu)/scale; w=np.ones_like(r); mask=np.abs(r)>c; w[mask]=c/np.abs(r[mask])
        new=float(np.sum(w*x)/np.sum(w))
        if abs(new-mu)<=1e-10*(1+abs(mu)): break
        mu=new
    return mu

def nrmse(a: np.ndarray,b: np.ndarray,scale: float|None=None)->float:
    a=np.asarray(a,float); b=np.asarray(b,float); mask=np.isfinite(a)&np.isfinite(b)
    if not np.any(mask): return np.nan
    err=np.sqrt(np.mean((a[mask]-b[mask])**2))
    if scale is None:
        q75,q25=np.percentile(b[mask],[75,25]); scale=max(float(q75-q25),float(np.std(b[mask])),1e-12)
    return float(err/scale)

def to_datetime_utc(series: pd.Series)->pd.Series:
    return pd.to_datetime(series,utc=True,errors="raise")

def nearest_positive_semidefinite(matrix: np.ndarray,epsilon: float=1e-10)->np.ndarray:
    a=np.asarray(matrix,float)
    if a.ndim!=2 or a.shape[0]!=a.shape[1]: raise ValueError("matrix must be square")
    a=(a+a.T)/2; values,vectors=np.linalg.eigh(a); values=np.maximum(values,epsilon)
    projected=(vectors*values)@vectors.T
    return (projected+projected.T)/2
