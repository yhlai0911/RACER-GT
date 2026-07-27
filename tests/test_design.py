from racergt.design import generate_chunk_windows, generate_collection_schedule


def test_chunk_windows_cover_interval(small_config):
    chunks = generate_chunk_windows(
        small_config.query.historical_start,
        small_config.query.historical_end,
        small_config.chunking.window_days,
        small_config.chunking.step_days,
    )
    assert chunks.iloc[0]["window_start"].date() == small_config.query.historical_start
    assert chunks.iloc[-1]["window_end"].date() == small_config.query.historical_end
    assert chunks["chunk_id"].is_unique


def test_schedule_balanced_and_hashed(small_config):
    schedule = generate_collection_schedule(small_config, anchor_date="2026-07-27")
    expected = (
        len(small_config.design.day_offsets)
        * len(small_config.design.streams)
        * small_config.design.technical_replicates
    )
    assert len(schedule) == expected
    assert schedule["pull_id"].is_unique
    assert schedule["protocol_hash"].nunique() == 1
    counts = schedule.groupby(["collection_day", "stream_id"]).size()
    assert counts.nunique() == 1
