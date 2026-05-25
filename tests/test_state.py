from __future__ import annotations
import json
from pathlib import Path

from scripts.state import Candidate, State, StoredEpisode, SkippedEntry, load_state, save_state


def test_empty_state_when_file_missing(tmp_path: Path):
    s = load_state(tmp_path / "state.json")
    assert s.candidates == []
    assert s.skipped == []
    assert s.episodes == []
    assert s.in_progress == []
    assert s.last_errors == {}


def test_save_then_load_roundtrip(tmp_path: Path):
    p = tmp_path / "state.json"
    original = State(
        last_curated_at="2026-05-25T14:30:00+09:00",
        candidates=[Candidate(
            video_id="abc", channel_id="UCx", channel_name="Andrej",
            channel_alias="카파시", title="GPT-2", duration_sec=7234,
            view_count=100, upload_date="2026-05-20", days_old=5,
            url="https://youtu.be/abc", thumbnail_url="https://i/abc.jpg",
            score=100.0,
        )],
        skipped=[SkippedEntry(video_id="x", skipped_at="2026-05-24T11:00:00+09:00")],
        episodes=[StoredEpisode(
            video_id="y", title="t", channel="c", duration_sec=60,
            url="https://youtu.be/y", summary="s", published_at="2026-05-18T09:00:00Z",
            asset_filename="2026-05-18_y_t.m4a", asset_bytes=1234,
            downloaded_at="2026-05-25T14:35:00+09:00",
        )],
        in_progress=["z"],
        last_errors={"e": "msg"},
    )
    save_state(p, original)
    loaded = load_state(p)
    assert loaded == original


def test_corrupt_json_is_quarantined(tmp_path: Path):
    p = tmp_path / "state.json"
    p.write_text("{not json")
    s = load_state(p)
    assert s.candidates == []
    assert (p.with_suffix(".json.bak")).read_text() == "{not json"


def test_atomic_save_no_partial_on_failure(tmp_path: Path, monkeypatch):
    p = tmp_path / "state.json"
    save_state(p, State())
    original_bytes = p.read_bytes()
    # simulate replace failure mid-write
    import os
    real_replace = os.replace
    def boom(*a, **kw):
        raise RuntimeError("disk on fire")
    monkeypatch.setattr(os, "replace", boom)
    try:
        save_state(p, State(last_curated_at="2099-01-01T00:00:00+09:00"))
    except RuntimeError:
        pass
    assert p.read_bytes() == original_bytes
