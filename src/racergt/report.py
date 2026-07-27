from __future__ import annotations

import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from jinja2 import Template

from .pipeline import PipelineResult


REPORT_TEMPLATE = Template(
    r"""# RACER-GT Diagnostic Report

**Protocol hash:** `{{ protocol_hash }}`  
**Formal decision:** **{{ decision_status }}**

> The decision concerns reproducibility of the locked Google Trends measurement
> construction. It does not identify absolute Google search counts and does not, by
> itself, establish the substantive validity of the keyword or Topic.

## 1. Batch and calibration

| Quantity | Value |
|---|---:|
| Raw complete pulls | {{ n_raw_pulls }} |
| Unique numeric pulls | {{ n_unique_pulls }} |
| Exact duplicates collapsed analytically | {{ n_collapsed }} |
| Spectral effective pulls | {{ spectral_effective }} |
| Mean raw zero share | {{ zero_share }} |
| All overlap graphs connected | {{ all_connected }} |

![Final series](figures/final_series.png)

## 2. Consensus weighting

The consensus estimator uses a shrinkage estimate of the residual pull-error covariance.
Near-duplicate pulls are retained in the audit dataset; exact duplicates are collapsed for
estimation, and highly dependent non-identical pulls receive less total weight.

![Consensus weights](figures/consensus_weights.png)

## 3. Generalizability analysis

{% for name, coeff in gcoeff.items() %}
### {{ name|capitalize }}

- Generalizability coefficient: **{{ '%.4f'|format(coeff.generalizability_coefficient) }}**
- Dependability coefficient: **{{ '%.4f'|format(coeff.dependability_coefficient) }}**
- Relative error variance: {{ '%.6g'|format(coeff.relative_error_variance) }}
- Absolute error variance: {{ '%.6g'|format(coeff.absolute_error_variance) }}

![{{ name }} variance components](figures/gstudy_{{ name }}_components.png)
{% endfor %}

## 4. Detection, level, and innovation reliability

| Diagnostic | Value |
|---|---:|
{% for key, value in reliability.items() %}| {{ key }} | {{ value }} |
{% endfor %}

![Consensus convergence](figures/consensus_convergence.png)

## 5. Near-duplicate structure

- Exact duplicate groups: {{ exact_groups }}
- Dependence-connected components: {{ near_components }}
- Largest component share: {{ max_component_share }}

A connected component means that its members are linked by a chain of qualifying
near-duplicate edges. It does **not** imply that every pair inside the component satisfies
the rule.

## 6. Multi-frequency benchmarking

{% if benchmark %}
- Benchmark mode: {{ benchmark.mode }}
- Standardized benchmark RMSE: {{ benchmark.benchmark_standardized_rmse }}
- Mean absolute daily correction: {{ benchmark.mean_absolute_correction }}

![Benchmark residuals](figures/benchmark_residuals.png)
{% else %}
No lower-frequency benchmark was supplied. The final series therefore remains a
baseline-normalized cross-pull consensus rather than a frequency-benchmarked index.
{% endif %}

## 7. Pre-specified decision tree

{{ decision_table }}

## 8. Interpretation

A PASS result supports use of the constructed relative-search index under the locked
retrieval design and stated assumptions. It does not justify claims that different IP
addresses generate independent Google Trends samples. It also does not remove the need
for a separate construct-validity analysis, real-time vintage design, and downstream
measurement-error correction in financial regressions.
"""
)


def _save_final_series(result: PipelineResult, path: Path) -> None:
    data = result.final_series.copy()
    data["historical_date"] = pd.to_datetime(data["historical_date"])
    fig, ax = plt.subplots(figsize=(11, 4.8))
    ax.plot(data["historical_date"], data["value"], linewidth=1.0)
    if {"ci_lower_95", "ci_upper_95"}.issubset(data.columns):
        ax.fill_between(
            data["historical_date"], data["ci_lower_95"], data["ci_upper_95"], alpha=0.2
        )
    ax.set_title("RACER-GT final relative-search index")
    ax.set_xlabel("Historical date")
    ax.set_ylabel("Index")
    fig.tight_layout()
    fig.savefig(path, dpi=180)
    plt.close(fig)


def _save_weights(result: PipelineResult, path: Path) -> None:
    weights = result.consensus.weights.sort_values("weight", ascending=False)
    fig, ax = plt.subplots(figsize=(10, 4.8))
    ax.bar(weights["pull_id"].astype(str), weights["weight"])
    ax.set_title("Covariance-adjusted consensus weights")
    ax.set_xlabel("Unique pull")
    ax.set_ylabel("Weight")
    ax.tick_params(axis="x", rotation=90)
    fig.tight_layout()
    fig.savefig(path, dpi=180)
    plt.close(fig)


