# RACER-GT 1.0.0 release validation

Validation date: 2026-07-27

Every figure below was produced by running the stated command on the tagged
tree. Where a result differs from the 0.1.0 release, the difference is stated
rather than smoothed over.

## Source tests

```
PYTHONPATH=src pytest -q
.........                                                                [100%]
9 passed
```

Coverage: collection schedule and chunk design; global overlap-graph
calibration; exact-duplicate diagnostics; design-cell weighted reference
estimator; covariance-adjusted consensus; crossed-facet G-study; temporal
benchmark; measurement-error correction; end-to-end pipeline.

## Lint

```
ruff check src tests examples scripts
All checks passed!
```

The rule set is pinned explicitly in `pyproject.toml` (`E,F,W,I,UP,B,C4,RUF`)
rather than inherited from ruff's defaults, which widened between releases and
produced 45 violations on a previously clean tree. Two ignores are deliberate
and documented at their definition: `B008` (typer requires `Argument()` and
`Option()` calls in parameter defaults) and `W291` in `report.py` (two trailing
spaces are a Markdown hard line break; stripping them reflows the generated
report).

## Continuous integration

All workflows green on `main`:

- `tests` — pytest on Python 3.10, 3.11, 3.12, 3.13 (Ubuntu) and 3.12 (macOS),
  plus ruff and a CLI `simulate` smoke test asserting the pipeline still writes
  `RACER_GT_final_series.csv` and `consensus/design_weighted_consensus.csv`.
- `docs` — all ten PDFs built on a full TeX Live, with an explicit font-presence
  check and a minimum-page-count assertion.
- `release` — not yet exercised; it triggers on a `v*` tag.

The first `docs` run failed: `texlive-xetex` does not ship `xeCJK`, so all three
English documents built and all three Chinese ones failed. Fixed by installing
`texlive-lang-chinese` and adding a `kpsewhich` check so the failure reports
itself in one line.

## Documents

Ten documents, five in each language, all built by `python scripts/build_docs.py`
from sources in `docs/latex`:

| PDF | Pages |
|---|---:|
| `RACER-GT-Methodology-en.pdf` | 20 |
| `RACER-GT-Methodology-zh-TW.pdf` | 30 |
| `RACER-GT-Mathematical-Appendix-en.pdf` | 9 |
| `RACER-GT-Mathematical-Appendix-zh-TW.pdf` | 8 |
| `RACER-GT-User-Guide-en.pdf` | 8 |
| `RACER-GT-User-Guide-zh-TW.pdf` | 7 |
| `RACER-GT-API-Reference-en.pdf` | 6 |
| `RACER-GT-API-Reference-zh-TW.pdf` | 5 |
| `RACER-GT-Protocol-and-Preregistration-en.pdf` | 5 |
| `RACER-GT-Protocol-and-Preregistration-zh-TW.pdf` | 4 |

All A4 (595.28 × 841.89 pt), unencrypted, with Traditional Chinese and
mathematics rendering correctly under visual inspection.

### Correction to the 0.1.0 validation record

The 0.1.0 record reported a 31-page Chinese manuscript. That PDF could not be
rebuilt from a clean checkout: its preamble required `DejaVu Sans Mono` and
`Noto Sans Mono CJK TC`, neither of which is obtainable from the same font set
as the other four families, so the published PDF had been compiled on a machine
whose font state was not reproducible. Both are now replaced by families the
document already required. The text is unmodified; the manuscript is one page
shorter because the monospace font metrics changed.

The document set now depends only on five Noto families, all installable on
Linux CI via `fonts-noto-core` and `fonts-noto-cjk`.

## Controlled Monte Carlo

Twenty replications re-run on this tree (`examples/run_monte_carlo.py`):

