from __future__ import annotations
import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from scripts.downloader import download_one, DownloadDeps, regenerate_feed
from scripts.state import Candidate, State, StoredEpisode, load_state, save_state
from scripts.rss_builder import FeedMeta


def _cand(vid="abc"):
    return Candidate(
        video_id=vid, channel_id="UCx", channel_name="Andrej",
        channel_alias="카파시", title="GPT-2 reproduction",
        duration_sec=7234, view_count=100,
        upload_date="2026-05-20", days_old=5,
        url=f"https://www.youtube.com/watch?v={vid}",
        thumbnail_url="https://i/a.jpg", score=100.0,
    )


def test_download_success_appends_episode_and_writes_feed(tmp_path: Path):
    state_path = tmp_path / "state.json"
    downloads = tmp_path / "downloads"
    feed_path = tmp_path / "feed.xml"

    state = State(candidates=[_cand()])
    save_state(state_path, state)

    def fake_fetch_meta(url):
        return {
            "description": "이건 첫 단락.\n\n다음 단락은 잘림.",
            "duration": 7234,
            "upload_date": "20260520",
        }

    def fake_run_ytdlp(url, out_path):
        out_path.write_bytes(b"fake-m4a-bytes")
        return True

    deps = DownloadDeps(fetch_meta=fake_fetch_meta, run_ytdlp=fake_run_ytdlp)
    meta = FeedMeta(title="t", description="d", link="http://x",
                    author="a", image_url="http://i", category="Technology")

    ok = download_one(
        candidate=_cand(),
        state_path=state_path,
        downloads_dir=downloads,
        feed_path=feed_path,
        feed_meta=meta,
        base_url="http://192.168.45.81:8000",
        deps=deps,
    )
    assert ok is True

    s = load_state(state_path)
    assert len(s.episodes) == 1
    ep = s.episodes[0]
    assert ep.video_id == "abc"
    assert ep.summary == "이건 첫 단락."
    assert ep.asset_bytes == len(b"fake-m4a-bytes")
    assert s.candidates == []   # consumed
    assert "abc" not in s.last_errors
    assert feed_path.exists()
    assert "원본: https://www.youtube.com/watch?v=abc" in feed_path.read_text()


def test_download_failure_records_error_and_keeps_candidate(tmp_path: Path):
    state_path = tmp_path / "state.json"
    state = State(candidates=[_cand()])
    save_state(state_path, state)

    def fake_fetch_meta(url):
        return {"description": "", "duration": 1, "upload_date": "20260520"}

    def fake_run_ytdlp(url, out_path):
        return False

    deps = DownloadDeps(fetch_meta=fake_fetch_meta, run_ytdlp=fake_run_ytdlp)
    meta = FeedMeta(title="t", description="d", link="http://x",
                    author="a", image_url="http://i", category="Technology")

    ok = download_one(
        candidate=_cand(),
        state_path=state_path,
        downloads_dir=tmp_path / "downloads",
        feed_path=tmp_path / "feed.xml",
        feed_meta=meta,
        base_url="http://x",
        deps=deps,
    )
    assert ok is False
    s = load_state(state_path)
    assert s.episodes == []
    assert any(c.video_id == "abc" for c in s.candidates)
    assert "abc" in s.last_errors


def test_summary_truncated_at_first_blank_line(tmp_path: Path):
    from scripts.downloader import _extract_summary
    assert _extract_summary("첫 단락.\n\n두 번째.") == "첫 단락."
    assert _extract_summary("한 줄만.") == "한 줄만."
    assert _extract_summary("") == ""
    long = "x" * 800
    assert len(_extract_summary(long)) == 500


def test_regenerate_feed_from_episodes(tmp_path: Path):
    state = State(episodes=[StoredEpisode(
        video_id="v", title="t", channel="c", duration_sec=60,
        url="https://yt/v", summary="s",
        published_at="2026-05-20T00:00:00+00:00",
        asset_filename="2026-05-20_v_t.m4a", asset_bytes=100,
        downloaded_at="2026-05-25T00:00:00+09:00",
    )])
    meta = FeedMeta(title="T", description="D", link="http://x",
                    author="A", image_url="http://i", category="Technology")
    out = tmp_path / "feed.xml"
    regenerate_feed(state, meta, "http://192.168.45.81:8000", out)
    xml = out.read_text()
    assert "<item>" in xml
    assert "http://192.168.45.81:8000/data/downloads/2026-05-20_v_t.m4a" in xml
