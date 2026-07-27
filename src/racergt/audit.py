from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from .config import RacerGTConfig
from .design import generate_chunk_windows
from .schema import ValidationIssue, coerce_raw_chunks, validate_raw_chunks, vector_to_bytes


@dataclass
class AuditResult:
    protocol_hash: str
    passed: bool
    issues: list[ValidationIssue]
    summary: dict

    def to_dict(self) -> dict:
        return {
            "protocol_hash": self.protocol_hash,
            "passed": self.passed,
            "issues": [asdict(issue) for issue in self.issues],
            "summary": self.summary,
        }

    def save_json(self, path: str | Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2, default=str), encoding="utf-8")
        return path


def numeric_vector_hash(values: np.ndarray, decimals: int = 10) -> str:
    return hashlib.sha256(vector_to_bytes(values, decimals=decimals)).hexdigest()


def audit_raw_batch(df: pd.DataFrame, config: RacerGTConfig) -> AuditResult:
    issues = validate_raw_chunks(df)
    if any(issue.severity == "error" for issue in issues):
        return AuditResult(config.protocol_hash(), False, issues, {"n_rows": len(df)})

    data = coerce_raw_chunks(df)
    expected_chunks = generate_chunk_windows(
        config.query.historical_start,
        config.query.historical_end,
        config.chunking.window_days,
        config.chunking.step_days,
    )
    expected_map = expected_chunks.set_index("chunk_id")[["window_start", "window_end"]]

    # Historical endpoints must be fixed across all pulls.
    actual_endpoints = (
        data.groupby("pull_id")
        .agg(hist_min=("historical_date", "min"), hist_max=("historical_date", "max"))
        .reset_index()
    )
    wrong_start = actual_endpoints["hist_min"] != pd.Timestamp(config.query.historical_start)
    wrong_end = actual_endpoints["hist_max"] != pd.Timestamp(config.query.historical_end)
    if wrong_start.any() or wrong_end.any():
        issues.append(
            ValidationIssue(
                "error",
                "historical_window_drift",
                "At least one pull does not use the locked historical endpoints",
                int((wrong_start | wrong_end).sum()),
            )
        )

    declared = data[["chunk_id", "window_start", "window_end"]].drop_duplicates()
    bad_declared = 0
    unknown = set(declared["chunk_id"]).difference(expected_map.index)
    bad_declared += len(unknown)
    for row in declared.itertuples(index=False):
        if row.chunk_id in expected_map.index:
            expected = expected_map.loc[row.chunk_id]
            if row.window_start != expected["window_start"] or row.window_end != expected["window_end"]:
                bad_declared += 1
    if bad_declared:
        issues.append(
            ValidationIssue(
                "error",
                "chunk_definition_drift",
                "Observed chunk definitions differ from the locked protocol",
                bad_declared,
            )
        )

    expected_ids = set(expected_chunks["chunk_id"])
    missing_by_pull: dict[str, list[str]] = {}
    for pull_id, group in data.groupby("pull_id"):
        missing = sorted(expected_ids.difference(group["chunk_id"].unique()))
        if missing:
            missing_by_pull[str(pull_id)] = missing
    if missing_by_pull:
        issues.append(
            ValidationIssue(
                "error",
                "missing_chunks",
                f"Missing chunks in {len(missing_by_pull)} pulls",
                sum(len(v) for v in missing_by_pull.values()),
            )
        )

    spec_cols = {
        "keyword": config.query.keyword,
        "geo": config.query.geo,
        "category": config.query.category,
        "search_property": config.query.search_property,
        "language": config.query.language,
    }
    for col, expected in spec_cols.items():
        if col in data.columns:
            mismatch = data[col].astype(str) != str(expected)
            if mismatch.any():
                issues.append(
                    ValidationIssue(
                        "error",
                        f"query_spec_drift_{col}",
                        f"Column {col} differs from locked value {expected!r}",
                        int(mismatch.sum()),
                    )
                )

    if "protocol_hash" in data.columns:
        mismatch = data["protocol_hash"].astype(str) != config.protocol_hash()
        if mismatch.any():
            issues.append(
                ValidationIssue(
                    "error",
                    "protocol_hash_mismatch",
                    "Rows were collected under a different protocol hash",
                    int(mismatch.sum()),
                )
            )

    pull_meta = data[
        ["pull_id", "collection_day", "stream_id", "replicate_id"]
    ].drop_duplicates()
    ambiguous_meta = int(pull_meta.duplicated("pull_id", keep=False).sum())
    if ambiguous_meta:
        issues.append(
            ValidationIssue(
                "error",
                "ambiguous_pull_metadata",
                "A pull_id maps to more than one day/stream/replicate combination",
                ambiguous_meta,
            )
        )

    summary = {
        "n_rows": int(len(data)),
        "n_pulls": int(data["pull_id"].nunique()),
        "n_chunks": int(data["chunk_id"].nunique()),
        "n_dates": int(data["historical_date"].nunique()),
        "zero_share": float((data["value"] == 0).mean()),
        "missing_chunks_by_pull": missing_by_pull,
        "collection_days": sorted(data["collection_day"].unique().tolist()),
        "streams": sorted(data["stream_id"].unique().tolist()),
        "replicates": sorted(data["replicate_id"].unique().tolist()),
    }
    passed = not any(issue.severity == "error" for issue in issues)
    return AuditResult(config.protocol_hash(), passed, issues, summary)
