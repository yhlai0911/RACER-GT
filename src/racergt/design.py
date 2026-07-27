from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import date, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from .config import RacerGTConfig


def generate_chunk_windows(
    start: date | str,
    end: date | str,
    window_days: int = 180,
    step_days: int = 15,
) -> pd.DataFrame:
    """Generate fixed, overlapping inclusive windows covering a historical interval.

    The last window is anchored to the requested end date so that the full interval is
    covered even when the step does not land exactly on the endpoint.
    """

    start_ts = pd.Timestamp(start).normalize()
    end_ts = pd.Timestamp(end).normalize()
    if end_ts < start_ts:
        raise ValueError("end must not precede start")
    if step_days <= 0 or window_days <= step_days:
        raise ValueError("require 0 < step_days < window_days")

    width = pd.Timedelta(days=window_days - 1)
    step = pd.Timedelta(days=step_days)
    starts: list[pd.Timestamp] = []
    cursor = start_ts
    while cursor + width < end_ts:
        starts.append(cursor)
        cursor += step
    final_start = max(start_ts, end_ts - width)
    if not starts or starts[-1] != final_start:
        starts.append(final_start)

    rows = []
    for idx, ws in enumerate(sorted(set(starts))):
        we = min(ws + width, end_ts)
        rows.append(
            {
                "chunk_id": f"C{idx + 1:04d}",
                "window_start": ws,
                "window_end": we,
                "n_calendar_days": int((we - ws).days + 1),
            }
        )
    return pd.DataFrame(rows)


def _cyclic_order(items: Sequence[str], row: int) -> list[str]:
    n = len(items)
    shift = row % n
    ordered = list(items[shift:]) + list(items[:shift])
    if (row // n) % 2 == 1:
        ordered = ordered[:1] + list(reversed(ordered[1:]))
    return ordered


def _balanced_chunk_order(chunk_ids: Sequence[str], row: int) -> list[str]:
    ids = list(chunk_ids)
    if not ids:
        return []
    shift = row % len(ids)
    ordered = ids[shift:] + ids[:shift]
    if row % 2 == 1:
        ordered = list(reversed(ordered))
    return ordered


def generate_collection_schedule(
    config: RacerGTConfig,
    anchor_date: date | str | None = None,
) -> pd.DataFrame:
    """Generate a reproducible balanced collection schedule.

    Stream order is rotated across collection days. The schedule records a protocol
    hash, making later drift auditable. Different streams are treated as composite
    collection environments; the design does not label them independent samples.
    """

    anchor = pd.Timestamp(anchor_date or datetime.utcnow().date()).normalize()
    design = config.design
    chunks = generate_chunk_windows(
        config.query.historical_start,
        config.query.historical_end,
        config.chunking.window_days,
        config.chunking.step_days,
    )
    chunk_ids = chunks["chunk_id"].tolist()
    rng = np.random.default_rng(design.random_seed)
    rows: list[dict] = []
    pull_counter = 0

    for day_pos, day_offset in enumerate(design.day_offsets):
        collection_date = anchor + pd.Timedelta(days=day_offset)
        stream_order = (
            _cyclic_order(design.streams, day_pos)
            if design.balance_stream_order
            else list(design.streams)
        )
        for order_pos, stream_id in enumerate(stream_order):
            slot = design.time_slots[order_pos % len(design.time_slots)]
            for rep in range(1, design.technical_replicates + 1):
                pull_counter += 1
                chunk_order = (
                    _balanced_chunk_order(chunk_ids, pull_counter - 1)
                    if design.balance_chunk_order
                    else list(chunk_ids)
                )
                # Deterministic micro-jitter prevents all technical replicates from sharing
                # exactly the same planned timestamp while retaining a locked schedule.
                jitter_minutes = int(rng.integers(0, 5)) if design.technical_replicates > 1 else 0
                hh, mm = map(int, slot.split(":"))
                planned = collection_date + pd.Timedelta(hours=hh, minutes=mm + jitter_minutes)
                rows.append(
                    {
                        "pull_id": f"P{pull_counter:03d}",
                        "series_id": config.query.series_id,
                        "day_offset": day_offset,
                        "collection_day": day_pos,
                        "planned_collection_date": collection_date.date().isoformat(),
                        "planned_start_time": planned.isoformat(),
                        "stream_id": stream_id,
                        "stream_order": order_pos + 1,
                        "replicate_id": str(rep),
                        "chunk_count": len(chunk_ids),
                        "chunk_order_json": json.dumps(chunk_order),
                        "historical_start": config.query.historical_start.isoformat(),
                        "historical_end": config.query.historical_end.isoformat(),
                        "protocol_hash": config.protocol_hash(),
                    }
                )
    return pd.DataFrame(rows)


def write_protocol_bundle(
    config: RacerGTConfig,
    output_dir: str | Path,
    anchor_date: date | str | None = None,
) -> dict[str, Path]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    config_path = config.save_yaml(output / "protocol.lock.yaml")
    schedule = generate_collection_schedule(config, anchor_date=anchor_date)
    schedule_path = output / "collection_schedule.csv"
    schedule.to_csv(schedule_path, index=False)
    chunks = generate_chunk_windows(
        config.query.historical_start,
        config.query.historical_end,
        config.chunking.window_days,
        config.chunking.step_days,
    )
    chunks_path = output / "chunk_windows.csv"
    chunks.to_csv(chunks_path, index=False)
    manifest = {
        "protocol_hash": config.protocol_hash(),
        "created_at_utc": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "config": config_path.name,
        "schedule": schedule_path.name,
        "chunks": chunks_path.name,
    }
    manifest_path = output / "protocol_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return {
        "config": config_path,
        "schedule": schedule_path,
        "chunks": chunks_path,
        "manifest": manifest_path,
    }
