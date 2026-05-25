import json
import xml.etree.ElementTree as ET
from pathlib import Path

from scripts.rss_builder import build_feed_xml, FeedMeta, FeedEpisode

FIXTURE = Path(__file__).parent / "fixtures" / "sample_episodes.json"


def _load_episodes() -> list[FeedEpisode]:
    raw = json.loads(FIXTURE.read_text())
    return [
        FeedEpisode(
            video_id=e["video_id"],
            title=e["title"],
            channel=e["channel"],
            duration_sec=e["duration_sec"],
            url=e["url"],
            summary=e["summary"],
            published_at=e["published_at"],
            asset_url=e["asset_url"],
            asset_bytes=e["asset_bytes"],
        )
        for e in raw
    ]


def _parse(xml: bytes):
    return ET.fromstring(xml)


def test_feed_has_channel_metadata():
    meta = FeedMeta(
        title="pocket-pod",
        description="K's curated YouTube audio feed",
        link="https://seonyoung-kim.github.io/pocket-pod-7c3f9a/",
        author="K",
        image_url="https://seonyoung-kim.github.io/pocket-pod-7c3f9a/cover.png",
        category="Education",
    )
    xml = build_feed_xml(meta, _load_episodes())
    root = _parse(xml)
    channel = root.find("channel")
    assert channel.findtext("title") == "pocket-pod"
    assert "K's curated" in channel.findtext("description")


def test_feed_has_one_item_per_episode():
    meta = FeedMeta("t", "d", "https://example.com/", "a", "https://example.com/i.png", "Education")
    xml = build_feed_xml(meta, _load_episodes())
    root = _parse(xml)
    items = root.findall("channel/item")
    assert len(items) == 2


def test_item_enclosure_has_url_type_length():
    meta = FeedMeta("t", "d", "https://example.com/", "a", "https://example.com/i.png", "Education")
    xml = build_feed_xml(meta, _load_episodes())
    root = _parse(xml)
    enc = root.find("channel/item/enclosure")
    assert enc.get("url").startswith("https://github.com/")
    assert enc.get("type") == "audio/mp4"
    assert int(enc.get("length")) > 0


def test_item_guid_uses_video_id_namespace():
    meta = FeedMeta("t", "d", "https://example.com/", "a", "https://example.com/i.png", "Education")
    xml = build_feed_xml(meta, _load_episodes())
    root = _parse(xml)
    guid = root.find("channel/item/guid")
    assert guid.text.startswith("youtube:")
    assert guid.get("isPermaLink") == "false"


def test_special_chars_in_summary_do_not_break_xml():
    meta = FeedMeta("t", "d", "https://example.com/", "a", "https://example.com/i.png", "Education")
    xml = build_feed_xml(meta, _load_episodes())
    # ET.fromstring would raise if XML is malformed
    root = _parse(xml)
    assert root is not None


def test_itunes_duration_formats_as_hhmmss():
    meta = FeedMeta("t", "d", "https://example.com/", "a", "https://example.com/i.png", "Education")
    xml = build_feed_xml(meta, _load_episodes())
    ns = {"itunes": "http://www.itunes.com/dtds/podcast-1.0.dtd"}
    root = _parse(xml)
    durations = [i.findtext("itunes:duration", namespaces=ns) for i in root.findall("channel/item")]
    assert "01:01:01" in durations
    assert "00:10:00" in durations


def test_hhmmss_boundary_values():
    from scripts.rss_builder import _hhmmss
    assert _hhmmss(0) == "00:00:00"
    assert _hhmmss(3600) == "01:00:00"
    assert _hhmmss(59) == "00:00:59"
    assert _hhmmss(90061) == "25:01:01"


def test_description_includes_origin_url():
    meta = FeedMeta(
        title="t", description="d", link="http://x",
        author="a", image_url="http://i", category="Technology",
    )
    ep = FeedEpisode(
        video_id="abc",
        title="T", channel="C", duration_sec=60,
        url="https://www.youtube.com/watch?v=abc",
        summary="요약 첫 줄.",
        published_at="2026-05-20T00:00:00Z",
        asset_url="http://x/a.m4a", asset_bytes=123,
    )
    xml = build_feed_xml(meta, [ep]).decode()
    assert "요약 첫 줄." in xml
    assert "원본: https://www.youtube.com/watch?v=abc" in xml


def test_description_falls_back_when_summary_empty():
    meta = FeedMeta(
        title="t", description="d", link="http://x",
        author="a", image_url="http://i", category="Technology",
    )
    ep = FeedEpisode(
        video_id="abc",
        title="T", channel="C", duration_sec=60,
        url="https://www.youtube.com/watch?v=abc",
        summary="",
        published_at="2026-05-20T00:00:00Z",
        asset_url="http://x/a.m4a", asset_bytes=123,
    )
    xml = build_feed_xml(meta, [ep]).decode()
    assert "(설명 없음)" in xml
    assert "원본: https://www.youtube.com/watch?v=abc" in xml
