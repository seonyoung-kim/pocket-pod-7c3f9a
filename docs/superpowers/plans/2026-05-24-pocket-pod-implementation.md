# pocket-pod Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a personal YouTube → audio podcast pipeline that runs on GitHub Actions cron, curates videos via Gemini, and publishes an RSS feed to GitHub Pages for Apple Podcasts subscription.

**Architecture:** Single-purpose Python 3.11 scripts orchestrated by a GitHub Actions workflow. Each script writes JSON state to disk so the next stage can consume it. External services: YouTube Data API v3 (search), Gemini API (curation), `yt-dlp` (audio extraction), `gh` CLI (Releases + Pages).

**Tech Stack:** Python 3.11, `google-genai` (Gemini SDK), `google-api-python-client` (YouTube), `yt-dlp`, `feedgen` (RSS), `pyyaml`, `pytest`, GitHub Actions (Ubuntu), GitHub Releases, GitHub Pages.

---

## File Structure

```
pocket-pod/
├── .github/
│   └── workflows/
│       └── curate.yml              # cron + run
├── config/
│   └── interests.yaml              # 관심사 프로필
├── scripts/
│   ├── __init__.py
│   ├── episode.py                  # Episode dataclass
│   ├── youtube_client.py           # YouTube search.list wrapper
│   ├── gemini_client.py            # Gemini Flash + Pro wrappers
│   ├── rss_builder.py              # RSS XML generation
│   ├── curate.py                   # orchestrator: search + 2-stage Gemini → out/selected.json
│   ├── download.py                 # selected.json → out/audio/*.m4a
│   ├── publish.py                  # upload Release + regenerate RSS + push gh-pages
│   └── cleanup.py                  # delete releases older than N days
├── tests/
│   ├── __init__.py
│   ├── test_episode.py
│   ├── test_rss_builder.py
│   ├── test_cleanup_logic.py
│   └── fixtures/
│       └── sample_episodes.json
├── docs/
│   └── superpowers/
│       ├── specs/2026-05-24-pocket-pod-design.md   # already exists
│       └── plans/2026-05-24-pocket-pod-implementation.md   # this file
├── requirements.txt
├── requirements-dev.txt
├── pyproject.toml
├── .gitignore
├── .python-version
└── README.md
```

**Responsibility split:**
- `episode.py` — value type used across stages (no I/O)
- `youtube_client.py` — talks to YouTube only
- `gemini_client.py` — talks to Gemini only
- `rss_builder.py` — pure XML builder (no I/O, no network)
- `curate.py`, `download.py`, `publish.py`, `cleanup.py` — orchestrators that glue clients + fs

Files testable without network: `episode.py`, `rss_builder.py`, `cleanup.py` date logic.

---

## Task 1: Project scaffolding

**Files:**
- Create: `pyproject.toml`
- Create: `requirements.txt`
- Create: `requirements-dev.txt`
- Create: `.python-version`
- Create: `.gitignore`
- Create: `scripts/__init__.py` (empty)
- Create: `tests/__init__.py` (empty)

- [ ] **Step 1: Set Python version pin**

Create `.python-version`:
```
3.11
```

- [ ] **Step 2: Create runtime deps**

Create `requirements.txt`:
```
google-genai==0.3.0
google-api-python-client==2.149.0
yt-dlp>=2025.1.1
feedgen==1.0.0
pyyaml==6.0.2
python-dateutil==2.9.0
```

- [ ] **Step 3: Create dev deps**

Create `requirements-dev.txt`:
```
-r requirements.txt
pytest==8.3.4
pytest-mock==3.14.0
```

- [ ] **Step 4: Pyproject for pytest config**

Create `pyproject.toml`:
```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["."]
addopts = "-v"
```

- [ ] **Step 5: Gitignore**

Create `.gitignore`:
```
__pycache__/
*.pyc
.pytest_cache/
.venv/
venv/
out/
.DS_Store
*.m4a
```

- [ ] **Step 6: Create empty package markers**

Create `scripts/__init__.py` (empty file).
Create `tests/__init__.py` (empty file).

- [ ] **Step 7: Set up local venv and install deps**

Run:
```bash
cd ~/IdeaProjects/my/pocket-pod
python3.11 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements-dev.txt
```

Expected: all packages install without error.

- [ ] **Step 8: Verify pytest discovers nothing yet but runs cleanly**

Run: `.venv/bin/pytest`
Expected: `no tests ran in X.XXs` (exit code 5 is OK, means no tests)

- [ ] **Step 9: Commit**

```bash
git add pyproject.toml requirements.txt requirements-dev.txt .python-version .gitignore scripts/ tests/
git commit -m "chore: scaffold Python project + deps"
```

---

## Task 2: Episode dataclass

**Files:**
- Create: `scripts/episode.py`
- Create: `tests/test_episode.py`

- [ ] **Step 1: Write failing test for Episode**

Create `tests/test_episode.py`:
```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_episode.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'scripts.episode'`.

- [ ] **Step 3: Implement Episode**

Create `scripts/episode.py`:
```python
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
```

- [ ] **Step 4: Run test to verify pass**

