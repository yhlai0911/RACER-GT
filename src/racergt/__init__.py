"""RACER-GT public API."""
from .core import (
    CalibrationResult,
    ConsensusResult,
    calibrate_overlap_graph,
    covariance_adjusted_consensus,
    create_balanced_design,
    create_chunk_windows,
    exact_duplicate_groups,
    expand_request_manifest,
    run_replay,
    save_manifest_csv,
    simulate_gt_chunks,
)

__version__ = "0.3.0"
__all__ = [
    "CalibrationResult", "ConsensusResult", "calibrate_overlap_graph",
    "covariance_adjusted_consensus", "create_balanced_design",
    "create_chunk_windows", "exact_duplicate_groups",
    "expand_request_manifest", "run_replay", "save_manifest_csv",
    "simulate_gt_chunks",
]
