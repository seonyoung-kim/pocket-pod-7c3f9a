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


def test_safe_channel_url_encodes_korean_handle():
    from scripts.curator import _safe_channel_url
    assert _safe_channel_url("https://www.youtube.com/@지식인사이드") == \
        "https://www.youtube.com/@%EC%A7%80%EC%8B%9D%EC%9D%B8%EC%82%AC%EC%9D%B4%EB%93%9C"
    # Already-encoded URL stays the same (% in safe charset)
    assert _safe_channel_url("https://www.youtube.com/@%EC%A7%80") == \
        "https://www.youtube.com/@%EC%A7%80"
    # ASCII handle untouched
    assert _safe_channel_url("https://www.youtube.com/@AndrejKarpathy") == \
        "https://www.youtube.com/@AndrejKarpathy"


def test_fetch_channel_videos_enriches_missing_fields():
    """flat extract에 view_count/upload_date 누락 → deep fetch로 보강."""
    from datetime import date
    from unittest.mock import patch
    from scripts.curator import fetch_channel_videos

    flat_response = {
        "channel_id": "UCx", "channel": "ch",
        "entries": [
            {"id": "ok1", "title": "t1", "duration": 60,
             "view_count": 1000, "upload_date": "20260520",
             "thumbnails": [{"url": "https://i/ok1.jpg"}]},
            {"id": "missing", "title": "t2", "duration": 60,
             "view_count": None, "upload_date": None,
             "thumbnails": [{"url": "https://i/m.jpg"}]},
        ],
    }
    deep_response = {
        "channel_id": "UCx", "channel": "ch", "title": "t2",
        "duration": 70, "view_count": 5000, "upload_date": "20260521",
        "thumbnail": "https://i/m2.jpg",
    }

    class FakeYDL:
        def __init__(self, opts): self.opts = opts
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def extract_info(self, url, download=False, process=True):
            return flat_response if "/videos" in url else deep_response

    with patch("scripts.curator.YoutubeDL", FakeYDL):
        out = fetch_channel_videos("https://www.youtube.com/@ch", limit=10)

    assert [v.video_id for v in out] == ["ok1", "missing"]
    # ok1 untouched (flat already had view_count + upload_date)
    assert out[0].view_count == 1000
    assert out[0].upload_date_yyyymmdd == "20260520"
    # missing got enriched via deep fetch
    assert out[1].view_count == 5000
    assert out[1].upload_date_yyyymmdd == "20260521"


def test_extract_video_id_recognizes_all_youtube_url_forms():
    from scripts.curator import extract_video_id
    assert extract_video_id("https://www.youtube.com/watch?v=mhnZOuN1xLk") == "mhnZOuN1xLk"
    assert extract_video_id("https://youtu.be/mhnZOuN1xLk") == "mhnZOuN1xLk"
    assert extract_video_id("https://www.youtube.com/shorts/mhnZOuN1xLk") == "mhnZOuN1xLk"
    assert extract_video_id("https://www.youtube.com/embed/mhnZOuN1xLk") == "mhnZOuN1xLk"
    assert extract_video_id("https://www.youtube.com/watch?v=mhnZOuN1xLk&t=42s") == "mhnZOuN1xLk"
    assert extract_video_id("mhnZOuN1xLk") == "mhnZOuN1xLk"
    assert extract_video_id("https://example.com/foo") is None
    assert extract_video_id("") is None


def test_enrich_returns_original_when_deep_fetch_fails():
    from yt_dlp import DownloadError
    from unittest.mock import patch
    from scripts.curator import VideoMeta, _enrich_if_missing

    v = VideoMeta(
        video_id="x", channel_id="", channel_name="",
        title="t", duration_sec=0, view_count=None,
        upload_date_yyyymmdd=None, thumbnail_url="",
    )
    with patch("scripts.curator._ytdlp_video_meta",
               side_effect=DownloadError("anti-bot")):
        result = _enrich_if_missing(v)
    assert result is v   # unchanged
