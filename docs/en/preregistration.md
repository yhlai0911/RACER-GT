# Preregistration Protocol

Complete and freeze this document before the first confirmatory pull.

## Query definition

- Construct:
- Primary search term or Topic ID:
- Alternative definitions:
- Geography:
- Category:
- Search property:
- Language and timezone handling:
- Historical start date:
- Historical end date:

## Acquisition design

- Collection days: 0, 1, 2, 7, 14, 21, 30
- Streams:
- Technical replicates per day × stream cell:
- Execution-order randomization seed:
- Device/browser/account/cookie/IP configuration:
- Network interruption logging rule:

## Chunk design

- Window length:
- Step length:
- Minimum usable overlap:
- Pseudocount or zero-handling rule:
- Lower-frequency benchmark:

## Locked diagnostics

- Exact numeric-vector duplicate rule:
- Near-duplicate thresholds:
- Graph connectivity requirement:
- Maximum calibration residual:
- Minimum effective pull count:
- Detection reliability threshold:
- Level reliability threshold:
- Innovation reliability threshold:

## Decision rule

MONITOR results from days 0–2 may detect implementation failures but may not be used to remove non-identical pulls or alter formal thresholds. If the code, thresholds, stitching rule, or decision tree changes after viewing MONITOR results, the observations are pilot data and a new confirmatory day 0 is required.

Formal acceptance is evaluated only after the day-30 batch is complete and locked. The acceptance decision must not use downstream prices, returns, volatility, or statistical significance.

## Outputs to archive

- Raw responses and SHA-256 hashes
- Request manifest and query fingerprint
- Software environment and package version
- Calibration edges and offsets
- Exact and near-duplicate reports
- Consensus weights and effective pull count
- All decision gates and sensitivity estimators
