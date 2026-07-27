"""Reference collector for the RACER-GT raw chunk table.

This is an EXAMPLE, not part of the package. RACER-GT is ingestion-first on
purpose: endpoints, authentication, rate limits, and terms of service change, and
a statistical method that depends on one unofficial client inherits that
fragility. The estimator never needs to know where the numbers came from --- it
only needs the schema in docs/data_dictionary.md. Replace this file with the
official API, a manual CSV export, or an institutionally approved client without
touching anything else.

STATUS: the API path below was tested on 2026-07-28 and did NOT work. The
explore endpoint returned 200, the very next widgetdata request returned HTTP
429, and a retry 30 seconds later returned 429 again. The web front end was
throttled at the same time: its own widgetdata request returned 429 while the
chart still rendered from cache, which means a user cannot tell from the screen
whether a series was actually retrieved. Treat this file as (a) a request-budget
calculator via --preview, and (b) a starting point if the endpoints or your
access conditions differ. What actually worked was the CSV download button on
trends.google.com, one chunk at a time; see review/HANDOFF-real-data-validation.md.

Read this before running it:

* The Google Trends web endpoints used here are undocumented. Check your own
  obligations under Google's terms of service; that judgment is yours, not this
  script's.
* Retrieval is rate limited, and aggressively so. Community experience with
  pytrends puts the floor at 3--5 seconds between requests and about 60 seconds
  of recovery once you are throttled (GeneralMills/pytrends issues #243, #523).
  The defaults here are more conservative than that, and were still refused.
* Plan the design around that limit. The manuscript's recommended protocol
  (2010 onwards, 180-day windows, 15--30 day steps, 21--42 pulls) implies
  4,000--16,500 requests, or 92--183 hours at a 20-second spacing. A single year
  with a 30-day step is 8 chunks per pull and finishes in minutes, which is what
  makes a study feasible at all. See --preview.

Usage:

    # See the request budget before collecting anything.
    python examples/collect_google_trends.py --preview \\
        --keyword bitcoin --start 2024-01-01 --end 2024-12-31

    # Collect one pull (one collection day, one stream, one replicate).
    python examples/collect_google_trends.py \\
        --keyword bitcoin --geo US --start 2024-01-01 --end 2024-12-31 \\
        --pull-id P001 --collection-day 0 --stream-id A \\
        --out raw_chunks.csv

Run it once per pull, on the collection days your locked schedule specifies,
from the stream environment that pull belongs to. Appending to the same --out
file across runs builds the raw chunk table the pipeline expects.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import http.cookiejar
import json
import random
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

EXPLORE = "https://trends.google.com/trends/api/explore"
MULTILINE = "https://trends.google.com/trends/api/widgetdata/multiline"
HOMEPAGE = "https://trends.google.com/trends/"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

FIELDS = [
    # Required by racergt.schema.RAW_REQUIRED_COLUMNS
    "series_id", "pull_id", "chunk_id", "historical_date", "value",
    "collection_day", "stream_id", "replicate_id", "window_start", "window_end",
    # Strongly recommended by docs/data_dictionary.md
    "retrieved_at", "keyword", "topic_or_term", "geo", "category",
    "search_property", "language", "is_partial", "raw_response_hash",
]


@dataclass
class Chunk:
    chunk_id: str
    start: date
    end: date


def build_chunks(start: date, end: date, window_days: int, step_days: int) -> list[Chunk]:
    """Fixed chunk manifest. Must match the locked protocol for every pull."""

    chunks, index, cursor = [], 1, start
    while cursor <= end:
        stop = min(cursor + timedelta(days=window_days - 1), end)
        chunks.append(Chunk(f"C{index:04d}", cursor, stop))
        if stop >= end:
            break
        cursor += timedelta(days=step_days)
        index += 1
    return chunks


class TrendsClient:
    """Minimal Trends client with cookie handling and backoff."""

    def __init__(self, language: str = "en-US", timezone_offset: int = -480) -> None:
        self.language = language
        self.timezone_offset = timezone_offset
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.jar)
        )
        self.opener.addheaders = [("User-Agent", USER_AGENT), ("Accept-Language", language)]

    def warm_up(self) -> None:
        """Fetch the homepage first so the session carries a consent cookie."""

        try:
            self.opener.open(HOMEPAGE, timeout=30).read()
        except urllib.error.URLError as exc:  # non-fatal: the API may still work
            print(f"  ! warm-up failed ({exc}); continuing", file=sys.stderr)

    def _get(self, url: str, attempts: int, base_pause: float) -> str:
        """GET with exponential backoff on 429. Returns the body minus Google's prefix."""

        for attempt in range(1, attempts + 1):
            try:
                with self.opener.open(url, timeout=60) as response:
                    body = response.read().decode("utf-8")
                # Responses are prefixed with )]}' or )]}',\n to defeat JSON hijacking.
                return body[body.index("{"):]
            except urllib.error.HTTPError as exc:
                if exc.code != 429 or attempt == attempts:
                    raise
                # Recovery after a 429 is reported at about 60 seconds, which is
                # independent of (and usually longer than) the inter-request pause,
                # so back off from that floor rather than from --pause. Full jitter:
                # retrying in lockstep is what gets a client blocked.
                delay = max(base_pause, 60.0) * (2 ** (attempt - 1))
                delay = random.uniform(delay / 2, delay)
                print(
                    f"  429 rate limited (attempt {attempt}/{attempts}); "
                    f"waiting {delay:.0f}s",
                    file=sys.stderr,
                )
                time.sleep(delay)
        raise RuntimeError("unreachable")

    def fetch_chunk(
        self,
        keyword: str,
        geo: str,
        chunk: Chunk,
        category: int,
        search_property: str,
        attempts: int,
        base_pause: float,
    ) -> tuple[list[tuple[str, float, bool]], str]:
        window = f"{chunk.start.isoformat()} {chunk.end.isoformat()}"
        request = {
            "comparisonItem": [{"keyword": keyword, "geo": geo, "time": window}],
            "category": category,
            "property": search_property if search_property != "web" else "",
        }
        query = urllib.parse.urlencode(
            {"hl": self.language, "tz": self.timezone_offset, "req": json.dumps(request)}
        )
        explore = json.loads(self._get(f"{EXPLORE}?{query}", attempts, base_pause))
        widget = next((w for w in explore["widgets"] if w.get("id") == "TIMESERIES"), None)
        if widget is None:
            raise RuntimeError(f"{chunk.chunk_id}: no TIMESERIES widget in explore response")

        query = urllib.parse.urlencode(
            {
                "hl": self.language,
                "tz": self.timezone_offset,
                "req": json.dumps(widget["request"]),
                "token": widget["token"],
            }
        )
        raw = self._get(f"{MULTILINE}?{query}", attempts, base_pause)
        payload = json.loads(raw)
        resolution = widget["request"].get("resolution")
        if resolution != "DAY":
            raise RuntimeError(
                f"{chunk.chunk_id}: Trends returned {resolution} resolution, not DAY. "
                "Shorten the chunk window."
            )
        points = [
            (
                datetime.utcfromtimestamp(int(point["time"])).date().isoformat(),
                float(point["value"][0]),
                bool(point.get("isPartial", False)),
            )
            for point in payload["default"]["timelineData"]
        ]
        return points, hashlib.sha256(raw.encode("utf-8")).hexdigest()


