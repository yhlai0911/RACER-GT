# Tutorial

## 1. Create the 42-pull design

```bash
racergt design --days 0,1,2,7,14,21,30 --streams A,B,C --replicates 2 --output collection_design.csv
```

## 2. Freeze the historical request manifest

```bash
racergt manifest --design collection_design.csv --keyword "gold price" --geo TW --historical-start 2010-01-01 --historical-end 2026-06-30 --window-days 180 --step-days 60 --output request_manifest.csv
```

Do not allow the historical end date, chunk plan, query definition, or software version to change across formal pulls.

## 3. Prepare the raw long-format table

Required columns:

```text
pull_id,chunk_id,date,value
```

Recommended audit columns:

```text
collection_day,stream,replicate,retrieved_at,keyword,geo,category,
search_property,is_partial,raw_response_hash,query_fingerprint
```

## 4. Calibrate and reconstruct

```python
import pandas as pd
from racergt import calibrate_overlap_graph, covariance_adjusted_consensus

raw = pd.read_csv("raw_chunks.csv")
calibration = calibrate_overlap_graph(raw)
consensus = covariance_adjusted_consensus(calibration.reconstructed)
consensus.series.to_csv("consensus.csv", index=False)
consensus.weights.to_csv("weights.csv", index=False)
```

## 5. Run replay validation

```bash
python examples/05_real_gt_replay_validation.py
```

The replay uses a known latent daily curve and GT-like separate normalization, rounding, retrieval noise, and repeated pulls. It validates the reconstruction mechanism; it is not evidence that any particular real keyword is valid.

## 6. Interpret results

- A disconnected overlap graph means the common scale is not identified.
- Exact duplicates remain in the audit archive.
- The effective number of pulls may be far below the nominal number.
- Reliability is not construct validity.
- A smoothed retrospective series must not be used as a real-time trading signal.
