# RACER-GT 0.1.0 release validation

Validation date: 2026-07-27

## Source tests

```text
.........                                                                [100%]
9 passed
```

Coverage of the current tests:

- collection schedule and chunk design;
- global overlap-graph calibration;
- exact-duplicate diagnostics;
- design-cell weighted reference estimator;
- covariance-adjusted consensus;
- crossed-facet G-study;
- temporal benchmark;
- measurement-error correction;
- end-to-end pipeline.

## Built-distribution test

The final wheel was installed into a fresh target directory with `--no-deps`, while dependencies were supplied by the validation runtime. The following public imports were verified:

```text
racergt.__version__ == 0.1.0
RacerGTConfig
RacerGTPipeline
fit_design_weighted_consensus
```

The installed CLI exposed:

```text
design, audit, run, simulate, export-stata
```

A full installed-wheel simulation completed successfully and returned `PASS`. It produced both:

- `consensus/design_weighted_consensus.csv`;
- `RACER_GT_final_series.csv`.

## Controlled Monte Carlo

Twenty replications are stored in `monte_carlo_results/replication_metrics.csv`. The summary is:

| Estimator | Mean RMSE | Mean correlation | Mean innovation correlation | Mean peak recall |
|---|---:|---:|---:|---:|
| Single pull | 7.230524 | 0.969502 | 0.886907 | 0.886842 |
| Cross-pull median | 4.170974 | 0.989829 | 0.955615 | 0.944737 |
| Simple mean | 3.725331 | 0.991879 | 0.974724 | 0.952632 |
| RACER-GT | 3.526473 | 0.992743 | 0.974451 | 0.952632 |

Under this particular DGP, RACER-GT reduces mean RMSE by approximately 51.2% relative to a single pull and 5.3% relative to a simple mean. It does not dominate the simple mean on every reported statistic: the mean innovation correlation is marginally lower, while peak recall is equal. These simulations are a controlled software/method check, not a universal performance guarantee.

## PDF preflight

- File: `paper/RACER_GT_Methodology_zh_TW.pdf`
- Pages: 31
- Page size: A4
- Encryption: none
- Embedded Traditional Chinese fonts render correctly in the validation renderer.
- All 31 pages were rendered to PNG after the final compilation; the title, equations, algorithm, module table, figures, and final reference page were visually inspected for clipping or broken glyphs.

## Interpretation limits

Passing these software checks does not validate a substantive keyword construct or prove an undisclosed Google sampling mechanism. Empirical use still requires a locked protocol, complete raw-response archive, construct-validity assessment, temporal-information alignment, and sensitivity analysis under the assumptions stated in the methodology manuscript.