def already_collected(path: Path, pull_id: str) -> set[str]:
    """Chunk ids this pull already has, so an interrupted run can resume."""

    if not path.exists():
        return set()
    with path.open(newline="", encoding="utf-8") as handle:
        return {
            row["chunk_id"]
            for row in csv.DictReader(handle)
            if row.get("pull_id") == pull_id
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--keyword", required=True)
    parser.add_argument("--geo", default="US")
    parser.add_argument("--start", required=True, type=date.fromisoformat)
    parser.add_argument("--end", required=True, type=date.fromisoformat)
    parser.add_argument("--window-days", type=int, default=180)
    parser.add_argument("--step-days", type=int, default=30)
    parser.add_argument("--series-id", default="target")
    parser.add_argument("--pull-id", default="P001")
    parser.add_argument("--collection-day", type=int, default=0)
    parser.add_argument("--stream-id", default="A")
    parser.add_argument("--replicate-id", default="1")
    parser.add_argument("--category", type=int, default=0)
    parser.add_argument("--search-property", default="web")
    parser.add_argument("--language", default="en-US")
    parser.add_argument("--topic-or-term", default="term")
    parser.add_argument("--out", type=Path, default=Path("raw_chunks.csv"))
    parser.add_argument(
        "--pause", type=float, default=20.0,
        help="seconds between chunks, and the base for 429 backoff (default 20)",
    )
    parser.add_argument("--attempts", type=int, default=5, help="attempts per request")
    parser.add_argument(
        "--preview", action="store_true",
        help="print the chunk manifest and request budget, then exit without collecting",
    )
    args = parser.parse_args()

    chunks = build_chunks(args.start, args.end, args.window_days, args.step_days)
    print(f"{len(chunks)} chunks per pull, {args.window_days}-day window, {args.step_days}-day step")

    if args.preview:
        print(f"  {chunks[0].chunk_id}: {chunks[0].start} .. {chunks[0].end}")
        if len(chunks) > 2:
            print("  ...")
        print(f"  {chunks[-1].chunk_id}: {chunks[-1].start} .. {chunks[-1].end}")
        print()
        print("Request budget (2 requests per chunk: explore, then widgetdata):")
        for pulls in (1, 21, 42):
            total = len(chunks) * pulls * 2
            hours = total * args.pause / 3600
            label = "one pull" if pulls == 1 else f"{pulls} pulls"
            print(f"  {label:9s}: {total:6,d} requests, >= {hours:.1f}h at --pause {args.pause:g}")
        print()
        print("Rate limiting is the binding constraint, not bandwidth. Design accordingly.")
        return 0

    done = already_collected(args.out, args.pull_id)
    if done:
        print(f"resuming {args.pull_id}: {len(done)} of {len(chunks)} chunks already present")

    client = TrendsClient(language=args.language)
    client.warm_up()

    new_file = not args.out.exists()
    written = 0
    with args.out.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        if new_file:
            writer.writeheader()

        for position, chunk in enumerate(chunks, start=1):
            if chunk.chunk_id in done:
                continue
            print(f"[{position}/{len(chunks)}] {chunk.chunk_id} {chunk.start}..{chunk.end}", flush=True)
            try:
                points, response_hash = client.fetch_chunk(
                    args.keyword, args.geo, chunk, args.category,
                    args.search_property, args.attempts, args.pause,
                )
            # Catch broadly on purpose: a partial collection that can be resumed is
            # worth more than a traceback that loses the chunks already fetched.
            except Exception as exc:
                print(f"  ! {exc}", file=sys.stderr)
                print(
                    f"  stopped after {written} new chunks. Rerun the same command later "
                    "to resume; collected chunks are preserved.",
                    file=sys.stderr,
                )
                return 2

            retrieved_at = datetime.now(timezone.utc).isoformat()
            for day, value, is_partial in points:
                writer.writerow(
                    {
                        "series_id": args.series_id,
                        "pull_id": args.pull_id,
                        "chunk_id": chunk.chunk_id,
                        "historical_date": day,
                        "value": value,
                        "collection_day": args.collection_day,
                        "stream_id": args.stream_id,
                        "replicate_id": args.replicate_id,
                        "window_start": chunk.start.isoformat(),
                        "window_end": chunk.end.isoformat(),
                        "retrieved_at": retrieved_at,
                        "keyword": args.keyword,
                        "topic_or_term": args.topic_or_term,
                        "geo": args.geo,
                        "category": args.category,
                        "search_property": args.search_property,
                        "language": args.language,
                        "is_partial": is_partial,
                        "raw_response_hash": response_hash,
                    }
                )
            handle.flush()
            written += 1
            print(f"  {len(points)} daily observations", flush=True)
            if position < len(chunks):
                time.sleep(args.pause)

    print(f"wrote {written} new chunks for {args.pull_id} to {args.out}")
    print("Audit before analysing:  racergt audit protocol.lock.yaml", args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
