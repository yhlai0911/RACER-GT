# RACER-GT Python API reference

This document summarizes the stable public workflow in version 1.0.0. Lower-level functions remain available for methodological diagnostics but may evolve more quickly than the pipeline interface.

## Top-level API

```python
from racergt import (
    RacerGTConfig,
    DesignWeightedResult,
    fit_design_weighted_consensus,
    RacerGTPipeline,
    PipelineResult,
    generate_collection_schedule,
    generate_chunk_windows,
)
```

### `RacerGTConfig`

Pydantic model containing all locked query, design, chunking, calibration, duplicate, consensus, G-study, benchmark, and decision settings.

Key methods:

```python
cfg = RacerGTConfig.load_yaml("protocol.yaml")
cfg.save_yaml("protocol.lock.yaml")
digest = cfg.protocol_hash()
```

The hash is generated from canonicalized configuration content. It changes whenever a locked setting changes.

### `generate_chunk_windows(start, end, window_days, step_days)`

Returns a fixed overlapping chunk manifest with `chunk_id`, `window_start`, `window_end`, and `n_calendar_days`.

### `generate_collection_schedule(config, anchor_date=None)`

Returns the balanced day × stream × replicate schedule, including stream order, planned time slot, deterministic chunk order, fixed historical endpoints, and protocol hash.

### `RacerGTPipeline(config).fit(raw, benchmark=None)`

Runs the full measurement pipeline:

1. protocol audit;
2. within-pull overlap-graph calibration;
3. design-cell weighted reference estimator;
4. exact and near-duplicate diagnostics;
5. G-studies;
6. covariance-adjusted consensus;
7. temporal benchmark, when supplied;
8. reliability and convergence diagnostics;
9. locked decision tree.

The result is a `PipelineResult`.

### `PipelineResult`

Important attributes:

- `final_series`: final daily indicator, conditional standard error, and interval;
- `calibrations`: per-pull graph-calibration results;
- `duplicate_diagnostics`: exact and near-duplicate diagnostics;
- `gstudies`: `level`, `detection`, and `innovation` G-study results;
- `design_consensus`: pre-specified design-cell mixture reference estimator;
- `consensus`: GLS/minimum-variance consensus object;
- `benchmark`: temporal-benchmark result or `None`;
- `reliability`: pairwise, day/stream, and convergence diagnostics;
- `decision`: PASS/REVIEW/FAIL result;
- `audit`: protocol-integrity audit.

```python
result = RacerGTPipeline(cfg).fit(raw, benchmark)
result.save("results")
print(result.decision.status)
```

## Within-pull calibration

```python
from racergt.overlap import OverlapGraphCalibrator, huber_location
```

### `OverlapGraphCalibrator.fit(data, baseline_start=None, baseline_end=None)`

Expects exactly one `series_id` and one `pull_id`. It estimates robust overlap edges, verifies graph connectivity, solves relative log scales by graph WLS, calibrates all chunks, aggregates overlapping daily observations, and normalizes the specified baseline.

Returns `CalibrationResult` with:

- `full_series`;
- `calibrated_observations`;
- `chunk_scales`;
- `edges`;
- `diagnostics`.

## Duplicate and dependence diagnostics

```python
from racergt.duplicates import diagnose_duplicates
```

`diagnose_duplicates(matrix, config, metadata=None)` retains exact-vector multiplicity, computes raw and residual pair metrics, and builds the value-anchored near-duplicate graph. Connected components are diagnostic connectivity sets; they do not imply that every pair within a component passes the rule.

## Generalizability Theory

```python
from racergt.gstudy import run_gstudy, run_all_gstudies
```

`run_gstudy(data, transformation, config)` supports:

- `level`;
- `detection` = `I(value > 0)`;
- `innovation` = `Delta log(1 + value)`.

The balanced model decomposes T, D, S, TD, TS, DS, TDS, and E components. When there is one technical replicate, E cannot be separated and is retained in TDS. The returned `GStudyResult` includes ANOVA tables, variance components, G/Phi, D-study, optional block bootstrap, and diagnostics.

## Design-weighted reference estimator

```python
from racergt.consensus import fit_design_weighted_consensus
```

`fit_design_weighted_consensus(matrix, metadata, ...)` first averages completed pulls within each pre-specified design cell and then combines cell means with fixed target weights. The default uses equal weights across observed collection-day × stream cells. This implements the finite-mixture estimand in the methodology manuscript and exposes cell coverage, cell means, and weights. It is a transparent design-based reference, not a claim that repeated pulls are independent.

## Consensus estimator

```python
from racergt.consensus import fit_gls_consensus
```

`fit_gls_consensus(matrix, config, metadata=None, baseline_start=None, baseline_end=None)` collapses exact vectors analytically, aligns pull-level offsets, estimates residual covariance, and solves unrestricted GLS or the configured nonnegative/capped minimum-variance problem.

Outputs include weights, covariance, residuals, spectral/Kish effective pull counts, consensus values, and conditional uncertainty.

## Temporal benchmarking

```python
from racergt.benchmark import temporal_benchmark
```

The lower-frequency table must contain `period_start`, `period_end`, and `value`; `se` is optional. `soft` mode treats lower-frequency values as noisy measurements. `exact` mode imposes aggregate equality through a KKT system.

## Downstream measurement-error methods

```python
from racergt.eiv import reliability_corrected_ols, simex_ols
```

### `reliability_corrected_ols(...)`

Implements the moment correction

```text
beta = W'MY / [W'MW - tr(M Omega_u)]
```

and reports HAC uncertainty. It raises an error when the corrected denominator is non-positive.

### `simex_ols(...)`

Adds known/estimated measurement noise at a grid of lambda values, averages repeated estimates, fits the configured extrapolation, and evaluates the curve at lambda = -1.

## Simulation and validation

```python
from racergt.simulation import SimulationSettings, simulate_racergt_data
from racergt.validation import run_monte_carlo
```

The controlled DGP includes latent dynamics, collection-day/stream effects, correlated retrieval error, independently normalized chunks, rounding/zeros, and optional exact duplicates. The validation module compares single pull, cross-pull mean, median, and RACER-GT against the known latent truth.

## File I/O

```python
from racergt.io import read_table, write_table
```

Supported read formats: CSV, Parquet, XLS/XLSX. Supported write formats: CSV, Parquet, XLSX, and Stata 118 `.dta`.
