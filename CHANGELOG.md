# Changelog

## 1.3.0 - 2026-07-27

Answers the question the project had never asked: is this better than the
alternatives? Only one alternative could be compared directly, and the answer
there is no.

### Added

- `src/racergt/baselines.py` implements sequential stitching in the style of
  Bleher and Dimpfl's knitting -- the reassembly the applied literature usually
  performs, and the procedure failure mode F1 argues against. It reuses the same
  Huber edge estimator, the same minimum-value gate, and the same baseline
  normalization, so the only difference from the graph calibrator is that it
  walks a spanning path instead of solving all overlaps jointly. A test pins the
  two to agree exactly on noiseless data, so the comparison measures the design
  choice rather than an implementation gap.
- `examples/run_calibration_comparison.py` and `calibration_comparison/`. The
  mechanism F1 describes is real and now quantified: sequential stitching's
  recovered log scale grows in cross-replication spread by a factor of 4.75 from
  the start of the chain to the end, against 1.12 for the graph. The accuracy
  consequence is not: even at 17 joins with retrieval noise cut to a sixth --- the
  setting built to favour the graph --- the advantage is +0.0111 with p = 0.098
  and 21 wins out of 40. At the shortest chain the graph is significantly worse.
- A remark on why the collection day is the load-bearing facet, following
  Djorno et al. (2026) on the twenty-four-hour cache and midnight-UTC reset, with
  the prediction it implies for the technical-replicate variance component. The
  prediction is stated as testable, not assumed; no result depends on it.

### Changed

- Both manuscripts, both READMEs and the landing page now state plainly what has
  and has not been compared. Against a single download the improvement is large
  and robust (49.1%, 20/20). Against a simple cross-pull mean and against
  sequential stitching there is no detectable advantage. West (2020) and Djorno
  et al. (2026) are **not** compared, because an anchor bank needs several
  queries and a preprocessing pipeline evaluated on downstream forecasts does not
  fit a single-series latent-truth simulation. No accuracy claim is made against
  them.
- The cross-cutting conclusion is now stated as such. Three mechanisms have been
  tested directly -- covariance weighting, dependence heterogeneity, and graph
  calibration -- and all three behave as designed while leaving point accuracy
  essentially unchanged. The framework's value is that it produces a series whose
  quality can be judged, which is a different claim from producing a more
  accurate one, and the evidence now supports the former rather than the latter.

## 1.2.0 - 2026-07-27

Tests a prediction that 1.1.0 made and could not check, and reports that the
prediction fails.

### Fixed

- **1.1.0 claimed that the covariance adjustment should win once dependence is
  heterogeneous. It does not.** That claim was a conjecture offered to explain
  why the covariance-adjusted consensus showed no advantage over a simple mean;
  it was stated in the abstract of both manuscripts as though it were
  established. `examples/run_dependence_experiment.py` now places a subset of
  pulls behind a shared cache disturbance that cuts across collection days and
  streams, so the dependence is invisible to the design facets and recoverable
  only from the residual covariance. Across four scenarios and 20 replications
  each, GLS wins none of them significantly and is significantly worse in two.
  Both manuscripts now report the test instead of the conjecture.

### Added

- `examples/run_dependence_experiment.py` and `dependence_experiment/`, covering
  the shared-dependence dimension of the factorial Monte Carlo that the
  limitations section has been asking for since 1.0.0. It also carries two
  diagnostics that decide how the negative result should be read: the
  constraints are not responsible (the constrained, uncapped, and fully
  unrestricted solutions all reach 4.1752, identical to the digit, because the
  unrestricted solution already lies inside the feasible set), and the mechanism
  works as designed (weights correlate -0.562 with shared residual dependence,
  negative in all ten replications). What remains is the error in estimating
  Sigma from nine pulls, which exceeds the efficiency that exploiting the true
  structure buys -- the same failure mode that motivated Ledoit-Wolf shrinkage in
  the portfolio literature.
- `SimulationSettings.cache_cluster_fraction` and `cache_cluster_weight`. At
  zero they reproduce the previous behaviour byte-for-byte, so the headline
  Monte Carlo numbers are unchanged and the two experiments stay comparable.

### Changed

- The practical recommendation, not the theory. With Sigma known the GLS weights
  are still minimum-variance among linear unbiased estimators; that derivation
  depends on no simulation. What changes is the advice at the design sizes this
  paper recommends (21-42 pulls, a single year), where no detectable gain in
  point accuracy should be expected and a simple mean is an equally defensible
  primary choice. The diagnostic value is unaffected: the spectral effective
  pull count fell from 4.93 to 2.95 across the scenarios, correctly reporting
  that nine pulls had become worth about three.

