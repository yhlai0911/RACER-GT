"""Reproducible Google Trends collection and replay example.

The script first creates the confirmatory 42-pull design and a fixed overlapping
manifest.  Actual collection is intentionally adapter-neutral: export one CSV
per request_id through an authorized API or Google Trends Explore.  The replay
section tests the estimator without requiring network access.
"""
from pathlib import Path
from racergt import create_balanced_design, create_chunk_windows, expand_request_manifest, run_replay

out=Path("example_output"); out.mkdir(exist_ok=True)
design=create_balanced_design()
windows=create_chunk_windows("2010-01-01","2026-06-30",window_days=180,step_days=60)
manifest=expand_request_manifest(design,windows,keyword="gold price",geo="TW")
design.to_csv(out/"collection_design.csv",index=False)
manifest.to_csv(out/"request_manifest.csv",index=False)
print(f"planned pulls: {design.pull_id.nunique()}")
print(f"planned requests: {len(manifest)}")
print("replay validation:",run_replay(seed=42))
