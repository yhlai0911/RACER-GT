from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class QuerySpec(BaseModel):
    """Immutable query specification used by every retrieval in a locked batch."""

    model_config = ConfigDict(extra="forbid")

    series_id: str = "target"
    keyword: str
    geo: str = ""
    category: int = 0
    search_property: Literal["web", "news", "images", "youtube", "froogle"] = "web"
    language: str = "en-US"
    historical_start: date
    historical_end: date
    topic_or_term: Literal["term", "topic"] = "term"
    baseline_start: date | None = None
    baseline_end: date | None = None

    @model_validator(mode="after")
    def validate_dates(self) -> QuerySpec:
        if self.historical_end < self.historical_start:
            raise ValueError("historical_end must not precede historical_start")
        if self.baseline_start is None:
            self.baseline_start = self.historical_start
        if self.baseline_end is None:
            self.baseline_end = self.historical_end
        if self.baseline_end < self.baseline_start:
            raise ValueError("baseline_end must not precede baseline_start")
        if self.baseline_start < self.historical_start or self.baseline_end > self.historical_end:
            raise ValueError("baseline period must lie within the historical window")
        return self


class CollectionDesignConfig(BaseModel):
    """Balanced repeated-retrieval design."""

    model_config = ConfigDict(extra="forbid")

    day_offsets: list[int] = Field(default_factory=lambda: [0, 1, 2, 7, 14, 21, 30])
    streams: list[str] = Field(default_factory=lambda: ["A", "B", "C"])
    technical_replicates: int = 1
    time_slots: list[str] = Field(default_factory=lambda: ["09:00", "13:00", "17:00"])
    random_seed: int = 20260727
    balance_stream_order: bool = True
    balance_chunk_order: bool = True
    require_fixed_environment_within_stream: bool = True

    @field_validator("day_offsets")
    @classmethod
    def validate_offsets(cls, value: list[int]) -> list[int]:
        if not value or min(value) < 0:
            raise ValueError("day_offsets must be non-empty and non-negative")
        if len(set(value)) != len(value):
            raise ValueError("day_offsets must be unique")
        return sorted(value)

    @field_validator("streams")
    @classmethod
    def validate_streams(cls, value: list[str]) -> list[str]:
        if len(value) < 2:
            raise ValueError("at least two streams are required")
        if len(set(value)) != len(value):
            raise ValueError("stream labels must be unique")
        return value

    @field_validator("technical_replicates")
    @classmethod
    def validate_reps(cls, value: int) -> int:
        if value < 1:
            raise ValueError("technical_replicates must be at least 1")
        return value


class ChunkingConfig(BaseModel):
    """Fixed chunk windows used for every complete pull."""

    model_config = ConfigDict(extra="forbid")

    window_days: int = 180
    step_days: int = 15
    min_overlap_days: int = 14
    inclusive_end: bool = True

    @model_validator(mode="after")
    def validate_chunking(self) -> ChunkingConfig:
        if self.window_days < 30:
            raise ValueError("window_days must be at least 30")
        if self.step_days < 1 or self.step_days >= self.window_days:
            raise ValueError("step_days must be positive and smaller than window_days")
        if self.min_overlap_days < 2:
            raise ValueError("min_overlap_days must be at least 2")
        return self


class CalibrationConfig(BaseModel):
    """Global overlap-graph calibration settings."""

    model_config = ConfigDict(extra="forbid")

    min_value: float = 2.0
    huber_c: float = 1.345
    max_huber_iter: int = 100
    huber_tol: float = 1e-8
    edge_variance_floor: float = 1e-6
    max_edge_weight: float = 1e6
    reference_strategy: Literal["highest_degree", "first", "explicit"] = "highest_degree"
    explicit_reference_chunk: str | None = None
    lognormal_bias_correction: bool = True
    aggregation: Literal["inverse_variance", "median", "huber"] = "inverse_variance"
    normalization: Literal["baseline_mean_100", "max_100", "none"] = "baseline_mean_100"
    allow_disconnected: bool = False

    @model_validator(mode="after")
    def validate_reference(self) -> CalibrationConfig:
        if self.reference_strategy == "explicit" and not self.explicit_reference_chunk:
            raise ValueError("explicit_reference_chunk is required for explicit reference strategy")
        return self


