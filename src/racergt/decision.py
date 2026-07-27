from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .audit import AuditResult
from .benchmark import BenchmarkResult
from .config import DecisionThresholds
from .consensus import ConsensusResult
from .duplicates import DuplicateDiagnostics
from .gstudy import GStudyResult
from .reliability import ReliabilityResult


@dataclass
class DecisionRule:
    rule_id: str
    description: str
    observed: Any
    threshold: Any
    passed: bool | None
    mandatory: bool = True
    interpretation: str = ""


@dataclass
class DecisionResult:
    status: str
    rules: list[DecisionRule]
    summary: dict

    def to_frame(self) -> pd.DataFrame:
        return pd.DataFrame([asdict(rule) for rule in self.rules])

    def save(self, output_dir: str | Path) -> dict[str, Path]:
        output = Path(output_dir)
        output.mkdir(parents=True, exist_ok=True)
        csv_path = output / "acceptance_decision_tree.csv"
        json_path = output / "acceptance_decision.json"
        self.to_frame().to_csv(csv_path, index=False)
        json_path.write_text(
            json.dumps(
                {"status": self.status, "summary": self.summary, "rules": [asdict(r) for r in self.rules]},
                indent=2,
                default=str,
            ),
            encoding="utf-8",
        )
        return {"csv": csv_path, "json": json_path}


def _finite(value: Any) -> bool:
    try:
        return bool(np.isfinite(float(value)))
    except (TypeError, ValueError):
        return False


def evaluate_batch(
    thresholds: DecisionThresholds,
    audit: AuditResult,
    calibration_diagnostics: list[dict],
    duplicates: DuplicateDiagnostics,
    consensus: ConsensusResult,
    gstudies: dict[str, GStudyResult],
    reliability: ReliabilityResult,
    benchmark: BenchmarkResult | None = None,
) -> DecisionResult:
    rules: list[DecisionRule] = []

    rules.append(
        DecisionRule(
            "protocol_integrity",
            "All retrievals conform to the locked query, historical window, and chunk protocol.",
            audit.passed,
            True,
            audit.passed if thresholds.require_protocol_integrity else None,
            mandatory=thresholds.require_protocol_integrity,
        )
    )

    all_connected = all(bool(d.get("connected", False)) for d in calibration_diagnostics)
    rules.append(
        DecisionRule(
            "overlap_graph_connectivity",
            "Every complete pull has an identified connected overlap graph.",
            all_connected,
            True,
            all_connected if thresholds.require_connected_overlap_graphs else None,
            mandatory=thresholds.require_connected_overlap_graphs,
        )
    )

    n_unique = consensus.diagnostics["n_unique_pulls"]
    rules.append(
        DecisionRule(
            "minimum_unique_pulls",
            "The batch contains enough numerically distinct complete pulls.",
            n_unique,
            f">= {thresholds.min_unique_pulls}",
            n_unique >= thresholds.min_unique_pulls,
        )
    )

    spectral = consensus.diagnostics["spectral_effective_pulls"]
    rules.append(
        DecisionRule(
            "effective_pull_information",
            "Residual-correlation spectral effective pull count is adequate.",
            spectral,
            f">= {thresholds.min_spectral_effective_pulls}",
            spectral >= thresholds.min_spectral_effective_pulls if _finite(spectral) else None,
        )
    )

    zero_share = audit.summary.get("zero_share", np.nan)
    rules.append(
        DecisionRule(
            "zero_share",
            "The raw batch is not dominated by below-threshold zero observations.",
            zero_share,
            f"<= {thresholds.max_zero_share}",
            zero_share <= thresholds.max_zero_share if _finite(zero_share) else None,
        )
    )

    level_g = (
        gstudies.get("level").coefficients.get("generalizability_coefficient")
        if "level" in gstudies
        else np.nan
    )
    rules.append(
        DecisionRule(
            "level_generalizability",
            "Relative level rankings reproduce across collection days and streams.",
            level_g,
            f">= {thresholds.min_level_generalizability}",
            level_g >= thresholds.min_level_generalizability if _finite(level_g) else None,
        )
    )

    innovation_g = (
        gstudies.get("innovation").coefficients.get("generalizability_coefficient")
        if "innovation" in gstudies
        else np.nan
    )
    rules.append(
        DecisionRule(
            "innovation_generalizability",
            "Daily innovations reproduce across collection days and streams.",
            innovation_g,
            f">= {thresholds.min_innovation_generalizability}",
            innovation_g >= thresholds.min_innovation_generalizability
            if _finite(innovation_g)
            else None,
        )
    )

    kappa = reliability.summary.get("detection_fleiss_kappa", np.nan)
    detection_applicable = _finite(zero_share) and 0.0 < float(zero_share) < 1.0
    rules.append(
        DecisionRule(
            "detection_reliability",
            "Zero/nonzero detection agreement exceeds the pre-specified threshold.",
            kappa if detection_applicable else "not applicable: no detection variation",
            f">= {thresholds.min_detection_kappa}",
            (kappa >= thresholds.min_detection_kappa if _finite(kappa) else None)
            if detection_applicable
            else None,
            mandatory=detection_applicable,
            interpretation=(
                "Kappa is not identified when all observations share one detection category; "
                "the rule is then reported but does not determine batch acceptance."
            ),
        )
    )

    component_share = duplicates.summary.get("max_component_share", 0.0)
    rules.append(
        DecisionRule(
            "near_duplicate_concentration",
            "No dependence-connected component dominates the batch.",
            component_share,
            f"<= {thresholds.max_component_share}",
            component_share <= thresholds.max_component_share,
        )
    )

    convergence = reliability.summary.get("final_convergence_mae_100", np.nan)
    rules.append(
        DecisionRule(
            "consensus_convergence",
            "Adding the final pull changes the consensus by less than the locked tolerance.",
            convergence,
            f"<= {thresholds.max_convergence_mae_100}",
            convergence <= thresholds.max_convergence_mae_100 if _finite(convergence) else None,
        )
    )

    if benchmark is not None:
        srmse = benchmark.diagnostics.get("benchmark_standardized_rmse", np.nan)
        rules.append(
            DecisionRule(
                "frequency_consistency",
                "Daily consensus is compatible with lower-frequency benchmark measurements.",
                srmse,
                f"<= {thresholds.max_benchmark_standardized_rmse}",
                srmse <= thresholds.max_benchmark_standardized_rmse if _finite(srmse) else None,
            )
        )

    mandatory = [r for r in rules if r.mandatory]
    if any(r.passed is False for r in mandatory):
        status = "FAIL"
    elif any(r.passed is None for r in mandatory):
        status = "REVIEW"
    else:
        status = "PASS"
    summary = {
        "status": status,
        "n_rules": len(rules),
        "n_passed": sum(r.passed is True for r in rules),
        "n_failed": sum(r.passed is False for r in rules),
        "n_indeterminate": sum(r.passed is None for r in rules),
        "interpretation": (
            "PASS authorizes construction under the locked protocol; it does not prove "
            "that GT equals absolute Google search counts or establish construct validity."
        ),
    }
    return DecisionResult(status=status, rules=rules, summary=summary)
