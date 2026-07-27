# RACER-GT Methodology

## Scope and estimand

RACER-GT reconstructs a common-scale latent relative-search-interest signal from repeated Google Trends retrievals. It does not identify absolute query counts. Let the latent search intensity be \(Q_t>0\). A retrieval-specific latent measurement is

\[
Z_{pct}=\kappa_{pc}Q_t\exp(x_p'\beta_t+u_{pct}),
\]

where \(p\) indexes a complete pull, \(c\) a separately normalized chunk, \(\kappa_{pc}\) the unknown chunk scale, and \(u_{pct}\) retrieval noise. The target is \(X_t=aQ_t\), a latent signal on an arbitrary but common relative scale under a frozen query protocol.

## Randomized acquisition design

The preferred confirmatory design is 7 collection days × 3 fixed streams × 2 technical replicates. Execution order and time slots are balanced so that stream effects are not confounded with order. A stream is a composite environment and is not interpreted as an IP effect without a separate crossover design.

## Global overlap-graph calibration

For overlapping chunks \(j,k\):

\[
r_{jkt}=\log(Y_{jt}+c)-\log(Y_{kt}+c)=\lambda_j-\lambda_k+\nu_{jkt}.
\]

Robust edge locations form \(\hat d=B\lambda+\nu\). RACER-GT estimates

\[
\hat\lambda=\arg\min_{\lambda:\lambda_1=0}(\hat d-B\lambda)'W(\hat d-B\lambda).
\]

Relative scales are identified if and only if the overlap graph is connected. Under conditional mean-zero edge errors, WLS is unbiased on the normalized subspace; inverse-covariance weighting is efficient among linear unbiased estimators.

## Duplicate and dependence diagnostics

Exact vectors remain in the audit archive but count once in the analytic information set. Near-duplicate detection is based on residual similarity after removing the common historical signal, not merely on raw-series correlation. Connected components are dependence diagnostics and need not be cliques.

## Generalizability Theory

With historical date \(t\) as the object of measurement and collection day \(d\), stream \(s\), and replicate \(r\) as facets:

\[
Y_{tdsr}=\mu+T_t+D_d+S_s+(TD)_{td}+(TS)_{ts}+\cdots+\varepsilon_{tdsr}.
\]

A D-study coefficient is

\[
G=\frac{\sigma_T^2}{\sigma_T^2+\sigma_{TD}^2/n_D+\sigma_{TS}^2/n_S+\sigma_{TDS}^2/(n_Dn_S)+\sigma_\varepsilon^2/(n_Dn_Sn_R)}.
\]

Separate studies are conducted for level, daily innovation, and zero/nonzero detection.

## Design-balanced covariance-adjusted consensus

For calibrated measurements \(y_t\), estimate \(\theta_t=w'y_t\) under \(1'w=1\) and \(H'w=0\), where \(H\) contains centered acquisition-facet contrasts. The minimum-variance solution is

\[
w^*=\Sigma^{-1}C(C'\Sigma^{-1}C)^{-1}c.
\]

The software uses a feasible shrinkage estimate of \(\Sigma\) and reports mean and median sensitivity estimators.

## Temporal benchmarking

Daily estimates may be softly aligned to a weekly or monthly benchmark:

\[
\hat x=(Q+A'WA)^{-1}(Qz+A'Wb).
\]

Exact benchmarking is justified only when the lower-frequency series is treated as authoritative.

## Downstream measurement error

If \(W_t=X_t+u_t\), classical measurement error attenuates OLS:

\[
\operatorname{plim}\hat\beta_{OLS}=\beta\frac{\sigma_X^2}{\sigma_X^2+\sigma_u^2}.
\]

RACER-GT supplies attenuation diagnostics, SIMEX, and multiple-imputation regression with HAC inference.

## Limitations

A measurement-protocol PASS does not establish construct validity, causality, real-time tradability, or universal estimator dominance. Any material rule change after pilot monitoring requires a new confirmatory batch.
