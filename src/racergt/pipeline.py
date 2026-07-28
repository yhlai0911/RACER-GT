from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from .audit import AuditResult, audit_raw_batch
from .benchmark import BenchmarkResult, temporal_benchmark
from .config import RacerGTConfig
from .consensus import (
    ConsensusResult,
    DesignWeightedResult,
    fit_design_weighted_consensus,
    fit_gls_consensus,
)
from .decision import DecisionResult, evaluate_batch
from .duplicates import DuplicateDiagnostics, diagnose_duplicates
from .gstudy import GStudyResult, run_all_gstudies
from .overlap import CalibrationResult, OverlapGraphCalibrator
from .reliability import ReliabilityResult, assess_reliability
from .schema import coerce_raw_chunks, wide_pull_matrix


@dataclass
class PipelineResult:
    config: RacerGTConfig
    audit: AuditResult
    calibrations: dict[str, CalibrationResult]
    complete_pulls: pd.DataFrame
    duplicate_diagnostics: DuplicateDiagnostics
    design_consensus: DesignWeightedResult
    consensus: ConsensusResult
    gstudies: dict[str, GStudyResult]
    reliability: ReliabilityResult
    benchmark: BenchmarkResult | None
    decision: DecisionResult

    @property
    def final_series(self) -> pd.DataFrame:
        if self.benchmark is not None:
            return self.benchmark.series.copy()
        return self.consensus.consensus.copy()

    def save(self, output_dir: str | Path) -> dict[str, Path]:
        output = Path(output_dir)
        output.mkdir(parents=True, exist_ok=True)
        paths: dict[str, Path] = {}
        paths["protocol"] = self.config.save_yaml(output / "protocol.lock.yaml")
        paths["audit"] = self.audit.save_json(output / "audit.json")
        complete_path = output / "complete_calibrated_pulls.csv"
        self.complete_pulls.to_csv(complete_path, index=False)
        paths["complete_pulls"] = complete_path

        cal_dir = output / "calibration"
        cal_dir.mkdir(exist_ok=True)
        cal_summary = []
        for pull_id, result in self.calibrations.items():
            result.full_series.to_csv(cal_dir / f"{pull_id}_series.csv", index=False)
            result.chunk_scales.to_csv(cal_dir / f"{pull_id}_chunk_scales.csv", index=False)
            result.edges.to_csv(cal_dir / f"{pull_id}_overlap_edges.csv", index=False)
            cal_summary.append(result.diagnostics)
        cal_summary_path = cal_dir / "calibration_summary.json"
        cal_summary_path.write_text(json.dumps(cal_summary, indent=2, default=str), encoding="utf-8")
        paths["calibration_summary"] = cal_summary_path

        self.duplicate_diagnostics.save(output / "duplicates")
        self.design_consensus.save(output / "consensus")
        self.consensus.save(output / "consensus")
        for result in self.gstudies.values():
            result.save(output / "gstudy")
        self.reliability.save(output / "reliability")
        if self.benchmark is not None:
            self.benchmark.save(output / "benchmark")
        self.decision.save(output / "decision")
        final_path = output / "RACER_GT_final_series.csv"
        self.final_series.to_csv(final_path, index=False)
        paths["final_series"] = final_path

        summary = {
            "protocol_hash": self.config.protocol_hash(),
            "decision_status": self.decision.status,
            "n_raw_pulls": self.consensus.diagnostics["n_raw_pulls"],
            "design_consensus": self.design_consensus.diagnostics,
            "n_unique_pulls": self.consensus.diagnostics["n_unique_pulls"],
            "spectral_effective_pulls": self.consensus.diagnostics["spectral_effective_pulls"],
            "gstudy_coefficients": {
                name: result.coefficients for name, result in self.gstudies.items()
            },
            "reliability": self.reliability.summary,
            "benchmark": self.benchmark.diagnostics if self.benchmark else None,
        }
        summary_path = output / "summary.json"
        summary_path.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
        paths["summary"] = summary_path
        return paths


class RacerGTPipeline:
    """End-to-end implementation of the RACER-GT measurement protocol."""

    def __init__(self, config: RacerGTConfig):
        self.config = config

    def fit(
        self,
        raw_chunks: pd.DataFrame,
        benchmark: pd.DataFrame | None = None,
        stop_on_audit_error: bool = True,
    ) -> PipelineResult:
        audit = audit_raw_batch(raw_chunks, self.config)
        if stop_on_audit_error and not audit.passed:
            messages = "; ".join(issue.message for issue in audit.issues if issue.severity == "error")
            raise ValueError(f"Raw batch failed protocol audit: {messages}")
        data = coerce_raw_chunks(raw_chunks)
        metadata = data[
            ["pull_id", "collection_day", "stream_id", "replicate_id"]
        ].drop_duplicates("pull_id")

        calibrator = OverlapGraphCalibrator(
            self.config.calibration,
            min_overlap_days=self.config.chunking.min_overlap_days,
        )
        calibrations: dict[str, CalibrationResult] = {}
        full_frames = []
        for pull_id, group in data.groupby("pull_id", sort=True):
            result = calibrator.fit(
                group,
                baseline_start=self.config.query.baseline_start,
                baseline_end=self.config.query.baseline_end,
            )
            calibrations[str(pull_id)] = result
            meta = metadata[metadata["pull_id"] == str(pull_id)].iloc[0].to_dict()
            full = result.full_series.copy()
            for key in ["collection_day", "stream_id", "replicate_id"]:
                full[key] = meta[key]
            full_frames.append(full)
        complete = pd.concat(full_frames, ignore_index=True)
        matrix = wide_pull_matrix(complete)

        duplicate_diagnostics = diagnose_duplicates(
            matrix,
            self.config.duplicates,
            metadata=metadata,
        )
        design_consensus = fit_design_weighted_consensus(
            matrix,
            metadata=metadata,
            baseline_start=self.config.query.baseline_start,
            baseline_end=self.config.query.baseline_end,
        )
        # The calibration stage already produced a per-day standard error for every
        # pull. Until now it was written to disk and dropped; passing it here lets the
        # consensus report an independently derived lower bound alongside its own.
        consensus = fit_gls_consensus(
            matrix,
            self.config.consensus,
            metadata=metadata,
            baseline_start=self.config.query.baseline_start,
            baseline_end=self.config.query.baseline_end,
            calibration_se=wide_pull_matrix(complete, value_col="calibration_se"),
        )
        gstudies = run_all_gstudies(complete, self.config.gstudy)
        reliability = assess_reliability(
            matrix,
            metadata,
            self.config.consensus,
            baseline_start=self.config.query.baseline_start,
            baseline_end=self.config.query.baseline_end,
        )

        benchmark_result: BenchmarkResult | None = None
        if benchmark is not None and self.config.benchmark.enabled:
            benchmark_result = temporal_benchmark(
                consensus.consensus,
                benchmark,
                self.config.benchmark,
            )

        decision = evaluate_batch(
            self.config.decision,
            audit,
            [result.diagnostics for result in calibrations.values()],
            duplicate_diagnostics,
            consensus,
            gstudies,
            reliability,
            benchmark_result,
        )
        return PipelineResult(
            config=self.config,
            audit=audit,
            calibrations=calibrations,
            complete_pulls=complete,
            duplicate_diagnostics=duplicate_diagnostics,
            design_consensus=design_consensus,
            consensus=consensus,
            gstudies=gstudies,
            reliability=reliability,
            benchmark=benchmark_result,
            decision=decision,
        )
