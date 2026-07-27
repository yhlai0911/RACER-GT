"""RACER-GT: reproducible measurement construction for Google Trends."""

from .config import RacerGTConfig
from .consensus import DesignWeightedResult, fit_design_weighted_consensus
from .design import generate_chunk_windows, generate_collection_schedule
from .pipeline import PipelineResult, RacerGTPipeline

__all__ = [
    "DesignWeightedResult",
    "PipelineResult",
    "RacerGTConfig",
    "RacerGTPipeline",
    "fit_design_weighted_consensus",
    "generate_chunk_windows",
    "generate_collection_schedule",
]

__version__ = "1.0.0"
