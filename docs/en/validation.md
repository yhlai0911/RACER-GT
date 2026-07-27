# Validation Report

## Scope

RACER-GT validation distinguishes software correctness, statistical recovery under known truth, and live data acquisition. A live Google Trends connection is not required to validate the statistical core.

## Automated tests

The repository test suite checks:

- 42-pull balanced design generation;
- overlapping window construction;
- graph connectivity and joint scale calibration;
- duplicate-aware covariance consensus;
- end-to-end latent-shape recovery.

Run:

```bash
python -m pytest -q
```

## Replay stress test

Run:

```bash
python examples/05_real_gt_replay_validation.py
```

The data-generating process creates a latent attention curve with weekly seasonality, persistent innovations, and event spikes. Each pull receives stream effects, shared retrieval errors, request-specific normalization, rounding, and additional noise. The evaluation rescales the reconstructed series only for comparing shape against the known latent truth.

Primary metrics are RMSE, MAE, correlation, and effective pull count. A high correlation alone is insufficient; calibration graph connectivity, residual edge errors, duplicate concentration, and weight concentration must also be examined.

## Current limitation

The repository contains a replay test rather than an embedded copyrighted or unstable live Google Trends dataset. For a substantive application, researchers must archive authorized raw CSV exports and run the same pipeline. A complete day-30 batch is required before formal acceptance.
