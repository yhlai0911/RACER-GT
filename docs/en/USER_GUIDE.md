# RACER-GT User Guide

## 1. Install

```bash
python -m pip install . --no-build-isolation
```

## 2. Generate the confirmatory design

```bash
racergt design --days 0,1,2,7,14,21,30 --streams A,B,C --replicates 2 --output collection_design.csv
```

This creates 42 complete-pull cells. Streams are composite collection environments; different IP addresses are not evidence of independent samples.

## 3. Freeze overlapping requests

```bash
racergt manifest --design collection_design.csv --keyword "gold price" --geo TW --historical-start 2010-01-01 --historical-end 2026-06-30 --window-days 180 --step-days 60 --output request_manifest.csv
```

Keep the historical endpoint, chunk plan, query definition, software version, and request order fixed across all collection dates.

## 4. Collect or import

Export one CSV for every `request_id` through an authorized API or Google Trends Explore. Preserve the raw file, retrieval timestamp, partial flag, frequency, and SHA-256 hash. Do not use financial outcomes to decide which pulls to retain.

The long table required by `fit` contains:

```text
pull_id, chunk_id, date, value
```

Additional design and audit metadata should be retained in the research archive.

## 5. Reconstruct

```bash
racergt fit --input collected_chunks.csv --output-dir results
```

Outputs include reconstructed pulls, graph offsets, edge residuals, the covariance-adjusted consensus, and pull weights.

## 6. Reproducible offline validation

```bash
racergt replay --seed 42 --output replay_metrics.json
python examples/gt_collection_example.py
```

The replay uses a known latent signal and injects separate chunk normalization, rounding, stream variation, and correlated retrieval noise. It validates software behavior; it does not claim that Google's undisclosed mechanism is identical to the simulation.
