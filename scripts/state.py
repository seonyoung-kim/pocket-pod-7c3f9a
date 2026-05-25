from __future__ import annotations
import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Candidate:
    video_id: str
    channel_id: str
    channel_name: str
    channel_alias: str
    title: str
    duration_sec: int
    view_count: int
    upload_date: str        # YYYY-MM-DD
    days_old: int
    url: str
    thumbnail_url: str
    score: float


@dataclass(frozen=True)
class SkippedEntry:
    video_id: str
    skipped_at: str         # ISO 8601


@dataclass(frozen=True)
class StoredEpisode:
    video_id: str
    title: str
    channel: str
    duration_sec: int
    url: str
    summary: str
    published_at: str       # ISO 8601
    asset_filename: str
    asset_bytes: int
    downloaded_at: str      # ISO 8601


@dataclass
class State:
    version: int = 1
    last_curated_at: str | None = None
    candidates: list[Candidate] = field(default_factory=list)
    skipped: list[SkippedEntry] = field(default_factory=list)
    episodes: list[StoredEpisode] = field(default_factory=list)
    in_progress: list[str] = field(default_factory=list)
    last_errors: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "last_curated_at": self.last_curated_at,
            "candidates": [asdict(c) for c in self.candidates],
            "skipped": [asdict(s) for s in self.skipped],
            "episodes": [asdict(e) for e in self.episodes],
            "in_progress": list(self.in_progress),
            "last_errors": dict(self.last_errors),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "State":
        return cls(
            version=int(d.get("version", 1)),
            last_curated_at=d.get("last_curated_at"),
            candidates=[Candidate(**c) for c in d.get("candidates", [])],
            skipped=[SkippedEntry(**s) for s in d.get("skipped", [])],
            episodes=[StoredEpisode(**e) for e in d.get("episodes", [])],
            in_progress=list(d.get("in_progress", [])),
            last_errors=dict(d.get("last_errors", {})),
        )


def load_state(path: Path) -> State:
    if not path.exists():
        return State()
    raw = path.read_text(encoding="utf-8")
    try:
        return State.from_dict(json.loads(raw))
    except (json.JSONDecodeError, TypeError, KeyError):
        path.with_suffix(".json.bak").write_text(raw, encoding="utf-8")
        return State()


def save_state(path: Path, state: State) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(state.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(tmp, path)
