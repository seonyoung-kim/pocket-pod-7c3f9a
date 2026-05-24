from __future__ import annotations
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError


_ISO_DURATION = re.compile(
    r"^PT(?:(?P<h>\d+)H)?(?:(?P<m>\d+)M)?(?:(?P<s>\d+)S)?$"
)


def _parse_iso_duration(s: str) -> int:
    m = _ISO_DURATION.match(s or "")
    if not m:
        return 0
    h = int(m.group("h") or 0)
    mi = int(m.group("m") or 0)
    se = int(m.group("s") or 0)
    return h * 3600 + mi * 60 + se


@dataclass(frozen=True)
class VideoCandidate:
    video_id: str
    title: str
    channel: str
    description: str
    duration_sec: int
    view_count: int
    published_at: datetime
    url: str


class YouTubeClient:
    def __init__(self, api_key: str | None = None):
        key = api_key or os.environ["YOUTUBE_API_KEY"]
        self._yt = build("youtube", "v3", developerKey=key, cache_discovery=False)

    def search_recent(
        self, query: str, recency_days: int, max_results: int = 20
    ) -> list[str]:
        """Return video IDs from search.list, no duration info yet."""
        published_after = (
            datetime.now(timezone.utc) - timedelta(days=recency_days)
        ).strftime("%Y-%m-%dT%H:%M:%SZ")
        resp = self._yt.search().list(
            q=query,
            part="id",
            type="video",
            order="relevance",
            maxResults=min(max_results, 50),
            publishedAfter=published_after,
        ).execute()
        return [it["id"]["videoId"] for it in resp.get("items", [])]

    def fetch_metadata(self, video_ids: Iterable[str]) -> list[VideoCandidate]:
        """Batch videos.list (max 50 per call) for full metadata."""
        ids = list(video_ids)
        out: list[VideoCandidate] = []
        for i in range(0, len(ids), 50):
            chunk = ids[i : i + 50]
            resp = self._yt.videos().list(
                id=",".join(chunk),
                part="snippet,contentDetails,statistics",
            ).execute()
            for item in resp.get("items", []):
                vid = item["id"]
                snip = item["snippet"]
                cd = item["contentDetails"]
                stats = item.get("statistics", {})
                out.append(
                    VideoCandidate(
                        video_id=vid,
                        title=snip["title"],
                        channel=snip["channelTitle"],
                        description=snip.get("description", ""),
                        duration_sec=_parse_iso_duration(cd.get("duration", "")),
                        view_count=int(stats.get("viewCount", 0)),
                        published_at=datetime.fromisoformat(
                            snip["publishedAt"].replace("Z", "+00:00")
                        ),
                        url=f"https://www.youtube.com/watch?v={vid}",
                    )
                )
        return out