Run: `.venv/bin/pytest tests/test_episode.py`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add scripts/episode.py tests/test_episode.py
git commit -m "feat(episode): add Episode value type with json roundtrip"
```

---

## Task 3: RSS builder

**Files:**
- Create: `scripts/rss_builder.py`
- Create: `tests/test_rss_builder.py`
- Create: `tests/fixtures/sample_episodes.json`

- [ ] **Step 1: Write fixture**

Create `tests/fixtures/sample_episodes.json`:
```json
[
  {
    "video_id": "aaa111BBB__",
    "title": "First episode",
    "channel": "Ch A",
    "duration_sec": 3661,
    "url": "https://www.youtube.com/watch?v=aaa111BBB__",
    "summary": "Summary of first.",
    "published_at": "2026-05-24T03:00:00+00:00",
    "score": 9.0,
    "asset_url": "https://github.com/owner/repo/releases/download/weekly-2026-05-24/2026-05-24_aaa111BBB___First_episode.m4a",
    "asset_bytes": 12345678
  },
  {
    "video_id": "bbb222CCC--",
    "title": "Second & special <chars>",
    "channel": "Ch B",
    "duration_sec": 600,
    "url": "https://www.youtube.com/watch?v=bbb222CCC--",
    "summary": "Has \"quotes\" and <html>.",
    "published_at": "2026-05-21T03:00:00+00:00",
    "score": 7.5,
    "asset_url": "https://github.com/owner/repo/releases/download/weekly-2026-05-21/2026-05-21_bbb222CCC---Second_special.m4a",
    "asset_bytes": 5000000
  }
]
```

- [ ] **Step 2: Write failing tests for rss_builder**

Create `tests/test_rss_builder.py`:
```python
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
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_rss_builder.py`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 4: Implement rss_builder**

Create `scripts/rss_builder.py`:
```python
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime

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
```

- [ ] **Step 5: Run tests to verify pass**

Run: `.venv/bin/pytest tests/test_rss_builder.py`
Expected: 6 passed.

- [ ] **Step 6: Commit**

```bash
git add scripts/rss_builder.py tests/test_rss_builder.py tests/fixtures/
git commit -m "feat(rss): generate iTunes-compatible RSS from episodes"
```

---

## Task 4: YouTube client

**Files:**
- Create: `scripts/youtube_client.py`

This module wraps `search.list` + `videos.list` calls. It is tested via integration smoke (manual run) in Task 7; no unit test here because mocking the Google client is heavier than the value it provides.

- [ ] **Step 1: Implement YouTubeClient**

Create `scripts/youtube_client.py`:
```python
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
```

- [ ] **Step 2: Sanity import check**

Run: `.venv/bin/python -c "from scripts.youtube_client import YouTubeClient, VideoCandidate; print('ok')"`
Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add scripts/youtube_client.py
git commit -m "feat(youtube): add search + metadata fetch wrapper"
```

---

## Task 5: Gemini client — Stage 1 (Flash, metadata scoring)

**Files:**
- Create: `scripts/gemini_client.py` (Stage 1 only this task; Stage 2 in Task 6)

- [ ] **Step 1: Implement Stage 1 scoring**

Create `scripts/gemini_client.py`:
```python
from __future__ import annotations
import json
import os
import time
from dataclasses import dataclass
from typing import Iterable

from google import genai
from google.genai import types


_FLASH_MODEL = "gemini-2.0-flash"
_PRO_MODEL = "gemini-2.5-pro"


@dataclass(frozen=True)
class Stage1Score:
    video_id: str
    score: float
    reason: str


@dataclass(frozen=True)
class Stage2Verdict:
    video_id: str
    score: float
    summary: str


class GeminiClient:
    def __init__(self, api_key: str | None = None):
        key = api_key or os.environ["GEMINI_API_KEY"]
        self._client = genai.Client(api_key=key)

    def score_candidates(
        self,
        interests_yaml_text: str,
        candidates: Iterable[dict],
    ) -> list[Stage1Score]:
        """Stage 1: rank candidates by metadata only.

        candidates: list of dicts {video_id, title, channel, description, duration_sec, view_count, published_at}
        Returns scored list (all candidates with 0-10 score).
        """
        cand_list = list(candidates)
        prompt = (
            "You are curating YouTube videos for a personal podcast feed.\n"
            "Below is the user's interest profile (YAML), followed by candidate videos.\n"
            "Score each candidate from 0 to 10 for how well it matches the interests.\n"
            "Return ONLY a JSON array, no markdown fences. "
            'Each element: {"video_id": str, "score": float, "reason": short str (Korean OK)}.\n\n'
            "=== INTERESTS ===\n"
            f"{interests_yaml_text}\n\n"
            "=== CANDIDATES ===\n"
            f"{json.dumps(cand_list, ensure_ascii=False, indent=2)}\n"
        )
        resp = self._client.models.generate_content(
            model=_FLASH_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.3,
            ),
        )
        data = json.loads(resp.text)
        return [
            Stage1Score(
                video_id=item["video_id"],
                score=float(item["score"]),
                reason=str(item.get("reason", "")),
            )
            for item in data
        ]

    def deep_analyze(self, video_url: str, interests_yaml_text: str) -> Stage2Verdict:
        """Stage 2 placeholder; implemented in Task 6."""
        raise NotImplementedError
```

- [ ] **Step 2: Sanity import check**

