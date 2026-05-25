from __future__ import annotations
from datetime import date, timedelta
from unittest.mock import patch

import pytest

from scripts.curator import VideoMeta, curate
from scripts.state import State, StoredEpisode, SkippedEntry
from scripts.watchlist import ChannelEntry, Defaults, Watchlist


def _mk_video(vid, vc, days_ago):
    upload = (date.today() - timedelta(days=days_ago)).strftime("%Y%m%d")
    return VideoMeta(
        video_id=vid, channel_id="UCx", channel_name="Andrej",
        title=f"v-{vid}", duration_sec=600,
        view_count=vc, upload_date_yyyymmdd=upload,
        thumbnail_url=f"https://i/{vid}.jpg",
    )


def test_filters_out_old_videos():
    wl = Watchlist(
        defaults=Defaults(lookback_days=7, top_k=5),
        channels=[ChannelEntry(url="https://yt/@a")],
    )
    state = State()
    fake = [_mk_video("new", 100, 3), _mk_video("old", 9999, 30)]
    with patch("scripts.curator.fetch_channel_videos", return_value=fake):
        out = curate(wl, state)
    assert [c.video_id for c in out] == ["new"]


def test_filters_out_seen_videos():
    wl = Watchlist(
        defaults=Defaults(lookback_days=7, top_k=5),
        channels=[ChannelEntry(url="https://yt/@a")],
    )
    state = State(
        skipped=[SkippedEntry(video_id="skip", skipped_at="2026-01-01T00:00:00+09:00")],
        episodes=[StoredEpisode(
            video_id="done", title="t", channel="c", duration_sec=1, url="u",
            summary="s", published_at="2026-01-01T00:00:00+09:00",
            asset_filename="f", asset_bytes=1, downloaded_at="2026-01-01T00:00:00+09:00",
        )],
    )
    fake = [_mk_video("skip", 200, 1), _mk_video("done", 300, 1), _mk_video("new", 100, 1)]
    with patch("scripts.curator.fetch_channel_videos", return_value=fake):
        out = curate(wl, state)
    assert [c.video_id for c in out] == ["new"]


def test_top_k_per_channel():
    wl = Watchlist(
        defaults=Defaults(lookback_days=7, top_k=2),
        channels=[ChannelEntry(url="https://yt/@a")],
    )
    fake = [_mk_video(str(i), 100 - i, 1) for i in range(5)]
    with patch("scripts.curator.fetch_channel_videos", return_value=fake):
        out = curate(wl, State())
    # top_k=2 means we keep the 2 highest view_count
    assert [c.video_id for c in out] == ["0", "1"]


def test_missing_view_count_excluded():
    wl = Watchlist(
        defaults=Defaults(lookback_days=7, top_k=5),
        channels=[ChannelEntry(url="https://yt/@a")],
    )
    fake = [
        VideoMeta(video_id="ok", channel_id="UCx", channel_name="A",
                  title="t", duration_sec=600, view_count=100,
                  upload_date_yyyymmdd=date.today().strftime("%Y%m%d"),
                  thumbnail_url=""),
        VideoMeta(video_id="bad", channel_id="UCx", channel_name="A",
                  title="t", duration_sec=600, view_count=None,
                  upload_date_yyyymmdd=date.today().strftime("%Y%m%d"),
                  thumbnail_url=""),
    ]
    with patch("scripts.curator.fetch_channel_videos", return_value=fake):
        out = curate(wl, State())
    assert [c.video_id for c in out] == ["ok"]


def test_channel_fetch_error_does_not_abort_others():
    from yt_dlp import DownloadError
    wl = Watchlist(
        defaults=Defaults(lookback_days=7, top_k=5),
        channels=[
            ChannelEntry(url="https://yt/@bad"),
            ChannelEntry(url="https://yt/@good"),
        ],
    )
    fake_good = [_mk_video("g", 1, 1)]
    def fetcher(url, limit, channel_overrides=None):
        if "@bad" in url:
            raise DownloadError("anti-bot")
        return fake_good
    with patch("scripts.curator.fetch_channel_videos", side_effect=fetcher):
        out = curate(wl, State())
    assert [c.video_id for c in out] == ["g"]


def test_per_channel_override_lookback():
    wl = Watchlist(
        defaults=Defaults(lookback_days=7, top_k=5),
        channels=[ChannelEntry(url="https://yt/@a", lookback_days=30, top_k=1)],
    )
    fake = [_mk_video("a", 100, 20)]  # 20 days old, in 30-day window
    with patch("scripts.curator.fetch_channel_videos", return_value=fake):
        out = curate(wl, State())
    assert [c.video_id for c in out] == ["a"]