## 1.1.0 - 2026-07-27

Acts on an external methodological review of 1.0.0. Two of the findings change
reported results, so this release supersedes the 1.0.0 Monte Carlo numbers
wherever they appear.

> **Protocol hashes change in this release.** `ConsensusConfig.center_pull_bias`
> has a new default, so every `protocol.lock.yaml` written by 1.0.0 will fail its
> hash check on load. Regenerate locked protocols from their source config with
> `save_yaml`. This is the reproducibility mechanism working as designed, not a
> defect.

### Fixed

- **The Monte Carlo comparison was not information-matched.** `final_series`
  returns the benchmarked series when a benchmark is available, but the three
  cross-pull baselines never received one, and in simulation the benchmark is
  generated from the latent truth. `validation.py` now evaluates every estimator
  twice, with and without the same benchmark, and reports paired tests and Monte
  Carlo standard errors. Under matched information sets the covariance-adjusted
  consensus shows **no detectable advantage over a simple mean** (−0.0167,
  p = 0.15). The manuscripts, READMEs, release validation record, and landing
  page now report that alongside the two findings that do favour the framework:
  aggregation cuts RMSE 49.1% against a single pull (20/20 replications) and
  temporal benchmarking adds about 0.22 more.
- **`center_pull_bias` subtracted a common constant, not a pull-specific bias.**
  After `baseline_rescale` every pull shares the same baseline mean, which forces
  the centring term to `100 - mean(daily medians)` for every pull. It shifted the
  whole consensus, violated `E(e_t)=0` in the consensus model, and degraded RMSE
  in all twenty replications. Now off by default; `pull_bias_cross_pull_sd` is
  reported so the degeneracy stays visible. Mean bias returns to machine
  precision (−0.1317 → +3.2e-17).
- **Three formulas in the mathematical appendix disagreed with the code**, in
  both languages: `E-rho^2`/`Phi` divided `sigma^2_TDS` by `n_d n_s n_r` instead
  of `n_d n_s` (which overstates G whenever `n_r > 1`, including the recommended
  42-pull design), the benchmark penalty was described as a second-difference
  operator when the implementation builds a first-difference one, and the
  lognormal correction was derived from the observation error's variance rather
  than the estimator's. A parametrized test in `tests/test_gstudy.py` now pins
  the coefficients to the documented formulas.
- `evaluate_batch` read upstream diagnostics with `.get(key, nan)`, so renaming a
  key upstream silently downgraded a batch from PASS to REVIEW. Keys are now
  named constants and a missing key raises.
- Missing residuals in covariance estimation were zero-filled, which shrinks
  variances and covariances toward zero and therefore overstates precision.
  Pairwise-complete moments are used instead.

### Changed

- Convergence is assessed by leave-one-out influence rather than by the last step
  of one arbitrary insertion order. `final_convergence_mae_100` is now the worst
  single-pull influence, which does not depend on which pull the metadata sort
  happened to place last; the sequential path is still reported.
- The single-pull Monte Carlo baseline is the mean over all pulls rather than a
  fixed first column, so it measures what downloading once should be expected to
  produce.
- Exact duplicates in the simulator are assigned at random among pulls retrieved
  earlier, instead of always to the last collection day, which previously
  confounded duplication with the design cell.
- The English manuscript gained a related-work subsection covering the GT
  measurement literature it had omitted, and both bibliographies now carry the
  union of the two: Fleiss, Kish, and Newey–West were used but uncited in the
  Chinese version; West, Bleher–Dimpfl, Cebrián–Domenech, Medeiros–Pires, Hölzl,
  and the Google documentation were absent from the English one.

### Added

- `scripts/make_figures.py` regenerates the manuscript figures from
  `monte_carlo_results/`. The figures were previously produced by hand, so
  nothing tied them to the published numbers.
- Diagnostics for zero handling: aggregating a zero chunk against a positive one
  yields a positive value, so a partly-zero date does not stay zero.
  `n_dates_with_zero_chunk` and `n_dates_zero_masked_by_aggregation` make that
  visible, and both manuscripts now state the behaviour rather than implying
  zeros always survive.
- An explicit statement of the two conditions bridging the retrieval-design
  expectation and the latent common-scale signal, which the unbiasedness
  propositions require but 1.0.0 left implicit.
- The known downward bias of the spectral effective pull count is documented:
  residuals are centred on the median of the pulls themselves, so the count falls
  below the nominal value even under independence (8.57 at m = 9).

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