class DuplicateConfig(BaseModel):
    """Exact- and near-duplicate diagnostic rules."""

    model_config = ConfigDict(extra="forbid")

    hash_decimals: int = 10
    exact_tolerance: float = 1e-10
    min_pair_observations: int = 30
    raw_correlation_threshold: float = 0.995
    residual_correlation_threshold: float = 0.95
    exact_cell_agreement_threshold: float = 0.90
    mae_100_threshold: float = 0.02
    positive_jaccard_threshold: float = 0.90
    use_residual_rule: bool = True


class ConsensusConfig(BaseModel):
    """Covariance-adjusted consensus estimator settings."""

    model_config = ConfigDict(extra="forbid")

    collapse_exact_duplicates: bool = True
    center_pull_bias: bool = True
    covariance: Literal["ledoit_wolf", "empirical", "diagonal"] = "ledoit_wolf"
    nonnegative_weights: bool = True
    weight_cap: float | None = 0.50
    local_uncertainty: bool = True
    baseline_rescale: bool = True

    @field_validator("weight_cap")
    @classmethod
    def validate_cap(cls, value: float | None) -> float | None:
        if value is not None and not (0 < value <= 1):
            raise ValueError("weight_cap must be in (0, 1]")
        return value


class GStudyConfig(BaseModel):
    """Generalizability-study and block-bootstrap settings."""

    model_config = ConfigDict(extra="forbid")

    clip_negative_components: bool = True
    bootstrap_replications: int = 0
    block_length: int = 28
    random_seed: int = 20260727
    transformations: list[Literal["level", "detection", "innovation"]] = Field(
        default_factory=lambda: ["level", "detection", "innovation"]
    )


class BenchmarkConfig(BaseModel):
    """Multi-frequency temporal-benchmarking settings."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    mode: Literal["soft", "exact"] = "soft"
    fidelity_weight: float = 1.0
    smoothness_weight: float = 10.0
    ridge: float = 1e-8
    default_benchmark_se: float = 2.0
    preserve_nonnegative: bool = True


class DecisionThresholds(BaseModel):
    """Pre-specified research thresholds; they are protocol choices, not universal constants."""

    model_config = ConfigDict(extra="forbid")

    min_unique_pulls: int = 12
    min_spectral_effective_pulls: float = 4.0
    max_zero_share: float = 0.80
    min_level_generalizability: float = 0.80
    min_innovation_generalizability: float = 0.70
    min_detection_kappa: float = 0.60
    max_component_share: float = 0.50
    max_convergence_mae_100: float = 0.02
    max_benchmark_standardized_rmse: float = 1.50
    require_connected_overlap_graphs: bool = True
    require_protocol_integrity: bool = True


class RacerGTConfig(BaseModel):
    """Top-level reproducible configuration."""

    model_config = ConfigDict(extra="forbid")

    query: QuerySpec
    design: CollectionDesignConfig = Field(default_factory=CollectionDesignConfig)
    chunking: ChunkingConfig = Field(default_factory=ChunkingConfig)
    calibration: CalibrationConfig = Field(default_factory=CalibrationConfig)
    duplicates: DuplicateConfig = Field(default_factory=DuplicateConfig)
    consensus: ConsensusConfig = Field(default_factory=ConsensusConfig)
    gstudy: GStudyConfig = Field(default_factory=GStudyConfig)
    benchmark: BenchmarkConfig = Field(default_factory=BenchmarkConfig)
    decision: DecisionThresholds = Field(default_factory=DecisionThresholds)

    def canonical_dict(self) -> dict:
        return self.model_dump(mode="json", exclude_none=False)

    def protocol_hash(self) -> str:
        payload = json.dumps(
            self.canonical_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    def save_yaml(self, path: str | Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = self.canonical_dict()
        payload["protocol_hash"] = self.protocol_hash()
        path.write_text(yaml.safe_dump(payload, sort_keys=False, allow_unicode=True), encoding="utf-8")
        return path

    @classmethod
    def load_yaml(cls, path: str | Path) -> RacerGTConfig:
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        expected_hash = raw.pop("protocol_hash", None)
        config = cls.model_validate(raw)
        if expected_hash is not None and expected_hash != config.protocol_hash():
            raise ValueError("protocol hash does not match the configuration contents")
        return config