Run: `.venv/bin/python -c "from scripts.gemini_client import GeminiClient, Stage1Score; print('ok')"`
Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add scripts/gemini_client.py
git commit -m "feat(gemini): add Stage 1 metadata scoring (Flash)"
```

---

## Task 6: Gemini client — Stage 2 (Pro, video analysis)

**Files:**
- Modify: `scripts/gemini_client.py`

- [ ] **Step 1: Replace `deep_analyze` stub with real implementation**

In `scripts/gemini_client.py`, replace the `deep_analyze` method with:

```python
    def deep_analyze(self, video_url: str, interests_yaml_text: str) -> Stage2Verdict:
        """Stage 2: send YouTube URL as fileData; return summary + final score."""
        # Extract video_id from URL for the response
        video_id = video_url.split("watch?v=")[-1].split("&")[0]

        prompt = (
            "You are evaluating a single YouTube video for a personal podcast feed.\n"
            "Watch the video and judge how well it matches the interest profile below.\n"
            'Return ONLY a JSON object: {"score": float 0-10, "summary": "1-2 Korean sentences"}.\n\n'
            "=== INTERESTS ===\n"
            f"{interests_yaml_text}\n"
        )
        contents = types.Content(
            role="user",
            parts=[
                types.Part(file_data=types.FileData(file_uri=video_url)),
                types.Part(text=prompt),
            ],
        )
        resp = self._client.models.generate_content(
            model=_PRO_MODEL,
            contents=contents,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.3,
            ),
        )
        data = json.loads(resp.text)
        # Stage 2 rate limit: 5 RPM on free tier. Sleep to be safe.
        time.sleep(13)
        return Stage2Verdict(
            video_id=video_id,
            score=float(data["score"]),
            summary=str(data["summary"]),
        )
```

- [ ] **Step 2: Sanity import**

Run: `.venv/bin/python -c "from scripts.gemini_client import GeminiClient; print('ok')"`
Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add scripts/gemini_client.py
git commit -m "feat(gemini): add Stage 2 video analysis (Pro with fileData)"
```

---

## Task 7: curate.py orchestrator

**Files:**
- Create: `config/interests.yaml`
- Create: `scripts/curate.py`

- [ ] **Step 1: Create initial interests profile**

Create `config/interests.yaml`:
```yaml
keywords:
  - 희야기
excludes: []
duration:
  min_minutes: 5
  max_minutes: 90
recency_days: 14
top_n: 5
stage1_top_n: 10
```

- [ ] **Step 2: Implement curate.py**

Create `scripts/curate.py`:
```python
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

import yaml

from scripts.episode import Episode
from scripts.youtube_client import YouTubeClient, VideoCandidate
from scripts.gemini_client import GeminiClient


def _load_config(path: Path) -> dict:
    return yaml.safe_load(path.read_text())


def _within_duration(cand: VideoCandidate, cfg: dict) -> bool:
    lo = cfg["duration"]["min_minutes"] * 60
    hi = cfg["duration"]["max_minutes"] * 60
    return lo <= cand.duration_sec <= hi


def _excluded(cand: VideoCandidate, excludes: list[str]) -> bool:
    text = f"{cand.title} {cand.description}"
    return any(ex in text for ex in excludes)


def _collect_candidates(
    yt: YouTubeClient, cfg: dict
) -> list[VideoCandidate]:
    seen: set[str] = set()
    ids: list[str] = []
    for kw in cfg["keywords"]:
        for vid in yt.search_recent(kw, cfg["recency_days"], max_results=25):
            if vid not in seen:
                seen.add(vid)
                ids.append(vid)
    meta = yt.fetch_metadata(ids)
    return [m for m in meta if _within_duration(m, cfg) and not _excluded(m, cfg.get("excludes", []))]


def _candidate_to_dict(c: VideoCandidate) -> dict:
    return {
        "video_id": c.video_id,
        "title": c.title,
        "channel": c.channel,
        "description": c.description[:500],
        "duration_sec": c.duration_sec,
        "view_count": c.view_count,
        "published_at": c.published_at.isoformat(),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config/interests.yaml")
    parser.add_argument("--out", default="out/selected.json")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Stop after Stage 1 (no Pro calls, no fileData)",
    )
    args = parser.parse_args()

    cfg_path = Path(args.config)
    cfg = _load_config(cfg_path)
    interests_text = cfg_path.read_text()

    yt = YouTubeClient()
    gem = GeminiClient()

    print(f"[curate] collecting candidates for keywords={cfg['keywords']}", file=sys.stderr)
    candidates = _collect_candidates(yt, cfg)
    print(f"[curate] {len(candidates)} candidates after filter", file=sys.stderr)
    if not candidates:
        print("[curate] no candidates; exiting", file=sys.stderr)
        return 0

    cand_dicts = [_candidate_to_dict(c) for c in candidates]
    stage1 = gem.score_candidates(interests_text, cand_dicts)
    stage1_sorted = sorted(stage1, key=lambda s: s.score, reverse=True)
    top1 = stage1_sorted[: cfg["stage1_top_n"]]
    print(f"[curate] Stage 1 Top {len(top1)}: " + ", ".join(s.video_id for s in top1), file=sys.stderr)

    if args.dry_run:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(
            [{"video_id": s.video_id, "score": s.score, "reason": s.reason} for s in top1],
            ensure_ascii=False, indent=2,
        ))
        print(f"[curate] dry-run wrote {out_path}", file=sys.stderr)
        return 0

    cand_by_id = {c.video_id: c for c in candidates}
    verdicts = []
    for s1 in top1:
        cand = cand_by_id.get(s1.video_id)
        if cand is None:
            continue
        try:
            v = gem.deep_analyze(cand.url, interests_text)
            verdicts.append((cand, v))
            print(f"[curate] Stage 2 {cand.video_id} score={v.score:.1f}", file=sys.stderr)
        except Exception as e:
            print(f"[curate] Stage 2 failed for {cand.video_id}: {e}", file=sys.stderr)

    verdicts.sort(key=lambda x: x[1].score, reverse=True)
    selected = verdicts[: cfg["top_n"]]

    episodes = [
        Episode(
            video_id=c.video_id,
            title=c.title,
            channel=c.channel,
            duration_sec=c.duration_sec,
            url=c.url,
            summary=v.summary,
            published_at=c.published_at,
            score=v.score,
        )
        for c, v in selected
    ]

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(
        [ep.to_dict() for ep in episodes],
        ensure_ascii=False, indent=2,
    ))
    print(f"[curate] wrote {len(episodes)} episodes to {out_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 3: Local dry-run (requires keys in env)**

Run:
```bash
GEMINI_API_KEY=$(security find-generic-password -a "$USER" -s "pocket-pod-gemini-key" -w 2>/dev/null) \
YOUTUBE_API_KEY=$(security find-generic-password -a "$USER" -s "pocket-pod-youtube-key" -w 2>/dev/null) \
.venv/bin/python -m scripts.curate --dry-run
```

If you haven't stashed keys in Keychain, set them inline:
```bash
GEMINI_API_KEY=... YOUTUBE_API_KEY=... .venv/bin/python -m scripts.curate --dry-run
```

Expected: `out/selected.json` with up to 10 entries, each `{video_id, score, reason}`. Inspect a few reasons to confirm they make sense for "희야기".

- [ ] **Step 4: Commit**

```bash
git add config/interests.yaml scripts/curate.py
git commit -m "feat(curate): orchestrate YouTube search + Gemini 2-stage curation"
```

---

## Task 8: download.py

**Files:**
- Create: `scripts/download.py`

- [ ] **Step 1: Install ffmpeg locally (one-time)**

Run: `brew install ffmpeg` (skip if already installed).
Verify: `ffmpeg -version | head -1`
Expected: version line printed.

- [ ] **Step 2: Implement download.py**

Create `scripts/download.py`:
```python
from __future__ import annotations
import argparse
import json
import subprocess
import sys
from pathlib import Path