| Estimator | Benchmark | RMSE | MCSE | Corr. | Innov. corr. | Peak recall |
|---|:--:|---:|---:|---:|---:|---:|
| Single pull | no | 7.3519 | 0.0573 | 0.9688 | 0.8878 | 0.8912 |
| Cross-pull median | no | 4.1710 | 0.0819 | 0.9898 | 0.9556 | 0.9447 |
| Simple mean | no | **3.7253** | 0.0877 | 0.9919 | **0.9747** | 0.9526 |
| RACER-GT | no | 3.7421 | 0.0894 | 0.9918 | 0.9743 | 0.9526 |
| Single pull | yes | 6.9881 | 0.0491 | 0.9717 | 0.8882 | 0.8947 |
| Cross-pull median | yes | 3.9584 | 0.0695 | 0.9908 | 0.9558 | 0.9474 |
| Simple mean | yes | **3.5058** | 0.0754 | **0.9928** | **0.9748** | **0.9553** |
| RACER-GT | yes | 3.5226 | 0.0770 | 0.9927 | 0.9745 | 0.9526 |

Every estimator is evaluated twice: on the calibrated pulls alone, and after
applying the **same** weekly/monthly benchmark. Comparing a benchmarked RACER-GT
against unbenchmarked baselines would confound the estimator with the extra
information, so both blocks are always reported. The single-pull row is the mean
over all pulls, not a fixed column.

Paired tests over the 20 replications (positive favours the first estimator):

| Comparison | Difference | p | Wins |
|---|---:|---:|:--:|
| RACER-GT vs single pull | +3.6098 | 2.4e-21 | 20/20 |
| RACER-GT vs cross-pull median | +0.4289 | 6.5e-12 | 20/20 |
| RACER-GT vs simple mean | −0.0167 | 0.152 | 7/20 |
| RACER-GT vs simple mean (both benchmarked) | −0.0168 | 0.116 | 7/20 |
| Benchmark gain, estimator fixed | +0.2194 | 3.1e-12 | 20/20 |

Three findings, two favourable and one not. Cross-pull aggregation cuts RMSE by
**49.1%** against a single pull (20/20 replications) and 10.3% against the
median. Temporal benchmarking adds about 0.22 more, and adds it almost
identically to RACER-GT and to the simple mean. Covariance-adjusted weighting,
however, shows **no detectable advantage over a simple mean** (p = 0.15). We
report that rather than only the favourable comparison: dependence in this DGP
is homogeneous, and GLS beats equal weights only when dependence strength varies
across pulls. This is one data-generating process, not a universal guarantee —
`examples/run_monte_carlo.py` reproduces it and `scripts/make_figures.py`
redraws the figures from the same CSVs.

### Reproducibility tolerance

The re-run reproduces every published 0.1.0 figure **to ten significant
digits**, not bit-for-bit. Example, RACER-GT mean RMSE:

```
0.1.0 published:  3.5264731591912244
1.0.0 re-run:     3.52647315907353
```

The disagreement appears at the eleventh significant digit and comes from
floating-point summation order in the linear-algebra backend, which varies
between runs. It is far below any reported precision. An earlier draft of the
1.0.0 changelog claimed bit-for-bit reproducibility; that claim was wrong and
has been corrected.

## Distributions

`python -m build` produces `racergt-1.0.0-py3-none-any.whl` and
`racergt-1.0.0.tar.gz`; `twine check` passes on both.

## Integrity manifest

`SHA256SUMS_PROJECT.txt` is generated by `make checksums` from `git ls-files`,
so the manifest cannot drift from the repository. The 0.1.0 manifest had no
generator and was produced by hand. All tracked files verify:

```
shasum -a 256 -c SHA256SUMS_PROJECT.txt
```

## Interpretation limits

Passing these software checks does not validate a substantive keyword construct
and does not prove anything about Google's undisclosed sampling mechanism.
Empirical use still requires a locked protocol, a complete raw-response archive,
construct-validity assessment, temporal-information alignment, and sensitivity
analysis under the assumptions stated in the methodology manuscript.

**No real Google Trends data has been collected or validated for this release.**
The five case studies in `examples/case_studies` are protocol-locked and
data-free by design; see that directory's README.
