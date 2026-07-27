# RACER-GT 0.1.0 release notes

Release date: 2026-07-27

## Scope

This is a research-software release for constructing a common-scale, long-horizon daily Google Trends relative-search-interest index from repeated, separately normalized retrievals. It does not estimate absolute Google search counts and does not assume that different IP addresses produce independent samples.

## Included

- Locked protocol and balanced collection schedule generator.
- Raw-batch integrity audit and immutable protocol hash.
- Robust global overlap-graph calibration for each complete pull.
- Exact-duplicate audit and residual near-duplicate dependence graph.
- Crossed-facet Generalizability Theory for level, detection, and innovation.
- Pre-specified design-cell weighted reference estimator.
- Covariance-adjusted GLS / constrained minimum-variance consensus.
- Weekly/monthly temporal benchmarking.
- Pre-specified PASS / REVIEW / FAIL decision tree.
- Reliability-corrected OLS and SIMEX for downstream measurement error.
- CLI, Python API, Stata 118 export, tests, examples, and Monte Carlo validation.
- 31-page Traditional Chinese methodology manuscript with derivations and proofs.

## Verification performed for this release

- Nine unit/integration tests pass.
- Wheel installation and CLI import verified from an isolated target directory.
- Full CLI simulation completes and returns PASS under its controlled DGP.
- Twenty-replication Monte Carlo files are included.
- PDF rendered and visually inspected after final compilation.

## Known limitations

- The statistical pipeline is ingestion-first and intentionally does not embed an unofficial Google Trends scraper.
- Strict unbiasedness/efficiency claims are conditional on the assumptions stated in the manuscript.
- Version 0.1.0 uses balanced method-of-moments G-study components; REML is a planned extension for unbalanced designs.
- Consensus confidence intervals are conditional approximations; full-pipeline block bootstrap is recommended for confirmatory inference.
- Anchor-bank calibration across different queries is documented as an extension but is not implemented in 0.1.0.
