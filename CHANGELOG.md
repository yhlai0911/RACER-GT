# Changelog

## 1.0.0 - 2026-07-27

First stable release. The statistical pipeline is unchanged from 0.1.0: a
re-run of the twenty-replication Monte Carlo reproduces every published
figure to ten significant digits. It is not bit-for-bit identical, because
floating-point summation order in the linear-algebra backend varies between
runs; the residual disagreement appears at the eleventh significant digit and
is far below any reported precision. This release makes the project usable and
citable as an open academic platform.

### Fixed

- The methodology PDF could not be rebuilt from a clean checkout: the preamble
  required `DejaVu Sans Mono` and `Noto Sans Mono CJK TC`, neither of which is
  available from the same font set as the other four families. Both are now
  replaced by families the document already needs, so the build depends only on
  the five Noto families available on Linux CI.
- Removed a dead `pivot_table` computation in `gstudy._anova_and_components`
  whose result was discarded; the ANOVA array is built separately.

### Changed

- Ruff rule selection is now pinned explicitly (`E,F,W,I,UP,B,C4,RUF`) so a
  future ruff release cannot turn CI red by widening its defaults. The tree is
  lint-clean under that set and lint is enforced in CI.

### Added

- Continuous integration: test matrix on Python 3.10-3.13, lint gate,
  reproducible PDF build, and PyPI publication via trusted publishing.
- Bilingual (zh-TW / en) documentation set built from LaTeX to PDF.
- Open-source governance: CONTRIBUTING, CODE_OF_CONDUCT, SECURITY, Zenodo
  metadata for DOI minting, and issue/PR templates.

## 0.1.0 - 2026-07-27

- Initial research release.
- Balanced retrieval design and protocol locking.
- Global overlap-graph calibration with robust edge estimation.
- Exact-duplicate and residual near-duplicate diagnostics.
- Three-facet generalizability study and D-study.
- Design-cell weighted reference estimator and covariance-adjusted GLS consensus estimator.
- Multi-frequency temporal benchmarking.
- Reliability diagnostics, decision tree, simulation, CLI, and reports.