from scripts.episode import Episode


def download_episode(ep: Episode, out_dir: Path) -> Path | None:
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / ep.audio_filename()
    cmd = [
        "yt-dlp",
        "-f", "bestaudio[ext=m4a]/bestaudio",
        "--extract-audio",
        "--audio-format", "m4a",
        "--no-playlist",
        "--no-progress",
        "-o", str(out_path.with_suffix("")) + ".%(ext)s",
        ep.url,
    ]
    print(f"[download] {ep.video_id} → {out_path.name}", file=sys.stderr)
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as e:
        print(f"[download] FAILED {ep.video_id}: {e.stderr[-400:]}", file=sys.stderr)
        return None
    if not out_path.exists():
        print(f"[download] file missing after yt-dlp: {out_path}", file=sys.stderr)
        return None
    return out_path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--selected", default="out/selected.json")
    parser.add_argument("--out-dir", default="out/audio")
    parser.add_argument("--manifest", default="out/downloaded.json")
    args = parser.parse_args()

    selected_path = Path(args.selected)
    out_dir = Path(args.out_dir)

    raw = json.loads(selected_path.read_text())
    episodes = [Episode.from_dict(d) for d in raw]

    manifest: list[dict] = []
    for ep in episodes:
        path = download_episode(ep, out_dir)
        if path is None:
            continue
        entry = ep.to_dict()
        entry["audio_path"] = str(path)
        entry["asset_bytes"] = path.stat().st_size
        manifest.append(entry)

    manifest_path = Path(args.manifest)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    print(f"[download] manifest with {len(manifest)} entries → {manifest_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 3: Smoke test with the dry-run output**

You need a `selected.json` with full Episode shape (not the dry-run output). For smoke, manually craft one entry pointing at a short public domain video, e.g.:

```bash
cat > /tmp/smoke_selected.json <<'EOF'
[
  {
    "video_id": "_LZefzgZ6cw",
    "title": "Blender Foundation sample short",
    "channel": "sample",
    "duration_sec": 60,
    "url": "https://www.youtube.com/watch?v=_LZefzgZ6cw",
    "summary": "smoke",
    "published_at": "2026-01-01T00:00:00+00:00",
    "score": 5.0
  }
]
EOF
.venv/bin/python -m scripts.download --selected /tmp/smoke_selected.json --out-dir /tmp/pocket-pod-smoke --manifest /tmp/pocket-pod-manifest.json
```

Expected: `/tmp/pocket-pod-smoke/*.m4a` created, manifest written.
Clean up: `rm -rf /tmp/pocket-pod-smoke /tmp/pocket-pod-manifest.json /tmp/smoke_selected.json`

- [ ] **Step 4: Commit**

```bash
git add scripts/download.py
git commit -m "feat(download): extract audio with yt-dlp + write manifest"
```

---

## Task 9: publish.py — Release upload

**Files:**
- Create: `scripts/publish.py` (Release upload only; RSS + Pages in Task 10)

- [ ] **Step 1: Implement Release upload**

Create `scripts/publish.py`:
```python
from __future__ import annotations
import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def _gh(args: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(["gh", *args], check=True, capture_output=True, text=True, **kwargs)


def _repo() -> str:
    return os.environ.get("GH_REPO") or os.environ["GITHUB_REPOSITORY"]


def create_release(tag: str, title: str, notes: str) -> None:
    repo = _repo()
    try:
        _gh(["release", "view", tag, "--repo", repo])
        print(f"[publish] release {tag} already exists", file=sys.stderr)
    except subprocess.CalledProcessError:
        _gh([
            "release", "create", tag,
            "--repo", repo,
            "--title", title,
            "--notes", notes,
        ])
        print(f"[publish] created release {tag}", file=sys.stderr)


def upload_assets(tag: str, files: list[Path]) -> None:
    repo = _repo()
    args = ["release", "upload", tag, "--repo", repo, "--clobber", *[str(f) for f in files]]
    _gh(args)
    print(f"[publish] uploaded {len(files)} assets to {tag}", file=sys.stderr)


def asset_url(tag: str, filename: str) -> str:
    repo = _repo()
    return f"https://github.com/{repo}/releases/download/{tag}/{filename}"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", default="out/downloaded.json")
    parser.add_argument(
        "--tag",
        default=f"weekly-{datetime.now(timezone.utc).strftime('%Y-%m-%d')}",
    )
    args = parser.parse_args()

    manifest = json.loads(Path(args.manifest).read_text())
    if not manifest:
        print("[publish] empty manifest; nothing to publish", file=sys.stderr)
        return 0

    audio_files = [Path(e["audio_path"]) for e in manifest]
    titles = [f"- {e['title']} ({e['channel']})" for e in manifest]
    notes = "Curated episodes:\n" + "\n".join(titles)

    create_release(args.tag, f"Weekly {args.tag}", notes)
    upload_assets(args.tag, audio_files)

    # enrich manifest with asset URLs for RSS step
    enriched = []
    for e in manifest:
        path = Path(e["audio_path"])
        enriched.append({**e, "asset_url": asset_url(args.tag, path.name), "release_tag": args.tag})
    Path(args.manifest).write_text(json.dumps(enriched, ensure_ascii=False, indent=2))
    print(f"[publish] enriched manifest with asset URLs", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Sanity import**

Run: `.venv/bin/python -c "from scripts.publish import create_release, asset_url; print('ok')"`
Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add scripts/publish.py
git commit -m "feat(publish): create GitHub Release + upload assets"
```

---

## Task 10: publish.py — RSS regeneration + Pages push

**Files:**
- Modify: `scripts/publish.py` (extend `main()` to regenerate RSS from ALL active releases and push gh-pages)

- [ ] **Step 1: Add RSS regeneration helpers to publish.py**

In `scripts/publish.py`, add these functions above `main()`:

```python
import tempfile
import shutil

from scripts.rss_builder import build_feed_xml, FeedMeta, FeedEpisode


def list_all_releases() -> list[dict]:
    repo = _repo()
    p = _gh(["release", "list", "--repo", repo, "--limit", "100", "--json", "tagName,publishedAt,assets,name,body"])
    return json.loads(p.stdout)


def collect_feed_episodes_from_releases(releases: list[dict]) -> list[FeedEpisode]:
    """Build FeedEpisode list from release notes + asset metadata.

    Release notes are simple bullet lists; we don't parse them.
    Instead, we expect each release to have a sibling 'episodes.json' asset
    that publish.py uploaded — see Step 2.
    """
    out: list[FeedEpisode] = []
    repo = _repo()
    for rel in releases:
        tag = rel["tagName"]
        episodes_asset = next(
            (a for a in rel.get("assets", []) if a["name"] == "episodes.json"),
            None,
        )
        if episodes_asset is None:
            continue
        with tempfile.TemporaryDirectory() as td:
            local = Path(td) / "episodes.json"
            _gh(["release", "download", tag, "--repo", repo, "--pattern", "episodes.json", "--dir", td, "--clobber"])
            data = json.loads(local.read_text())
        for e in data:
            out.append(FeedEpisode(
                video_id=e["video_id"],
                title=e["title"],
                channel=e["channel"],
                duration_sec=e["duration_sec"],
                url=e["url"],
                summary=e["summary"],
                published_at=e["published_at"],
                asset_url=e["asset_url"],
                asset_bytes=e["asset_bytes"],
            ))
    out.sort(key=lambda e: e.published_at, reverse=True)
    return out


def publish_pages(feed_xml: bytes) -> None:
    """Push feed.xml + index.html to gh-pages branch via worktree."""
    repo = _repo()
    pages_url = f"https://{repo.split('/')[0]}.github.io/{repo.split('/')[1]}/"
    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        # Add gh-pages worktree
        subprocess.run(
            ["git", "fetch", "origin", "gh-pages"],
            capture_output=True,
        )
        branch_exists = subprocess.run(
            ["git", "show-ref", "--verify", "--quiet", "refs/remotes/origin/gh-pages"]
        ).returncode == 0
        if branch_exists:
            subprocess.run(
                ["git", "worktree", "add", str(td_path), "gh-pages"],
                check=True,
            )
        else:
            subprocess.run(
                ["git", "worktree", "add", "--orphan", "-b", "gh-pages", str(td_path)],
                check=True,
            )
            # Clean orphan worktree
            for child in td_path.iterdir():
                if child.name == ".git":
                    continue
                if child.is_dir():
                    shutil.rmtree(child)
                else:
                    child.unlink()
        (td_path / "feed.xml").write_bytes(feed_xml)
        (td_path / "index.html").write_text(
            f"<!doctype html><meta charset=utf-8><title>pocket-pod</title>"
            f"<h1>pocket-pod</h1><p>RSS: <a href=\"feed.xml\">feed.xml</a></p>"
        )
        (td_path / ".nojekyll").write_text("")
        subprocess.run(["git", "-C", str(td_path), "add", "-A"], check=True)
        # Allow empty commit (no changes) to avoid failure
        status = subprocess.run(
            ["git", "-C", str(td_path), "status", "--porcelain"],
            capture_output=True, text=True,
        )
        if status.stdout.strip():
            subprocess.run(
                ["git", "-C", str(td_path), "commit", "-m", f"publish feed @ {datetime.now(timezone.utc).isoformat()}"],
                check=True,
            )
            subprocess.run(
                ["git", "-C", str(td_path), "push", "origin", "gh-pages"],
                check=True,
            )
            print(f"[publish] pushed gh-pages; feed at {pages_url}feed.xml", file=sys.stderr)
        else:
            print("[publish] no changes to gh-pages", file=sys.stderr)
        subprocess.run(["git", "worktree", "remove", str(td_path), "--force"])
```

- [ ] **Step 2: Upload episodes.json alongside audio files**

In `main()`, BEFORE `create_release`, write an `episodes.json` to a temp path and add it to the upload list. Change the asset upload section to:

```python
    # Build episodes.json that future RSS generation will consume.
    # Append to manifest first so it has asset_url populated.
    # NOTE: we know asset_url before upload because we control the tag + filename.
    enriched_for_release = []
    for e in manifest:
        path = Path(e["audio_path"])
        enriched_for_release.append({
            "video_id": e["video_id"],
            "title": e["title"],
            "channel": e["channel"],
            "duration_sec": e["duration_sec"],
            "url": e["url"],
            "summary": e["summary"],
            "published_at": e["published_at"],
            "asset_url": asset_url(args.tag, path.name),
            "asset_bytes": e["asset_bytes"],
        })
    episodes_json = Path("out") / "episodes.json"
    episodes_json.write_text(json.dumps(enriched_for_release, ensure_ascii=False, indent=2))

    create_release(args.tag, f"Weekly {args.tag}", notes)
    upload_assets(args.tag, audio_files + [episodes_json])
```

Remove the old "enriched manifest" rewriting block — `episodes.json` on the release is now the source of truth.

- [ ] **Step 3: Add RSS regeneration + Pages push to main()**

At the end of `main()` (before `return 0`), add:

```python
    # Regenerate RSS from ALL active releases.
    releases = list_all_releases()
    feed_episodes = collect_feed_episodes_from_releases(releases)
    repo = _repo()
    owner, name = repo.split("/")
    meta = FeedMeta(
        title="pocket-pod",
        description="K's curated YouTube audio feed",
        link=f"https://{owner}.github.io/{name}/",
        author="K",
        image_url=f"https://{owner}.github.io/{name}/cover.png",
        category="Education",
    )
    feed_xml = build_feed_xml(meta, feed_episodes)
    publish_pages(feed_xml)
```

- [ ] **Step 4: Sanity import**

Run: `.venv/bin/python -c "from scripts.publish import main, list_all_releases, publish_pages; print('ok')"`
Expected: `ok`

- [ ] **Step 5: Enable GitHub Pages from gh-pages branch (one-time setup)**

Run:
```bash
gh api -X POST /repos/seonyoung-kim/pocket-pod-7c3f9a/pages \
  -f source.branch=gh-pages -f source.path=/ 2>&1 || echo "(may fail if branch does not yet exist; first publish will create it, then run this again)"
```

If it fails with 404 (branch doesn't exist), skip — we'll come back after the first publish run creates the branch.

- [ ] **Step 6: Commit**

```bash
git add scripts/publish.py
git commit -m "feat(publish): regenerate RSS from all releases + push gh-pages"
```

---

## Task 11: cleanup.py

**Files:**
- Create: `scripts/cleanup.py`
- Create: `tests/test_cleanup_logic.py`

- [ ] **Step 1: Write failing test for cutoff logic**

Create `tests/test_cleanup_logic.py`:
```python
from datetime import datetime, timezone, timedelta

from scripts.cleanup import should_delete


def test_release_older_than_cutoff_deleted():
    now = datetime(2026, 6, 1, tzinfo=timezone.utc)
    published = (now - timedelta(days=15)).isoformat()
    assert should_delete(published, retention_days=14, now=now) is True


def test_release_within_cutoff_kept():
    now = datetime(2026, 6, 1, tzinfo=timezone.utc)
    published = (now - timedelta(days=10)).isoformat()
    assert should_delete(published, retention_days=14, now=now) is False


def test_release_exactly_at_cutoff_kept():
    now = datetime(2026, 6, 1, tzinfo=timezone.utc)
    published = (now - timedelta(days=14)).isoformat()
    assert should_delete(published, retention_days=14, now=now) is False
```

- [ ] **Step 2: Run test, verify it fails**

Run: `.venv/bin/pytest tests/test_cleanup_logic.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'scripts.cleanup'`.

- [ ] **Step 3: Implement cleanup.py**

Create `scripts/cleanup.py`:
```python
from __future__ import annotations
import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone, timedelta

from dateutil.parser import isoparse


def should_delete(published_at_iso: str, retention_days: int, now: datetime) -> bool:
    published = isoparse(published_at_iso)
    return (now - published) > timedelta(days=retention_days)


def _gh(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(["gh", *args], check=True, capture_output=True, text=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--retention-days", type=int, default=14)
    parser.add_argument("--prefix", default="weekly-")
    args = parser.parse_args()

    repo = os.environ.get("GH_REPO") or os.environ["GITHUB_REPOSITORY"]
    now = datetime.now(timezone.utc)

    p = _gh(["release", "list", "--repo", repo, "--limit", "100", "--json", "tagName,publishedAt"])
    releases = json.loads(p.stdout)

    deleted = 0
    for rel in releases:
        tag = rel["tagName"]
        if not tag.startswith(args.prefix):
            continue
        if should_delete(rel["publishedAt"], args.retention_days, now):
            _gh(["release", "delete", tag, "--repo", repo, "--yes", "--cleanup-tag"])
            print(f"[cleanup] deleted {tag}", file=sys.stderr)
            deleted += 1

    print(f"[cleanup] deleted {deleted} release(s)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run test, verify pass**

Run: `.venv/bin/pytest tests/test_cleanup_logic.py`
Expected: 3 passed.

- [ ] **Step 5: Run all tests as regression check**

Run: `.venv/bin/pytest`
Expected: all tests pass (Episode + RSS + cleanup).

- [ ] **Step 6: Commit**

```bash
git add scripts/cleanup.py tests/test_cleanup_logic.py
git commit -m "feat(cleanup): delete releases older than retention window"
```

---

## Task 12: GitHub Actions workflow

**Files:**
- Create: `.github/workflows/curate.yml`

- [ ] **Step 1: Write the workflow**

Create `.github/workflows/curate.yml`:
```yaml
name: curate-and-publish
on:
  workflow_dispatch:
  schedule:
    # 06:00 KST Mon & Thu = 21:00 UTC Sun & Wed
    - cron: '0 21 * * 0,3'

permissions:
  contents: write
  pages: write
  id-token: write

concurrency:
  group: curate
  cancel-in-progress: false

jobs:
  run:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
          cache: pip
      - name: Install system deps
        run: |
          sudo apt-get update
          sudo apt-get install -y ffmpeg
      - name: Install Python deps
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt
      - name: Configure git (for gh-pages push)
        run: |
          git config user.name "pocket-pod-bot"
          git config user.email "actions@github.com"
      - name: Curate
        env:
          GEMINI_API_KEY: ${{ secrets.GEMINI_API_KEY }}
          YOUTUBE_API_KEY: ${{ secrets.YOUTUBE_API_KEY }}
        run: python -m scripts.curate
      - name: Download audio
        run: python -m scripts.download
      - name: Publish to Release + Pages
        env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          GH_REPO: ${{ github.repository }}
        run: python -m scripts.publish
      - name: Cleanup old releases
        env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          GH_REPO: ${{ github.repository }}
        run: python -m scripts.cleanup
```

- [ ] **Step 2: Lint workflow YAML locally (syntax only)**

Run:
```bash
.venv/bin/python -c "import yaml; yaml.safe_load(open('.github/workflows/curate.yml')); print('ok')"
```
Expected: `ok`

- [ ] **Step 3: Commit + push**

```bash
git add .github/workflows/curate.yml
git commit -m "feat(ci): add cron + manual workflow"
git push
```

---

## Task 13: README + first manual run

**Files:**
- Create: `README.md`

- [ ] **Step 1: Write README**

Create `README.md`:
```markdown
# pocket-pod

Personal YouTube → audio podcast pipeline. Curates videos via Gemini, extracts
audio with yt-dlp, publishes an iTunes-compatible RSS to GitHub Pages.

## How it works

1. GitHub Actions cron runs every Mon & Thu 06:00 KST (also manual trigger via Actions tab).
2. `scripts/curate.py` searches YouTube for `config/interests.yaml` keywords, scores via Gemini Flash, then deep-analyzes Top 10 with Gemini Pro → Top 5.
3. `scripts/download.py` extracts m4a audio with yt-dlp.
4. `scripts/publish.py` creates a GitHub Release (`weekly-YYYY-MM-DD`), uploads the m4a files + `episodes.json`, regenerates `feed.xml` from all active releases, pushes to `gh-pages` branch.
5. `scripts/cleanup.py` deletes releases older than 14 days.

## Subscribe (iPhone Apple Podcasts)

After the first run finishes:
1. `feed.xml` URL: `https://<owner>.github.io/<repo>/feed.xml`
2. iPhone → Podcasts → Library → top-right `…` → "Follow a Show by URL" → paste feed URL.

## Local dev

```bash
python3.11 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/pytest

# dry-run (stops after Stage 1, no Pro calls)
GEMINI_API_KEY=... YOUTUBE_API_KEY=... .venv/bin/python -m scripts.curate --dry-run
```

## Editing interests

`config/interests.yaml` — push changes to `main`, next cron picks them up.
```

- [ ] **Step 2: Commit + push**

```bash
git add README.md
git commit -m "docs: add README"
git push
```

- [ ] **Step 3: Trigger first run manually**

Run:
```bash
gh workflow run curate-and-publish --repo seonyoung-kim/pocket-pod-7c3f9a
sleep 5
gh run list --repo seonyoung-kim/pocket-pod-7c3f9a --workflow=curate-and-publish --limit 1
```

Expected: a run shows up in `in_progress` status.

- [ ] **Step 4: Watch the run**

Run:
```bash
gh run watch --repo seonyoung-kim/pocket-pod-7c3f9a $(gh run list --repo seonyoung-kim/pocket-pod-7c3f9a --workflow=curate-and-publish --limit 1 --json databaseId -q '.[0].databaseId')
```

Expected: all steps green. If any step fails, read the logs:
```bash
gh run view --repo seonyoung-kim/pocket-pod-7c3f9a --log-failed
```

Common first-run issues:
- **Pages step fails because gh-pages branch doesn't exist yet** → the publish.py script creates an orphan branch automatically; if the API call still 404s, re-enable Pages in repo Settings → Pages → Source = gh-pages.
- **YouTube quota exceeded** → wait 24h, then re-run.
- **yt-dlp HTTP 403** → bump yt-dlp version in requirements.txt to latest, push, re-run.

---

## Task 14: Enable Pages + Apple Podcasts subscription

- [ ] **Step 1: Enable GitHub Pages on gh-pages branch (after first publish)**

Run:
```bash
gh api -X POST /repos/seonyoung-kim/pocket-pod-7c3f9a/pages \
  -f source.branch=gh-pages -f source.path=/
```

If it returns `409 already exists`, that's fine. Verify:
```bash
gh api /repos/seonyoung-kim/pocket-pod-7c3f9a/pages | python -c "import json,sys; d=json.load(sys.stdin); print(d.get('html_url'), d.get('status'))"
```

Expected: prints the pages URL and `built` status.

- [ ] **Step 2: Verify feed is reachable**

Run:
```bash
curl -sI https://seonyoung-kim.github.io/pocket-pod-7c3f9a/feed.xml | head -5
```

Expected: `HTTP/2 200`. If `404`, wait 2-3 minutes (Pages build is async) and retry.

- [ ] **Step 3: Validate RSS structure**

Run:
```bash
curl -s https://seonyoung-kim.github.io/pocket-pod-7c3f9a/feed.xml | head -30
```

Expected: well-formed XML starting with `<?xml version="1.0" encoding="UTF-8"?>` and a `<channel>` with `<title>pocket-pod</title>`.

- [ ] **Step 4: Subscribe on iPhone**

1. iPhone → Podcasts app → Library tab → top-right `•••` (three dots) → "Follow a Show by URL…"
2. Paste: `https://seonyoung-kim.github.io/pocket-pod-7c3f9a/feed.xml`
3. Tap "Follow"
4. Episodes should appear within 1-2 minutes. Tap download icon (or set auto-download in show settings).

- [ ] **Step 5: Final verification**

Confirm on iPhone:
- Episodes appear with title, channel name, summary
- Audio plays
- Disable WiFi → cached episode plays offline

If all good, you're done. The cron will keep adding episodes every Mon & Thu.

---

## Operations notes

- **To pause publishing**: comment out the `schedule:` block in `curate.yml`. Manual `workflow_dispatch` still works.
- **To change keywords**: edit `config/interests.yaml`, commit, push. No restart needed; next cron picks up.
- **To force a fresh run**: Actions tab → curate-and-publish → "Run workflow" button.
- **If a single video errors**: check `gh run view --log-failed`. Failed downloads are skipped; failed Gemini Stage 2 calls also skip (other videos proceed).

---

## Self-review

**Spec coverage check:**
- §1 목적 → Tasks 1-14 deliver the end-to-end pipeline ✓
- §3 아키텍처 → Tasks 12 (workflow), 7-11 (scripts), 9-10 (Releases + Pages) ✓
- §4 데이터 흐름 (10 steps) → all mapped: search (T4), Stage 1/2 (T5, T6, T7), download (T8), release (T9), RSS (T10), Pages (T10/T14), cleanup (T11) ✓
- §5.1 interests.yaml → T7 Step 1 ✓
- §5.2 curate.py with dry-run + rate limit → T7 ✓
- §5.3 download.py with failure-skip → T8 ✓
- §5.4 publish.py with RSS regen → T9 + T10 ✓
- §5.5 cleanup.py idempotent → T11 ✓
- §5.6 workflow + Secrets + permissions → T12 ✓
- §6 Security: secrets via env, no hardcode → T12 ✓
- §7 Error handling table → covered in T7 (Stage 2 try/except), T8 (download skip), T10 (Pages no-op on empty), T11 (idempotent)
- §8 Test strategy: unit tests only for RSS + cleanup + Episode → T2, T3, T11 ✓
- §9 Initial sample (희야기) → T7 Step 1 ✓

**Placeholder scan:** No "TBD", no "implement later", no "similar to". Every code block is complete.

**Type consistency:** `Episode` fields are identical across episode.py / curate.py / download.py / publish.py (`video_id`, `title`, `channel`, `duration_sec`, `url`, `summary`, `published_at`, `score`). `FeedEpisode` adds `asset_url` + `asset_bytes` for the RSS stage; mapping is explicit in T10.

**Known follow-ups (not in scope):** cover image, multilingual support, weighted channels — listed in spec §10.
