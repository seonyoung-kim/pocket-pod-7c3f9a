from datetime import datetime, timezone
from scripts.episode import Episode


def test_episode_roundtrip_json():
    ep = Episode(
        video_id="abc123XYZ_-",
        title="Sample title",
        channel="Sample channel",
        duration_sec=1234,
        url="https://www.youtube.com/watch?v=abc123XYZ_-",
        summary="A short summary.",
        published_at=datetime(2026, 5, 24, 12, 0, tzinfo=timezone.utc),
        score=8.5,
    )
    payload = ep.to_dict()
    restored = Episode.from_dict(payload)
    assert restored == ep


def test_episode_filename_is_filesystem_safe():
    ep = Episode(
        video_id="abc123XYZ_-",
        title="제목: 슬래시/콜론:포함",
        channel="Ch",
        duration_sec=60,
        url="https://www.youtube.com/watch?v=abc123XYZ_-",
        summary="s",
        published_at=datetime(2026, 5, 24, tzinfo=timezone.utc),
        score=1.0,
    )
    name = ep.audio_filename()
    assert name.endswith(".m4a")
    assert "/" not in name
    assert ":" not in name
    assert "abc123XYZ_-" in name
