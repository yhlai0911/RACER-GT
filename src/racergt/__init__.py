"""RACER-GT: reproducible measurement construction for Google Trends."""

from .config import RacerGTConfig
from .consensus import DesignWeightedResult, fit_design_weighted_consensus
from .design import generate_collection_schedule, generate_chunk_windows
from .pipeline import RacerGTPipeline, PipelineResult

__all__ = [
    "RacerGTConfig",
    "DesignWeightedResult",
    "fit_design_weighted_consensus",
    "RacerGTPipeline",
    "PipelineResult",
    "generate_collection_schedule",
    "generate_chunk_windows",
]

__version__ = "0.1.0"
