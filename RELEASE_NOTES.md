# RACER-GT 1.0.0 release notes

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

## New in 1.0.0

- Bilingual document set: five documents in Traditional Chinese and English,
  built from LaTeX by `python scripts/build_docs.py`.
- English methodology manuscript aimed at journal submission.
- Continuous integration: tests on Python 3.10-3.13 plus macOS, a lint gate, a
  reproducible PDF build, and PyPI publication via trusted publishing.
- Open-source governance: CONTRIBUTING, CODE_OF_CONDUCT, SECURITY, an expanded
  CITATION.cff, and .zenodo.json for DOI minting.
- Five protocol-locked case studies (no data; see their README).
- `make checksums` generates the integrity manifest from `git ls-files`; it
  previously had no generator.

## Fixed

- The methodology PDF could not be rebuilt from a clean checkout because its
  preamble required two fonts unavailable from the same set as the others.
- A dead `pivot_table` computation in the G-study whose result was discarded.

## Verification performed for this release

- Nine unit/integration tests pass; ruff clean under an explicitly pinned rule set.
- All ten PDFs build in CI on a full TeX Live.
- Full CLI simulation completes and returns PASS under its controlled DGP.
- Twenty-replication Monte Carlo re-run reproduces every 0.1.0 figure to ten
  significant digits (not bit-for-bit; see RELEASE_VALIDATION.md).
- `twine check` passes on both distributions.

## Not verified

- **No real Google Trends data has been collected.** The five case studies are
  protocol-locked and data-free; the package embeds no collector by design.
- The `release` workflow has not yet been exercised; it triggers on a `v*` tag.

## Known limitations

- The statistical pipeline is ingestion-first and intentionally does not embed an unofficial Google Trends scraper.
- Strict unbiasedness/efficiency claims are conditional on the assumptions stated in the manuscript.
- Version 1.0.0 uses balanced method-of-moments G-study components; REML is a planned extension for unbalanced designs.
- Consensus confidence intervals are conditional approximations; full-pipeline block bootstrap is recommended for confirmatory inference.
- Anchor-bank calibration across different queries is documented as an extension but is not implemented in 1.0.0.
