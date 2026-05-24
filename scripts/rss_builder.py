from __future__ import annotations
from dataclasses import dataclass

from dateutil.parser import isoparse
from feedgen.feed import FeedGenerator


@dataclass(frozen=True)
class FeedMeta:
    title: str
    description: str
    link: str
    author: str
    image_url: str
    category: str


@dataclass(frozen=True)
class FeedEpisode:
    video_id: str
    title: str
    channel: str
    duration_sec: int
    url: str
    summary: str
    published_at: str  # ISO 8601
    asset_url: str
    asset_bytes: int


def _hhmmss(seconds: int) -> str:
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def build_feed_xml(meta: FeedMeta, episodes: list[FeedEpisode]) -> bytes:
    fg = FeedGenerator()
    fg.load_extension("podcast")
    fg.title(meta.title)
    fg.description(meta.description)
    fg.link(href=meta.link, rel="alternate")
    fg.language("ko")
    fg.author({"name": meta.author})
    fg.logo(meta.image_url)
    fg.podcast.itunes_author(meta.author)
    fg.podcast.itunes_summary(meta.description)
    fg.podcast.itunes_explicit("no")
    fg.podcast.itunes_category(meta.category)
    fg.podcast.itunes_image(meta.image_url)

    for ep in episodes:
        fe = fg.add_entry()
        fe.id(f"youtube:{ep.video_id}")
        fe.guid(f"youtube:{ep.video_id}", permalink=False)
        fe.title(f"{ep.title} — {ep.channel}")
        fe.description(ep.summary)
        fe.link(href=ep.url)
        fe.published(isoparse(ep.published_at))
        fe.enclosure(ep.asset_url, str(ep.asset_bytes), "audio/mp4")
        fe.podcast.itunes_duration(_hhmmss(ep.duration_sec))
        fe.podcast.itunes_summary(ep.summary)

    return fg.rss_str(pretty=True)