def _save_components(name: str, result: PipelineResult, path: Path) -> None:
    comp = result.gstudies[name].variance_components
    fig, ax = plt.subplots(figsize=(8, 4.8))
    ax.bar(comp["component"], comp["variance"])
    ax.set_title(f"{name.capitalize()} G-study variance components")
    ax.set_xlabel("Component")
    ax.set_ylabel("Estimated variance")
    fig.tight_layout()
    fig.savefig(path, dpi=180)
    plt.close(fig)


def _save_convergence(result: PipelineResult, path: Path) -> None:
    conv = result.reliability.convergence
    fig, ax = plt.subplots(figsize=(8, 4.8))
    if not conv.empty:
        ax.plot(conv["n_pulls"], conv["mae_100_from_previous"], marker="o")
    ax.set_title("Sequential consensus convergence")
    ax.set_xlabel("Number of pulls included")
    ax.set_ylabel("MAE from previous consensus / 100")
    fig.tight_layout()
    fig.savefig(path, dpi=180)
    plt.close(fig)


def _save_benchmark_residuals(result: PipelineResult, path: Path) -> None:
    fit = result.benchmark.benchmark_fit if result.benchmark is not None else pd.DataFrame()
    fig, ax = plt.subplots(figsize=(10, 4.8))
    if not fit.empty:
        x = np.arange(len(fit))
        ax.plot(x, fit["standardized_residual"], linewidth=0.8)
        ax.axhline(0.0, linewidth=0.8)
    ax.set_title("Lower-frequency benchmark standardized residuals")
    ax.set_xlabel("Benchmark period")
    ax.set_ylabel("Standardized residual")
    fig.tight_layout()
    fig.savefig(path, dpi=180)
    plt.close(fig)


def _markdown_table(frame: pd.DataFrame) -> str:
    if frame.empty:
        return "No rows."
    columns = ["rule_id", "observed", "threshold", "passed", "mandatory"]
    view = frame[[c for c in columns if c in frame.columns]].copy()
    header = "| " + " | ".join(view.columns) + " |"
    separator = "|" + "|".join(["---"] * len(view.columns)) + "|"
    rows = [
        "| " + " | ".join(str(value) for value in row) + " |"
        for row in view.itertuples(index=False, name=None)
    ]
    return "\n".join([header, separator, *rows])


def generate_diagnostic_report(result: PipelineResult, output_dir: str | Path) -> Path:
    output = Path(output_dir)
    figures = output / "figures"
    figures.mkdir(parents=True, exist_ok=True)
    _save_final_series(result, figures / "final_series.png")
    _save_weights(result, figures / "consensus_weights.png")
    for name in result.gstudies:
        _save_components(name, result, figures / f"gstudy_{name}_components.png")
    _save_convergence(result, figures / "consensus_convergence.png")
    if result.benchmark is not None:
        _save_benchmark_residuals(result, figures / "benchmark_residuals.png")

    reliability = {
        key: f"{value:.6g}" if isinstance(value, (float, np.floating)) else value
        for key, value in result.reliability.summary.items()
    }
    context = {
        "protocol_hash": result.config.protocol_hash(),
        "decision_status": result.decision.status,
        "n_raw_pulls": result.consensus.diagnostics["n_raw_pulls"],
        "n_unique_pulls": result.consensus.diagnostics["n_unique_pulls"],
        "n_collapsed": result.consensus.diagnostics["n_collapsed_exact_duplicates"],
        "spectral_effective": f"{result.consensus.diagnostics['spectral_effective_pulls']:.3f}",
        "zero_share": f"{result.audit.summary.get('zero_share', np.nan):.4f}",
        "all_connected": all(c.diagnostics.get("connected", False) for c in result.calibrations.values()),
        "gcoeff": {name: study.coefficients for name, study in result.gstudies.items()},
        "reliability": reliability,
        "exact_groups": len(result.duplicate_diagnostics.exact_groups),
        "near_components": len(result.duplicate_diagnostics.components),
        "max_component_share": result.duplicate_diagnostics.summary["max_component_share"],
        "benchmark": result.benchmark.diagnostics if result.benchmark else None,
        "decision_table": _markdown_table(result.decision.to_frame()),
    }
    report_path = output / "RACER_GT_diagnostic_report.md"
    report_path.write_text(REPORT_TEMPLATE.render(**context), encoding="utf-8")
    summary_path = output / "report_context.json"
    summary_path.write_text(json.dumps(context, indent=2, default=str), encoding="utf-8")
    return report_path
