# Protocol and Validation

## Confirmatory protocol

Before Day 0, freeze the construct, primary term/topic, alternative definitions, geo, category, search property, historical start/end, chunk plan, collection schedule, duplicate rules, reliability gates, consensus estimator, benchmark method, and stopping rule. Any material change after Day 0–2 monitoring reclassifies the observed data as pilot data and requires a new confirmatory Day 0.

## Required audit record

Preserve every raw retrieval, including exact duplicates. Record `request_id`, pull and chunk IDs, collection day, stream, replicate, execution order, retrieval time, actual returned dates, returned frequency, partial status, raw-response hash, numeric-vector hash, software version, and interruption log.

## Validation status

The development repository passed 25 tests with one live-network test skipped in the isolated environment. The public core includes unit tests for the balanced design, overlap plan, end-to-end calibration, covariance-adjusted consensus, and replay quality. GitHub Actions runs Python 3.10–3.13 and saves replay metrics as an artifact.

## Interpretation

A protocol PASS establishes only that pre-specified measurement-quality gates were met. It does not establish construct validity, causal identification, absence of historical revision, or real-time tradability.
