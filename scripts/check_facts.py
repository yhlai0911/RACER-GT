"""Check the repeated numbers and the retracted claims against a single source.

Two checks, and the second is the one that earns its keep.

Occurrences: each fact in docs/canonical-facts.yaml is located across the tree, so
changing a value shows every file that has to follow instead of relying on memory
that "the simulator overstates by 4.5 times" lives in seven of them.

Retractions: a claim that has been superseded leaves no failing test behind. On
2026-07-28 the reading of an indefinite corrected covariance was corrected in the
code and both manuscripts while a stale copy survived in the module spec, and
nothing caught it. Registering the wording makes it catchable: any occurrence
outside the files that document the correction is an error and exits non-zero.

Usage:
    python scripts/check_facts.py            # report and fail on stale claims
    python scripts/check_facts.py --list     # also list every occurrence
"""

from __future__ import annotations

import argparse
import sys
from fnmatch import fnmatch
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
FACTS_FILE = ROOT / "docs" / "canonical-facts.yaml"

SEARCH_GLOBS = (
    "docs/latex/*.tex",
    "docs/*.md",
    "docs/*.html",
    "docs/agents/*.md",
    "README.md",
    "README.zh-TW.md",
    "CHANGELOG.md",
    "src/racergt/*.py",
    "tests/*.py",
    "examples/*.py",
    # review/ is gitignored but is where the tickets and specs live, and the stale
    # copy that motivated this check was in one of them.
    "review/*.md",
    "review/tickets/*.md",
)


def _searchable_files() -> list[Path]:
    seen: dict[Path, None] = {}
    for pattern in SEARCH_GLOBS:
        for path in sorted(ROOT.glob(pattern)):
            if path.is_file():
                seen.setdefault(path, None)
    return list(seen)


def _relative(path: Path) -> str:
    return str(path.relative_to(ROOT))


def _is_allowed(relative_path: str, allowed: list[str]) -> bool:
    return any(fnmatch(relative_path, pattern) for pattern in allowed)


def _find(paths: list[Path], needle: str) -> list[tuple[str, int, str]]:
    hits = []
    for path in paths:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (UnicodeDecodeError, OSError):
            continue
        for number, line in enumerate(lines, start=1):
            if needle in line:
                hits.append((_relative(path), number, line.strip()[:100]))
    return hits


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", action="store_true", help="list occurrences of each fact")
    args = parser.parse_args()

    spec = yaml.safe_load(FACTS_FILE.read_text(encoding="utf-8"))
    paths = _searchable_files()
    print(f"Scanning {len(paths)} files against {FACTS_FILE.relative_to(ROOT)}\n")

    print("Facts")
    for fact in spec.get("facts", []):
        # Short values such as "4" or "2.0" match everywhere and the count is noise.
        # They stay in the file as the authoritative record but are not traced.
        if not fact.get("track_occurrences", True):
            print(f"  {fact['id']:<38} {fact['value']:>8}  (not traced: value too short)")
            continue
        hits = _find(paths, fact["value"])
        outside = [h for h in hits if h[0] != "docs/canonical-facts.yaml"]
        print(f"  {fact['id']:<38} {fact['value']:>8}  in {len(outside)} file(s)")
        if args.list:
            for relative, number, text in outside:
                print(f"      {relative}:{number}  {text}")

    print("\nRetracted claims")
    failures: list[str] = []
    for claim in spec.get("retracted", []):
        allowed = claim.get("allowed_in", [])
        stale: list[tuple[str, int, str]] = []
        for pattern in claim.get("patterns", []):
            for relative, number, text in _find(paths, pattern):
                if not _is_allowed(relative, allowed):
                    stale.append((relative, number, text))
        if stale:
            print(f"  FAIL  {claim['id']}")
            print(f"        superseded by: {claim['superseded_by']}")
            for relative, number, text in stale:
                print(f"        {relative}:{number}  {text}")
            failures.append(claim["id"])
        else:
            print(f"  ok    {claim['id']}")

    if failures:
        print(
            f"\n{len(failures)} retracted claim(s) still present outside the files that "
            "document the correction. Update the text, or add the file to allowed_in if "
            "it is recording the correction itself."
        )
        return 1

    print("\nNo retracted claim survives outside its allowed files.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
