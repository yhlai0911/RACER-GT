# RACER-GT Methodology

## 1. Estimand

RACER-GT does not estimate absolute Google query counts. Let the latent relative-search signal be \(X_t>0\). For pull \(p\), chunk \(c\), and date \(t\), the latent pre-rounding measurement is

\[
Z_{pct}=\kappa_{pc}X_t\exp(x_p'\beta_t+u_{pct}),
\]

where \(\kappa_{pc}\) is a request-specific scale, \(x_p\) records collection-day, stream, replicate, and order, and \(u_{pct}\) is retrieval error. The observed Google Trends value is a rounded and censored 0–100 transformation of \(Z_{pct}\). Only a common relative scale is identified without an external absolute-count anchor.

## 2. Acquisition design

The recommended confirmatory design is

\[
7\text{ days}\times3\text{ streams}\times2\text{ technical replicates}=42\text{ pulls}.
\]

Collection days are 0, 1, 2, 7, 14, 21, and 30. Execution order is cyclically balanced. A stream is treated as a composite environment; a different IP address is not evidence of an independent Google sample.

## 3. Global overlap-graph calibration

For overlapping chunks \(j,k\), define

\[
r_{jkt}=\log(Y_{jt}+c)-\log(Y_{kt}+c)
       =\lambda_j-\lambda_k+\nu_{jkt}.
\]

Robust edge estimates are stacked as

\[
\hat d=B\lambda+\nu,
\]

and the scale offsets solve

\[
\hat\lambda=\arg\min_{\lambda:\lambda_1=0}
(\hat d-B\lambda)'W(\hat d-B\lambda).
\]

A connected overlap graph is required. Under conditional mean-zero edge errors, the relative scale estimator is unbiased on the identified subspace. Using all overlap edges avoids sequential error propagation.

## 4. Duplicate-aware consensus

After calibration, let \(z_t\) collect the repeated pull values for date \(t\). Exact numeric duplicates remain in the audit archive but are collapsed in the analytic information set. Let \(\Sigma\) be the residual covariance matrix. The minimum-variance linear unbiased consensus is

\[
\hat X_t=\frac{\mathbf1'\Sigma^{-1}z_t}{\mathbf1'\Sigma^{-1}\mathbf1}.
\]

The implementation uses covariance shrinkage and nonnegative convex weights for finite-sample stability. Consequently, its practical estimator is a stabilized feasible GLS estimator rather than an unconditional exact BLUE.

## 5. Generalizability Theory

Historical date is the object of measurement; collection day, stream, and technical replicate are measurement facets. A crossed random-effects model decomposes variation into signal and acquisition-related components. For \(n_D,n_S,n_R\) design levels, a relative-decision coefficient has the generic form

\[
G=\frac{\sigma_T^2}{\sigma_T^2+\sigma_{TD}^2/n_D+\sigma_{TS}^2/n_S+\sigma_{TDS}^2/(n_Dn_S)+\sigma_e^2/(n_Dn_Sn_R)}.
\]

D-study calculations determine whether additional days, streams, or technical replicates provide the greatest reliability gain.

## 6. Decision protocol

The formal batch is accepted only after the protocol, historical end date, chunk plan, query definition, software version, and thresholds are locked. Exact duplicates are reported, non-identical pulls are not removed merely for lowering reliability, and acceptance cannot depend on downstream financial significance.

## 7. Validation

Validation has three layers: unit and integration tests; Monte Carlo experiments with known latent truth; and replay tests that impose GT-like normalization, rounding, zero inflation, correlated retrieval errors, and duplicate concentration. A network-dependent live collector test is optional and must not be confused with the statistical validation of the reconstruction core.
