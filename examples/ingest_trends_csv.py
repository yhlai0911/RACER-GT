"""Convert manually downloaded Google Trends CSV exports into the raw chunk table.

This is the adapter that the ingestion-first design leaves to the user. The
package never fetches anything; it needs one long-format table whose columns are
listed in docs/data_dictionary.md. This script produces that table from the CSV
files the Trends web interface hands you when you press the download button --
the route that actually worked when the undocumented JSON endpoints returned 429
(see examples/collect_google_trends.py for what failed and why).

Input files are named ``<chunk_id>_<window_start>_<window_end>.csv``, for example
``C0001_2024-01-01_2024-06-28.csv``. The chunk identifier and the declared window
come from the file name, because the export itself records neither: it contains
only a category line, a blank line, a header naming the query, and one row per
day. Renaming a file therefore relabels a chunk, so the names are treated as part
of the protocol and are validated against the dates actually present.

The export encodes values below one as the string ``<1`` rather than a number.
That is a censoring marker, not a zero, and mapping it to zero would inflate the
zero share that detection reliability is measured on. It is converted to
``--censored-value`` (0.5 by default) and counted in the summary so the choice is
visible rather than silent.

Usage:

    python examples/ingest_trends_csv.py real_data/raw_downloads \\
        --series-id bitcoin_us --keyword bitcoin --geo US \\
        --pull-id P001 --collection-day 0 --stream-id A --replicate-id 1 \\
        --out real_data/raw_chunks.csv

One invocation produces one pull. A full RACER-GT design needs several, each
collected on its own scheduled day from its own stream environment; append them
to the same --out file to build the table the pipeline expects.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

# C0001_2024-01-01_2024-06-28.csv
FILENAME_PATTERN = re.compile(
    r"^(?P<chunk_id>[A-Za-z0-9]+)_"
    r"(?P<window_start>\d{4}-\d{2}-\d{2})_"
    r"(?P<window_end>\d{4}-\d{2}-\d{2})\.csv$"
)

# "bitcoin: (United States)" or "bitcoin: (美國)" -- the geography is localized to
# the download session's interface language, so only the query part is trusted.
HEADER_PATTERN = re.compile(r"^(?P<query>.+?):\s*\((?P<geo>.+)\)\s*$")

CENSORED_MARKER = "<1"


def parse_export(path: Path, censored_value: float) -> tuple[pd.DataFrame, str, int]:
    """Read one Trends CSV export into dates, values, and its declared query.

    Returns the two-column frame, the query string from the header, and the
    number of censored ``<1`` cells that were substituted.
    """

    frame = pd.read_csv(path, skiprows=2)
    if frame.shape[1] != 2:
        raise ValueError(f"{path.name}: expected 2 columns, found {frame.shape[1]}")

    value_header = str(frame.columns[1])
    match = HEADER_PATTERN.match(value_header)
    query = match.group("query").strip() if match else value_header.strip()

    dates = pd.to_datetime(frame.iloc[:, 0], errors="coerce")
    if dates.isna().any():
        bad = int(dates.isna().sum())
        raise ValueError(f"{path.name}: {bad} unparseable date(s) in column 1")

    raw = frame.iloc[:, 1].astype(str).str.strip()
    censored = int((raw == CENSORED_MARKER).sum())
    values = pd.to_numeric(raw.replace(CENSORED_MARKER, str(censored_value)), errors="coerce")
    if values.isna().any():
        offenders = raw[values.isna()].unique()[:5].tolist()
        raise ValueError(f"{path.name}: non-numeric value(s) {offenders}")

    return (
        pd.DataFrame({"historical_date": dates.dt.normalize(), "value": values.astype(float)}),
        query,
        censored,
    )


def ingest(directory: Path, args: argparse.Namespace) -> pd.DataFrame:
    paths = sorted(directory.glob("*.csv"))
    if not paths:
        raise SystemExit(f"No CSV files in {directory}")

    parts: list[pd.DataFrame] = []
    queries: dict[str, str] = {}
    censored_total = 0

    for path in paths:
        name_match = FILENAME_PATTERN.match(path.name)
        if name_match is None:
            raise SystemExit(
                f"{path.name} does not match <chunk_id>_<start>_<end>.csv; "
                "the chunk identifier and window come from the file name"
            )
        chunk_id = name_match.group("chunk_id")
        window_start = pd.Timestamp(name_match.group("window_start"))
        window_end = pd.Timestamp(name_match.group("window_end"))

        observations, query, censored = parse_export(path, args.censored_value)
        censored_total += censored
        queries[chunk_id] = query

        # The declared window is protocol metadata; the schema validator rejects
        # any historical_date outside it, so catch the mismatch here where the
        # file name can still be blamed for it.
        outside = ~observations["historical_date"].between(window_start, window_end)
        if outside.any():
            raise SystemExit(
                f"{path.name}: {int(outside.sum())} date(s) outside the window its "
                f"name declares ({window_start.date()} to {window_end.date()})"
            )

        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        # The download button leaves no retrieval timestamp anywhere in the file.
        # The modification time is the closest available record and is labelled
        # as such rather than presented as the moment Google served the response.
        retrieved_at = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)

        observations = observations.assign(
            series_id=args.series_id,
            pull_id=args.pull_id,
            chunk_id=chunk_id,
            collection_day=args.collection_day,
            stream_id=args.stream_id,
            replicate_id=args.replicate_id,
            window_start=window_start,
            window_end=window_end,
            retrieved_at=retrieved_at,
            keyword=args.keyword,
            topic_or_term=args.topic_or_term,
            geo=args.geo,
            category=args.category,
            search_property=args.search_property,
            language=args.language,
            is_partial=False,
            raw_response_hash=digest,
            source_file=path.name,
        )
        parts.append(observations)

    distinct = sorted(set(queries.values()))
    if len(distinct) > 1:
        raise SystemExit(
            f"Chunks were downloaded for different queries: {distinct}. "
            "They cannot be calibrated onto a common scale."
        )
    if distinct and args.keyword and distinct[0] != args.keyword:
        print(
            f"warning: files declare query {distinct[0]!r} but --keyword is "
            f"{args.keyword!r}; recording --keyword",
            file=sys.stderr,
        )

    table = pd.concat(parts, ignore_index=True)
    columns = [
        "series_id",
        "pull_id",
        "chunk_id",
        "historical_date",
        "value",
        "collection_day",
        "stream_id",
        "replicate_id",
        "window_start",
        "window_end",
        "retrieved_at",
        "keyword",
        "topic_or_term",
        "geo",
        "category",
        "search_property",
        "language",
        "is_partial",
        "raw_response_hash",
        "source_file",
    ]
    table = table[columns].sort_values(["chunk_id", "historical_date"], ignore_index=True)

    duplicated = table.duplicated(["series_id", "pull_id", "chunk_id", "historical_date"])
    if duplicated.any():
        raise SystemExit(f"{int(duplicated.sum())} duplicate observation key(s)")

    if censored_total:
        print(
            f"note: {censored_total} cell(s) exported as {CENSORED_MARKER!r} were "
            f"set to {args.censored_value}",
            file=sys.stderr,
        )
    return table


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("directory", type=Path, help="Directory of Trends CSV exports")
    parser.add_argument("--out", type=Path, required=True, help="Destination CSV")
    parser.add_argument("--series-id", required=True)
    parser.add_argument("--keyword", required=True)
    parser.add_argument("--geo", default="US")
    parser.add_argument("--pull-id", default="P001")
    parser.add_argument(
        "--collection-day",
        type=int,
        default=0,
        help="Ordinal index into the locked schedule, not a calendar offset",
    )
    parser.add_argument("--stream-id", default="A")
    parser.add_argument("--replicate-id", default="1")
    parser.add_argument("--topic-or-term", default="term", choices=["term", "topic"])
    parser.add_argument("--category", default=0, type=int)
    parser.add_argument("--search-property", default="web")
    parser.add_argument("--language", default="en-US")
    parser.add_argument(
        "--censored-value",
        type=float,
        default=0.5,
        help=f"Value substituted for cells exported as {CENSORED_MARKER!r}",
    )
    parser.add_argument(
        "--append",
        action="store_true",
        help="Append to --out instead of overwriting, to accumulate pulls",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    table = ingest(args.directory, args)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    if args.append and args.out.exists():
        table.to_csv(args.out, mode="a", header=False, index=False)
    else:
        table.to_csv(args.out, index=False)

    print(f"{len(table)} rows from {table['chunk_id'].nunique()} chunks -> {args.out}")
    print(
        f"  pull {args.pull_id}  day {args.collection_day}  stream {args.stream_id}  "
        f"replicate {args.replicate_id}"
    )
    print(
        f"  {table['historical_date'].min().date()} to "
        f"{table['historical_date'].max().date()}, "
        f"{table['historical_date'].nunique()} distinct dates"
    )
    print(f"  zero share {float((table['value'] == 0).mean()):.4f}")


if __name__ == "__main__":
    main()
