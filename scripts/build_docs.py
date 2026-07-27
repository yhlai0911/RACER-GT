#!/usr/bin/env python3
"""Build every RACER-GT document from LaTeX to PDF.

Sources live in ``docs/latex`` and are named ``<slug>.<lang>.tex`` where lang is
``zh`` or ``en``. Outputs are written to ``docs/pdf`` under stable, citable
names so that a URL published today keeps resolving after a rebuild.

The script is the single entry point used by ``make docs`` and by the
``docs`` GitHub Actions workflow, so a document that builds here builds in CI.

Exit status is non-zero if any document fails, so it can gate a release.
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "docs" / "latex"
OUT = ROOT / "docs" / "pdf"

LANG_SUFFIX = {"zh": "zh-TW", "en": "en"}

# Slug -> published basename. Keeping this explicit (rather than deriving it)
# means renaming a source file cannot silently change a published PDF URL.
TITLES = {
    "methodology": "RACER-GT-Methodology",
    "math-appendix": "RACER-GT-Mathematical-Appendix",
    "user-guide": "RACER-GT-User-Guide",
    "protocol": "RACER-GT-Protocol-and-Preregistration",
    "validation": "RACER-GT-Validation-Report",
    "api-reference": "RACER-GT-API-Reference",
}


def discover() -> list[tuple[str, str, Path]]:
    found = []
    for path in sorted(SRC.glob("*.tex")):
        if path.name.startswith("_"):
            continue  # shared preamble fragments are inputs, not documents
        match = re.fullmatch(r"(?P<slug>[a-z0-9-]+)\.(?P<lang>zh|en)\.tex", path.name)
        if not match:
            print(f"  skip (unrecognised name): {path.name}")
            continue
        found.append((match["slug"], match["lang"], path))
    return found


def page_count(pdf: Path) -> int | None:
    """Read the page count without adding a PDF library dependency."""
    try:
        proc = subprocess.run(
            ["mdls", "-raw", "-name", "kMDItemNumberOfPages", str(pdf)],
            capture_output=True,
            text=True,
            timeout=30,
        )
        value = proc.stdout.strip()
        if value.isdigit():
            return int(value)
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        proc = subprocess.run(
            ["pdfinfo", str(pdf)], capture_output=True, text=True, timeout=30
        )
        match = re.search(r"^Pages:\s+(\d+)", proc.stdout, re.M)
        if match:
            return int(match.group(1))
    except (OSError, subprocess.SubprocessError):
        pass
    return None


def build_one(slug: str, lang: str, source: Path, keep_aux: bool) -> tuple[bool, str]:
    # latexmk must run inside docs/latex so that \input{_common} resolves.
    cmd = [
        "latexmk",
        "-xelatex",
        "-interaction=nonstopmode",
        "-halt-on-error",
        "-file-line-error",
        source.name,
    ]
    proc = subprocess.run(cmd, cwd=SRC, capture_output=True, text=True, timeout=1800)
    built = SRC / f"{source.stem}.pdf"
    if proc.returncode != 0 or not built.exists():
        errors = [ln for ln in proc.stdout.splitlines() if ln.startswith("./") or ln.startswith("!")]
        detail = errors[0] if errors else f"latexmk exit {proc.returncode}"
        return False, detail

    OUT.mkdir(parents=True, exist_ok=True)
    target = OUT / f"{TITLES.get(slug, slug)}-{LANG_SUFFIX[lang]}.pdf"
    shutil.move(str(built), target)
    if not keep_aux:
        subprocess.run(
            ["latexmk", "-c", source.name], cwd=SRC, capture_output=True, timeout=300
        )
    pages = page_count(target)
    return True, f"{target.name} ({pages} pages)" if pages else target.name


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", help="build a single slug, e.g. --only methodology")
    parser.add_argument("--lang", choices=["zh", "en"], help="build a single language")
    parser.add_argument("--keep-aux", action="store_true", help="do not clean .aux/.log")
    args = parser.parse_args()

    if shutil.which("latexmk") is None:
        print("error: latexmk not found. Install TeX Live (or BasicTeX + latexmk).")
        return 127

    documents = discover()
    if args.only:
        documents = [d for d in documents if d[0] == args.only]
    if args.lang:
        documents = [d for d in documents if d[1] == args.lang]
    if not documents:
        print("error: no matching documents found in docs/latex")
        return 1

    failures = []
    print(f"Building {len(documents)} document(s) from {SRC.relative_to(ROOT)}\n")
    for slug, lang, source in documents:
        print(f"  {source.name:<32}", end="", flush=True)
        ok, detail = build_one(slug, lang, source, args.keep_aux)
        print(("OK    " if ok else "FAIL  ") + detail)
        if not ok:
            failures.append(source.name)

    print()
    if failures:
        print(f"{len(failures)} document(s) failed: {', '.join(failures)}")
        print("Re-run with --keep-aux and read docs/latex/<name>.log for the full error.")
        return 1
    print(f"All {len(documents)} document(s) built into {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
