from __future__ import annotations
from dataclasses import dataclass, asdict
from datetime import datetime
import re

from dateutil.parser import isoparse


_SLUG_RE = re.compile(r"[^0-9A-Za-z._-]+")


@dataclass(frozen=True)
class Episode:
    video_id: str
    title: str
    channel: str
    duration_sec: int
    url: str
    summary: str
    published_at: datetime
    score: float

    def to_dict(self) -> dict:
        d = asdict(self)
        d["published_at"] = self.published_at.isoformat()
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Episode":
        return cls(
            video_id=d["video_id"],
            title=d["title"],
            channel=d["channel"],
            duration_sec=int(d["duration_sec"]),
            url=d["url"],
            summary=d["summary"],
            published_at=isoparse(d["published_at"]),
            score=float(d["score"]),
        )

    def audio_filename(self) -> str:
        slug = _SLUG_RE.sub("_", self.title)[:60].strip("_") or "untitled"
        date = self.published_at.strftime("%Y-%m-%d")
        return f"{date}_{self.video_id}_{slug}.m4a"
