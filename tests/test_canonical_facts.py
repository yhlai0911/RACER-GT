"""The single-source-of-truth check works, and can fail.

Numbers and claims get copied across the manuscripts, the READMEs, the module
docstrings and the tickets. Numbers at least have something to grep for; a
retracted claim leaves nothing behind, and no test turns red when a stale copy
survives. That happened on 2026-07-28: the reading of an indefinite corrected
covariance was corrected in the code and in both manuscripts, and four stale
copies stayed behind, one of them in a README.

docs/canonical-facts.yaml registers the superseded wording so the copies become
detectable. A checker that cannot fail would restore exactly the problem it was
written for, so the last test plants one and requires a non-zero exit.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
FACTS_FILE = ROOT / "docs" / "canonical-facts.yaml"
CHECKER = ROOT / "scripts" / "check_facts.py"


def _run_checker() -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(CHECKER)],
        capture_output=True,
        text=True,
        cwd=ROOT,
        check=False,
    )


def test_facts_file_is_well_formed():
    spec = yaml.safe_load(FACTS_FILE.read_text(encoding="utf-8"))

    assert spec["facts"], "the facts list must not be empty"
    for fact in spec["facts"]:
        assert {"id", "value", "meaning", "source"} <= set(fact), fact.get("id")
        assert fact["value"], fact["id"]

    for claim in spec["retracted"]:
        assert {"id", "superseded_by", "reason", "patterns"} <= set(claim), claim.get("id")
        assert claim["patterns"], claim["id"]
        # A retraction with no allowed file would flag its own registration.
        assert "docs/canonical-facts.yaml" in claim.get("allowed_in", []), claim["id"]


def test_no_retracted_claim_survives_in_the_tree():
    result = _run_checker()
    assert result.returncode == 0, result.stdout + result.stderr


def test_the_checker_fails_on_a_planted_stale_claim(tmp_path):
    """Plant a superseded claim where the checker looks, and require it to fail.

    Written into review/, which the checker scans and git ignores. Removed in a
    finally block so a failure inside the assertion cannot leave it behind.
    """

    spec = yaml.safe_load(FACTS_FILE.read_text(encoding="utf-8"))
    claim = next(c for c in spec["retracted"] if c["patterns"])
    pattern = claim["patterns"][0]

    review = ROOT / "review"
    review.mkdir(exist_ok=True)
    planted = review / "_planted_stale_claim_for_test.md"
    planted.write_text(f"# planted\n\n{pattern}\n", encoding="utf-8")
    try:
        result = _run_checker()
        assert result.returncode != 0, "checker passed on a planted stale claim"
        assert claim["id"] in result.stdout
        assert planted.name in result.stdout
    finally:
        planted.unlink(missing_ok=True)

    # And the tree is clean again, so the plant did not leak into later tests.
    assert _run_checker().returncode == 0


@pytest.mark.parametrize(
    "fact_id",
    ["rounding_floor", "within_day_dispersion", "fitted_chunk_noise", "latent_log_sd"],
)
def test_traced_facts_actually_appear_somewhere(fact_id):
    """A fact nothing cites is either dead or misspelt; both are worth knowing."""

    spec = yaml.safe_load(FACTS_FILE.read_text(encoding="utf-8"))
    fact = next(f for f in spec["facts"] if f["id"] == fact_id)
    assert fact.get("track_occurrences", True), fact_id

    hits = 0
    for pattern in ("docs/latex/*.tex", "README*.md", "src/racergt/*.py", "review/**/*.md"):
        for path in ROOT.glob(pattern):
            if path.name == "canonical-facts.yaml" or not path.is_file():
                continue
            try:
                if fact["value"] in path.read_text(encoding="utf-8"):
                    hits += 1
            except (UnicodeDecodeError, OSError):
                continue
    assert hits > 0, f"{fact_id} ({fact['value']}) appears nowhere outside the facts file"
