# RACER-GT

**Randomized Acquisition, Calibration, Error Decomposition, and Reconstruction for Google Trends**

RACER-GT is a research-oriented Python package for constructing long-horizon daily Google Trends (GT) series from repeated, separately normalized retrievals. It is designed for financial econometrics, where a single 0–100 download, ad hoc chunk concatenation, or unexamined averaging of repeated pulls can create measurement error and misleading inference.

RACER-GT does **not** claim to recover absolute Google query counts. Its estimand is a **common-scale latent relative-search-interest signal** under a frozen query specification and explicit measurement assumptions.

## Core capabilities

- Balanced day × stream × technical-replicate acquisition design.
- Frozen request manifests and protocol hash locks.
- Global overlap-graph calibration of separately normalized chunks.
- Exact and residual near-duplicate diagnostics.
- Crossed-facet Generalizability Theory and D-study planning.
- Covariance-adjusted FGLS/convex consensus reconstruction.
- Weekly/monthly temporal benchmarking.
- Downstream attenuation diagnostics, SIMEX, and multiple-imputation regression.
- Reproducible simulation and real-GT-shape replay validation.

## Installation

```bash
python -m pip install . --no-build-isolation
```

Optional Playwright collector:

```bash
python -m pip install -e '.[collect]' --no-build-isolation
playwright install chromium
```

## Quick validation

```bash
python -m pytest -q
python examples/02_end_to_end_simulation.py
python examples/05_real_gt_replay_validation.py
```

Isolated local validation: **25 passed, 1 skipped**. The skipped test requires external Google Trends network access.

## Collection design example

```bash
racergt design --days 0,1,2,7,14,21,30 --streams A,B,C --replicates 2 --output collection_design.csv
racergt manifest --design collection_design.csv --keyword "gold price" --geo TW --historical-start 2010-01-01 --historical-end 2026-06-30 --window-days 180 --step-days 60 --output request_manifest.csv
```

## Documentation

- [English documentation](docs/en/)
- [繁體中文文件](docs/zh-TW/)
- [Traditional Chinese README](README_zh-TW.md)

## Interpretation limits

Different IP addresses are not treated as proof of independent Google samples. A stream is a composite collection environment unless its components are experimentally crossed. Exact duplicates remain in the audit archive and are collapsed only in the analytic information set. Reliability does not establish construct validity or causality.

## Citation

See `CITATION.cff`. Archive the raw pulls, package version, frozen protocol, query manifest, and all decision-gate outputs in substantive applications.
