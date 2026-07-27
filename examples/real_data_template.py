"""Minimal real-data workflow after GT responses have been converted to RACER-GT format."""
from pathlib import Path

import pandas as pd

from racergt import RacerGTConfig, RacerGTPipeline
from racergt.report import generate_diagnostic_report

ROOT = Path(__file__).resolve().parents[1]
config = RacerGTConfig.load_yaml(ROOT / "examples" / "config_example.yaml")
raw = pd.read_csv("raw_chunks.csv")
benchmark = pd.read_csv("benchmark.csv")

result = RacerGTPipeline(config).fit(raw, benchmark=benchmark)
result.save("racergt_results")
generate_diagnostic_report(result, "racergt_results/report")

print("Decision:", result.decision.status)
print(result.final_series.tail())
