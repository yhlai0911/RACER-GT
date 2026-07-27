# RACER-GT

**Randomized Acquisition, Calibration, Error Decomposition, and Reliability for Google Trends**

[![tests](https://github.com/yhlai0911/RACER-GT/actions/workflows/tests.yml/badge.svg)](https://github.com/yhlai0911/RACER-GT/actions/workflows/tests.yml)
[![docs](https://github.com/yhlai0911/RACER-GT/actions/workflows/docs.yml/badge.svg)](https://github.com/yhlai0911/RACER-GT/actions/workflows/docs.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12%20%7C%203.13-blue.svg)](pyproject.toml)

🇹🇼 [繁體中文版 README](README.zh-TW.md)

---

Google Trends rescales every request to 0–100, returns daily granularity only
for short windows, and can return different numbers for an identical query
repeated on a different day. Downloading a series once, stitching the windows
together, and treating the result as an observed variable imports four problems
into whatever model consumes it: compounding scale error, dependence
masquerading as replication, zero inflation at low volume, and attenuation bias
downstream.

RACER-GT treats acquisition as a **preregistered repeated-measurement
experiment** instead. It does not claim to recover Google's absolute search
counts — that quantity is not identified — and instead estimates two targets
that are: the expected GT return under a fixed query and retrieval design, and
the latent relative search signal on a common scale.

## What it actually does differently

| Common practice | RACER-GT |
|---|---|
| Stitch chunks sequentially, chaining each onto the last | Solve **all** chunk scales at once by weighted least squares on the overlap graph — no error accumulation, plus connectivity and cycle-consistency diagnostics |
| Download once | Balanced, protocol-locked repeated retrieval across collection days, streams, and replicates |
| Treat N retrievals as N samples | Estimate residual dependence and report **spectral and Kish effective pull counts**, which fall below N when retrievals are dependent |
| Delete duplicates | Retain them in the audit archive, collapse exact ones analytically, and expose near-duplicate clusters |
| One reliability number | Separate **detection**, **level**, and **daily-innovation** reliability, because they routinely disagree |
| Stop at construction | Propagate measurement uncertainty into reliability-corrected OLS and SIMEX |

## Install

```bash
pip install racergt
```

Requires Python 3.10+.

## 60-second start

```bash
# 1. Lock a protocol (SHA-256 hashed; hand-editing the lock file fails loudly)
racergt design examples/config_example.yaml --out protocol_bundle --anchor-date 2026-08-01

# 2. Collect per the generated schedule, convert to the documented long format

# 3. Audit against the locked protocol (exit 2 on failure)
racergt audit examples/config_example.yaml raw_chunks.csv --out audit.json

# 4. Run the pipeline (exit 3 if the decision tree returns FAIL)
racergt run examples/config_example.yaml raw_chunks.csv --benchmark weekly.csv --out results
```

No data yet? Generate a controlled dataset with known ground truth:

```bash
racergt simulate examples/config_example.yaml --out simulation --seed 42
```

```python
from racergt import RacerGTConfig, RacerGTPipeline
import pandas as pd

result = RacerGTPipeline(RacerGTConfig.load_yaml("config.yaml")).fit(
    pd.read_csv("raw_chunks.csv"), benchmark=pd.read_csv("weekly.csv")
)
print(result.decision.status)      # PASS / REVIEW / FAIL
result.save("results")
```

## Documentation

Every document exists in Traditional Chinese and English, built from LaTeX:

| Document | English | 繁體中文 |
|---|---|---|
| Methodology manuscript | [PDF](docs/pdf/RACER-GT-Methodology-en.pdf) | [PDF](docs/pdf/RACER-GT-Methodology-zh-TW.pdf) |
| Mathematical appendix | [PDF](docs/pdf/RACER-GT-Mathematical-Appendix-en.pdf) | [PDF](docs/pdf/RACER-GT-Mathematical-Appendix-zh-TW.pdf) |
| User guide | [PDF](docs/pdf/RACER-GT-User-Guide-en.pdf) | [PDF](docs/pdf/RACER-GT-User-Guide-zh-TW.pdf) |
| API reference | [PDF](docs/pdf/RACER-GT-API-Reference-en.pdf) | [PDF](docs/pdf/RACER-GT-API-Reference-zh-TW.pdf) |
| Protocol & preregistration template | [PDF](docs/pdf/RACER-GT-Protocol-and-Preregistration-en.pdf) | [PDF](docs/pdf/RACER-GT-Protocol-and-Preregistration-zh-TW.pdf) |

Sources are in `docs/latex/`; rebuild everything with `python scripts/build_docs.py`.

## Controlled Monte Carlo

Twenty replications against a known latent truth:

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

## What this does not claim

- It does not identify absolute Google search counts.
- Every unbiasedness, consistency, and minimum-variance result is conditional on
  assumptions stated explicitly in the methodology manuscript.
- PASS means the batch satisfies the locked measurement rules. It establishes
  neither construct validity for the keyword nor any causal interpretation.
- A static IP address is not evidence of an independent sample. `stream_id`
  denotes a composite environment; an estimated stream effect is not an IP
  effect without a crossover factorial design.
- The package embeds no Google Trends scraper, by design.

## Project layout

```
src/racergt/           core package
docs/latex/            bilingual LaTeX sources
docs/pdf/              built PDFs
examples/case_studies/ protocol-locked studies (no data — see its README)
monte_carlo_results/   per-replication simulation output
tests/                 unit and integration tests
```

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Changes to an estimator require a
statement of which proposition they affect, Monte Carlo evidence before and
after — including metrics that got worse — and a test that fails without the
change.

Methodological corrections are the most valuable contributions this project can
receive. Open an issue with the `methodology` label.

## Citation

See [CITATION.cff](CITATION.cff). Cite both the software release and the
accompanying methodology manuscript.

## License

MIT — see [LICENSE](LICENSE).
