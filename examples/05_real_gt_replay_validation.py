"""Reproducible GT-shaped replay validation.

This example does not scrape Google. It stress-tests RACER-GT on a latent daily
attention curve observed through repeated, separately normalized GT-like chunks.
Replace the simulated chunk table with authorized Google Trends CSV exports to
run the same pipeline on real pulls.
"""
from pathlib import Path
import json

from racergt import run_replay


def main() -> None:
    metrics = run_replay(seed=42)
    out = Path("results/replay")
    out.mkdir(parents=True, exist_ok=True)
    (out / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    print(json.dumps(metrics, indent=2))


if __name__ == "__main__":
    main()
