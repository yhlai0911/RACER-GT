from __future__ import annotations

from pathlib import Path

import pandas as pd


def read_table(path: str | Path) -> pd.DataFrame:
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return pd.read_csv(path)
    if suffix in {".parquet", ".pq"}:
        return pd.read_parquet(path)
    if suffix in {".xlsx", ".xls"}:
        return pd.read_excel(path)
    raise ValueError(f"Unsupported table format: {path.suffix}")


def write_table(data: pd.DataFrame, path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    suffix = path.suffix.lower()
    if suffix == ".csv":
        data.to_csv(path, index=False)
    elif suffix in {".parquet", ".pq"}:
        data.to_parquet(path, index=False)
    elif suffix == ".xlsx":
        data.to_excel(path, index=False)
    elif suffix == ".dta":
        safe = data.copy()
        for col in safe.select_dtypes(include=["datetime64[ns]", "datetimetz"]).columns:
            safe[col] = safe[col].dt.tz_localize(None)
        safe.to_stata(path, write_index=False, version=118)
    else:
        raise ValueError(f"Unsupported output format: {path.suffix}")
    return path
