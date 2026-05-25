# pocket-pod 재설계 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 로컬 네트워크에서 구독하는 채널 큐레이션 podcast 도구. 채널 watchlist → yt-dlp flat extract scoring → Flask 웹 승인 → 백그라운드 m4a 다운로드 → Range 지원 정적 서버.

**Architecture:** `server.py` (`:8000`, RSS+m4a 정적) ↔ `app.py` (`:8001`, Flask 콘솔) ↔ `scripts/{state,watchlist,curator,downloader}.py` 라이브러리 ↔ `config/watchlist.yaml` + `data/state.json`. 단일 워커 스레드로 다운로드 직렬 처리.

**Tech Stack:** Python 3.11+, Flask, yt-dlp, feedgen, PyYAML, python-dateutil, pytest.

**Spec:** [`../specs/2026-05-25-pocket-pod-redesign.md`](../specs/2026-05-25-pocket-pod-redesign.md)

---

## Task 0: 폐기 자산 정리 + 의존성 재구성

폐기 결정된 파일들을 삭제하고 requirements/.gitignore를 새 스택에 맞게 정리한다. 이후 모든 작업의 베이스라인.

**Files:**
- Delete: `.github/workflows/curate.yml`
- Delete: `scripts/curate.py`, `scripts/gemini_client.py`, `scripts/youtube_client.py`, `scripts/publish.py`, `scripts/cleanup.py`, `scripts/download.py`
- Delete: `config/interests.yaml`
- Delete: `tests/test_cleanup_logic.py`
- Modify: `requirements.txt`
- Modify: `.gitignore`
- Create: `config/watchlist.yaml`
- Create: `data/.gitkeep`

- [ ] **Step 1: 폐기할 파일들 삭제**

```bash
git rm .github/workflows/curate.yml
git rm scripts/curate.py scripts/gemini_client.py scripts/youtube_client.py
git rm scripts/publish.py scripts/cleanup.py scripts/download.py
git rm config/interests.yaml
git rm tests/test_cleanup_logic.py
# .github 디렉토리가 비었으면 같이 제거
rmdir .github/workflows .github 2>/dev/null || true
```

- [ ] **Step 2: `requirements.txt` 갱신**

```
yt-dlp>=2025.1.1
feedgen==1.0.0
pyyaml==6.0.2
python-dateutil==2.9.0
flask>=3.0,<4.0
```

(`google-genai`, `google-api-python-client` 삭제됨)

- [ ] **Step 3: `.gitignore` 갱신**

기존 내용 끝에 다음 추가:

```
# runtime data
data/
!data/.gitkeep
feed.xml
*.bak
*.log
.venv/
__pycache__/
```

- [ ] **Step 4: 초기 `config/watchlist.yaml` 생성**

```yaml
defaults:
  lookback_days: 7
  top_k: 5

channels: []
```

- [ ] **Step 5: `data/` placeholder 생성**

```bash
mkdir -p data
touch data/.gitkeep
```

- [ ] **Step 6: 테스트가 여전히 통과하는지 확인**

```bash
pytest -v
```

Expected: PASS (`test_episode.py`, `test_rss_builder.py`만 남아있음)

- [ ] **Step 7: 커밋**

```bash
git add -A
git commit -m "chore: drop gemini/youtube-api/gh-actions assets, add watchlist scaffold"
```

---

## Task 1: `scripts/state.py` — state.json 영속화

State 도메인 dataclass와 atomic load/save. corrupt JSON 만나면 `.bak`에 손상본 보존하고 빈 state로 fresh start.

**Files:**
- Create: `scripts/state.py`
- Create: `tests/test_state.py`

- [ ] **Step 1: `tests/test_state.py` 작성 — load/save 라운드트립**

```python
from __future__ import annotations
import json
from pathlib import Path

from scripts.state import Candidate, State, StoredEpisode, SkippedEntry, load_state, save_state


def test_empty_state_when_file_missing(tmp_path: Path):
    s = load_state(tmp_path / "state.json")
    assert s.candidates == []
    assert s.skipped == []
    assert s.episodes == []
    assert s.in_progress == []
    assert s.last_errors == {}


def test_save_then_load_roundtrip(tmp_path: Path):
    p = tmp_path / "state.json"
    original = State(
        last_curated_at="2026-05-25T14:30:00+09:00",
        candidates=[Candidate(
            video_id="abc", channel_id="UCx", channel_name="Andrej",
            channel_alias="카파시", title="GPT-2", duration_sec=7234,
            view_count=100, upload_date="2026-05-20", days_old=5,
            url="https://youtu.be/abc", thumbnail_url="https://i/abc.jpg",
            score=100.0,
        )],
        skipped=[SkippedEntry(video_id="x", skipped_at="2026-05-24T11:00:00+09:00")],
        episodes=[StoredEpisode(
            video_id="y", title="t", channel="c", duration_sec=60,
            url="https://youtu.be/y", summary="s", published_at="2026-05-18T09:00:00Z",
            asset_filename="2026-05-18_y_t.m4a", asset_bytes=1234,
            downloaded_at="2026-05-25T14:35:00+09:00",
        )],
        in_progress=["z"],
        last_errors={"e": "msg"},
    )
    save_state(p, original)
    loaded = load_state(p)
    assert loaded == original


def test_corrupt_json_is_quarantined(tmp_path: Path):
    p = tmp_path / "state.json"
    p.write_text("{not json")
    s = load_state(p)
    assert s.candidates == []
    assert (p.with_suffix(".json.bak")).read_text() == "{not json"


def test_atomic_save_no_partial_on_failure(tmp_path: Path, monkeypatch):
    p = tmp_path / "state.json"
    save_state(p, State())
    original_bytes = p.read_bytes()
    # simulate replace failure mid-write
    import os
    real_replace = os.replace
    def boom(*a, **kw):
        raise RuntimeError("disk on fire")
    monkeypatch.setattr(os, "replace", boom)
    try:
        save_state(p, State(last_curated_at="2099-01-01T00:00:00+09:00"))
    except RuntimeError:
        pass
    assert p.read_bytes() == original_bytes
```

- [ ] **Step 2: 테스트 실행 → 실패 확인**

```bash
pytest tests/test_state.py -v
```

Expected: ImportError (state 모듈 없음)

- [ ] **Step 3: `scripts/state.py` 작성**

```python
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
```

- [ ] **Step 4: 테스트 실행 → PASS 확인**

```bash
pytest tests/test_state.py -v
```

Expected: 4 passed

- [ ] **Step 5: 커밋**

```bash
git add scripts/state.py tests/test_state.py
git commit -m "feat(state): atomic state.json persistence with corrupt-file quarantine"
```

---

## Task 2: `scripts/watchlist.py` — watchlist.yaml 영속화 + defaults merge

채널 추가/삭제 + per-channel override의 effective config 계산.

**Files:**
- Create: `scripts/watchlist.py`
- Create: `tests/test_watchlist.py`

- [ ] **Step 1: `tests/test_watchlist.py` 작성**

```python
from __future__ import annotations
from pathlib import Path

from scripts.watchlist import (
    ChannelEntry, Defaults, Watchlist, EffectiveConfig,
    load_watchlist, save_watchlist,
)


def test_empty_yaml_returns_baseline_defaults(tmp_path: Path):
    p = tmp_path / "watchlist.yaml"
    p.write_text("")
    wl = load_watchlist(p)
    assert wl.defaults == Defaults(lookback_days=7, top_k=5)
    assert wl.channels == []


def test_load_with_channels_and_overrides(tmp_path: Path):
    p = tmp_path / "watchlist.yaml"
    p.write_text(
        "defaults:\n"
        "  lookback_days: 10\n"
        "  top_k: 3\n"
        "channels:\n"
        "  - url: https://www.youtube.com/@a\n"
        "    alias: ay\n"
        "  - url: https://www.youtube.com/@b\n"
        "    lookback_days: 14\n"
    )
    wl = load_watchlist(p)
    assert wl.defaults.lookback_days == 10
    assert wl.defaults.top_k == 3
    assert len(wl.channels) == 2
    assert wl.channels[0].alias == "ay"
    assert wl.channels[1].lookback_days == 14


def test_effective_config_uses_defaults_when_unset(tmp_path: Path):
    wl = Watchlist(
        defaults=Defaults(lookback_days=7, top_k=5),
        channels=[
            ChannelEntry(url="u1", alias=None, lookback_days=None, top_k=None),
            ChannelEntry(url="u2", alias="b", lookback_days=14, top_k=3),
        ],
    )
    assert wl.effective(wl.channels[0]) == EffectiveConfig(lookback_days=7, top_k=5)
    assert wl.effective(wl.channels[1]) == EffectiveConfig(lookback_days=14, top_k=3)


def test_save_then_load_roundtrip(tmp_path: Path):
    p = tmp_path / "watchlist.yaml"
    original = Watchlist(
        defaults=Defaults(lookback_days=14, top_k=4),
        channels=[
            ChannelEntry(url="https://www.youtube.com/@x", alias="X",
                         lookback_days=None, top_k=None),
            ChannelEntry(url="https://www.youtube.com/@y", alias=None,
                         lookback_days=21, top_k=2),
        ],
    )
    save_watchlist(p, original)
    assert load_watchlist(p) == original


def test_add_remove_channel(tmp_path: Path):
    wl = Watchlist(defaults=Defaults(), channels=[])
    wl.add_channel(ChannelEntry(url="https://www.youtube.com/@a", alias=None,
                                lookback_days=None, top_k=None))
    assert len(wl.channels) == 1
    wl.add_channel(ChannelEntry(url="https://www.youtube.com/@a", alias="dup",
                                lookback_days=None, top_k=None))
    assert len(wl.channels) == 1  # 중복 URL은 무시 (no-op)
    wl.remove_channel("https://www.youtube.com/@a")
    assert wl.channels == []
```

- [ ] **Step 2: 테스트 실행 → 실패 확인**

```bash
pytest tests/test_watchlist.py -v
```

Expected: ImportError

- [ ] **Step 3: `scripts/watchlist.py` 작성**

```python
from __future__ import annotations
import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass(frozen=True)
class Defaults:
    lookback_days: int = 7
    top_k: int = 5


@dataclass
class ChannelEntry:
    url: str
    alias: str | None = None
    lookback_days: int | None = None
    top_k: int | None = None


@dataclass(frozen=True)
class EffectiveConfig:
    lookback_days: int
    top_k: int


@dataclass
class Watchlist:
    defaults: Defaults = field(default_factory=Defaults)
    channels: list[ChannelEntry] = field(default_factory=list)

    def effective(self, ch: ChannelEntry) -> EffectiveConfig:
        return EffectiveConfig(
            lookback_days=ch.lookback_days or self.defaults.lookback_days,
            top_k=ch.top_k or self.defaults.top_k,
        )

    def add_channel(self, ch: ChannelEntry) -> None:
        if any(c.url == ch.url for c in self.channels):
            return
        self.channels.append(ch)

    def remove_channel(self, url: str) -> None:
        self.channels = [c for c in self.channels if c.url != url]

    def to_dict(self) -> dict:
        return {
            "defaults": {
                "lookback_days": self.defaults.lookback_days,
                "top_k": self.defaults.top_k,
            },
            "channels": [
                {k: v for k, v in {
                    "url": c.url,
                    "alias": c.alias,
                    "lookback_days": c.lookback_days,
                    "top_k": c.top_k,
                }.items() if v is not None}
                for c in self.channels
            ],
        }


def load_watchlist(path: Path) -> Watchlist:
    if not path.exists():
        return Watchlist()
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    d = raw.get("defaults") or {}
    defaults = Defaults(
        lookback_days=int(d.get("lookback_days", 7)),
        top_k=int(d.get("top_k", 5)),
    )
    channels = [
        ChannelEntry(
            url=c["url"],
            alias=c.get("alias"),
            lookback_days=c.get("lookback_days"),
            top_k=c.get("top_k"),
        )
        for c in (raw.get("channels") or [])
    ]
    return Watchlist(defaults=defaults, channels=channels)


def save_watchlist(path: Path, wl: Watchlist) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        yaml.safe_dump(wl.to_dict(), sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    os.replace(tmp, path)
```

- [ ] **Step 4: 테스트 실행 → PASS**

```bash
pytest tests/test_watchlist.py -v
```

Expected: 5 passed

- [ ] **Step 5: 커밋**

```bash
git add scripts/watchlist.py tests/test_watchlist.py
git commit -m "feat(watchlist): yaml persistence with defaults merge"
```

---

## Task 3: `scripts/rss_builder.py` — description 본문 포맷 수정

기존 `<description>` 본문 = `ep.summary` 만 → `summary + 원본 URL` 조합으로 변경.

**Files:**
- Modify: `scripts/rss_builder.py` (`build_feed_xml` 함수 내부)
- Modify: `tests/test_rss_builder.py` (새 케이스 추가)

- [ ] **Step 1: `tests/test_rss_builder.py`에 검증 케이스 추가**

기존 파일 끝에 추가:

```python
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
```

- [ ] **Step 2: 테스트 실행 → 실패 확인**

```bash
pytest tests/test_rss_builder.py -v -k description
```

Expected: 2 failed (assertion 미스)

- [ ] **Step 3: `scripts/rss_builder.py` 수정**

`build_feed_xml` 함수의 episode 루프 안에서, 두 줄 교체:

```python
        # 기존:
        # fe.description(ep.summary)
        # ...
        # fe.podcast.itunes_summary(ep.summary)

        # 변경:
        body = ep.summary.strip() if ep.summary else "(설명 없음)"
        description = f"{body}\n\n원본: {ep.url}"
        fe.description(description)
        ...
        fe.podcast.itunes_summary(description)
```

전체 교체 후 함수는 다음과 같이 됨 (변경 부분만):

```python
    for ep in episodes:
        fe = fg.add_entry()
        fe.id(f"youtube:{ep.video_id}")
        fe.guid(f"youtube:{ep.video_id}", permalink=False)
        fe.title(f"{ep.title} — {ep.channel}")

        body = ep.summary.strip() if ep.summary else "(설명 없음)"
        description = f"{body}\n\n원본: {ep.url}"
        fe.description(description)

        fe.link(href=ep.url)
        fe.published(isoparse(ep.published_at))
        fe.enclosure(ep.asset_url, str(ep.asset_bytes), "audio/mp4")
        fe.podcast.itunes_duration(_hhmmss(ep.duration_sec))
        fe.podcast.itunes_summary(description)
```

- [ ] **Step 4: 테스트 전체 실행 → PASS**

```bash
pytest tests/test_rss_builder.py -v
```

Expected: 모든 테스트 PASS (기존 + 신규 2개)

- [ ] **Step 5: 커밋**

```bash
git add scripts/rss_builder.py tests/test_rss_builder.py
git commit -m "feat(rss): embed origin youtube url in episode description"
```

---

## Task 4: `scripts/curator.py` — yt-dlp 채널 추출 + scoring

채널 `/videos` 페이지를 flat extract로 받아 lookback/seen 필터 + view_count 정렬. CLI entrypoint 포함.

**Files:**
- Create: `scripts/curator.py`
- Create: `tests/test_curator.py`

- [ ] **Step 1: `tests/test_curator.py` 작성**

```python
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
```

- [ ] **Step 2: 테스트 실행 → 실패 확인**

```bash
pytest tests/test_curator.py -v
```

Expected: ImportError

- [ ] **Step 3: `scripts/curator.py` 작성**

```python
from __future__ import annotations
import argparse
import logging
import os
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from yt_dlp import YoutubeDL, DownloadError

from scripts.state import Candidate, State, load_state, save_state
from scripts.watchlist import ChannelEntry, Watchlist, load_watchlist


log = logging.getLogger(__name__)

_MOBILE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1"
)


@dataclass(frozen=True)
class VideoMeta:
    video_id: str
    channel_id: str
    channel_name: str
    title: str
    duration_sec: int
    view_count: int | None
    upload_date_yyyymmdd: str | None     # yt-dlp returns YYYYMMDD
    thumbnail_url: str


def _ytdl_opts(limit: int) -> dict:
    opts: dict = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": "in_playlist",
        "playlistend": limit,
        "http_headers": {"User-Agent": _MOBILE_UA},
        "extractor_args": {
            "youtube": {"player_client": ["tv_simply", "web_safari", "mweb"]}
        },
    }
    if cookies := os.environ.get("POCKET_POD_COOKIES"):
        opts["cookiefile"] = cookies
    if proxy := os.environ.get("POCKET_POD_PROXY"):
        opts["proxy"] = proxy
    return opts


def fetch_channel_videos(channel_url: str, limit: int,
                         channel_overrides: dict | None = None) -> list[VideoMeta]:
    """Fetch up to `limit` recent videos from a channel via yt-dlp flat extract."""
    target = channel_url.rstrip("/")
    if "/videos" not in target and "playlist?" not in target:
        target = f"{target}/videos"
    with YoutubeDL(_ytdl_opts(limit)) as ydl:
        info = ydl.extract_info(target, download=False)
    entries = info.get("entries") or []
    out: list[VideoMeta] = []
    for e in entries:
        if not e:
            continue
        out.append(VideoMeta(
            video_id=e.get("id") or "",
            channel_id=e.get("channel_id") or info.get("channel_id") or "",
            channel_name=e.get("channel") or info.get("channel") or "",
            title=e.get("title") or "",
            duration_sec=int(e.get("duration") or 0),
            view_count=e.get("view_count"),
            upload_date_yyyymmdd=e.get("upload_date"),
            thumbnail_url=(e.get("thumbnails") or [{}])[-1].get("url", ""),
        ))
    return out


def _parse_upload(yyyymmdd: str) -> date:
    return datetime.strptime(yyyymmdd, "%Y%m%d").date()


def _meta_to_candidate(m: VideoMeta, alias: str | None, today: date,
                       score: float | None = None) -> Candidate:
    up = _parse_upload(m.upload_date_yyyymmdd)
    return Candidate(
        video_id=m.video_id,
        channel_id=m.channel_id,
        channel_name=m.channel_name,
        channel_alias=alias or "",
        title=m.title,
        duration_sec=m.duration_sec,
        view_count=int(m.view_count or 0),
        upload_date=up.isoformat(),
        days_old=(today - up).days,
        url=f"https://www.youtube.com/watch?v={m.video_id}",
        thumbnail_url=m.thumbnail_url,
        score=float(score if score is not None else (m.view_count or 0)),
    )


def curate(watchlist: Watchlist, state: State) -> list[Candidate]:
    seen = ({e.video_id for e in state.episodes}
            | {s.video_id for s in state.skipped})
    today = date.today()
    all_cands: list[Candidate] = []

    for ch in watchlist.channels:
        cfg = watchlist.effective(ch)
        try:
            videos = fetch_channel_videos(ch.url, limit=cfg.top_k * 5)
        except DownloadError as e:
            log.warning("channel %s skipped: %s", ch.alias or ch.url, e)
            continue

        cutoff = today - timedelta(days=cfg.lookback_days)
        filtered: list[VideoMeta] = []
        for v in videos:
            if not v.upload_date_yyyymmdd or v.view_count is None:
                continue
            up = _parse_upload(v.upload_date_yyyymmdd)
            if up < cutoff:
                continue
            if v.video_id in seen:
                continue
            filtered.append(v)
        filtered.sort(key=lambda v: v.view_count or 0, reverse=True)
        for v in filtered[: cfg.top_k]:
            all_cands.append(_meta_to_candidate(v, ch.alias, today))

    all_cands.sort(key=lambda c: (c.upload_date, c.view_count), reverse=True)
    return all_cands


def run_curation(watchlist_path: Path, state_path: Path) -> int:
    watchlist = load_watchlist(watchlist_path)
    state = load_state(state_path)
    cands = curate(watchlist, state)
    state.candidates = cands
    state.last_curated_at = datetime.now(timezone(timedelta(hours=9))).isoformat()
    save_state(state_path, state)
    return len(cands)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="[%(name)s] %(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("--watchlist", default="config/watchlist.yaml")
    parser.add_argument("--state", default="data/state.json")
    args = parser.parse_args()
    n = run_curation(Path(args.watchlist), Path(args.state))
    print(f"[curator] {n} candidates written")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: 테스트 실행 → PASS**

```bash
pytest tests/test_curator.py -v
```

Expected: 6 passed

- [ ] **Step 5: 커밋**

```bash
git add scripts/curator.py tests/test_curator.py
git commit -m "feat(curator): yt-dlp flat extract + recent view_count scoring"
```

---

## Task 5: `scripts/downloader.py` — m4a 다운로드 + episodes append + feed 재생성

`download_one`은 단일 candidate를 m4a로 추출하고 `StoredEpisode`로 변환해 state.episodes에 append + feed.xml 재생성. 외부 호출(subprocess yt-dlp)은 인터페이스로 추상화해 테스트.

**Files:**
- Create: `scripts/downloader.py`
- Create: `tests/test_downloader.py`

- [ ] **Step 1: `tests/test_downloader.py` 작성**

```python
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
```

- [ ] **Step 2: 테스트 실행 → 실패 확인**

```bash
pytest tests/test_downloader.py -v
```

Expected: ImportError

- [ ] **Step 3: `scripts/downloader.py` 작성**

```python
from __future__ import annotations
import logging
import os
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Callable

from yt_dlp import YoutubeDL, DownloadError

from scripts.episode import _SLUG_RE
from scripts.rss_builder import FeedEpisode, FeedMeta, build_feed_xml
from scripts.state import Candidate, State, StoredEpisode, load_state, save_state


log = logging.getLogger(__name__)

_MAX_SUMMARY = 500
_MOBILE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1"
)


def _extract_summary(description: str) -> str:
    if not description:
        return ""
    first = description.strip().split("\n\n", 1)[0].strip()
    if len(first) > _MAX_SUMMARY:
        return first[:_MAX_SUMMARY]
    return first


def _asset_filename(c: Candidate, published_iso: str) -> str:
    slug = _SLUG_RE.sub("_", c.title)[:60].strip("_") or "untitled"
    return f"{published_iso[:10]}_{c.video_id}_{slug}.m4a"


def _now_kst_iso() -> str:
    return datetime.now(timezone(timedelta(hours=9))).isoformat()


def _ytdlp_meta(url: str) -> dict:
    opts: dict = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "http_headers": {"User-Agent": _MOBILE_UA},
        "extractor_args": {
            "youtube": {"player_client": ["tv_simply", "web_safari", "mweb"]}
        },
    }
    if cookies := os.environ.get("POCKET_POD_COOKIES"):
        opts["cookiefile"] = cookies
    if proxy := os.environ.get("POCKET_POD_PROXY"):
        opts["proxy"] = proxy
    with YoutubeDL(opts) as ydl:
        return ydl.extract_info(url, download=False)


def _ytdlp_download(url: str, out_path: Path) -> bool:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "yt-dlp",
        "-f", "bestaudio[ext=m4a]/bestaudio",
        "--extract-audio",
        "--audio-format", "m4a",
        "--no-playlist",
        "--no-progress",
        "--user-agent", _MOBILE_UA,
        "--extractor-args",
        "youtube:player_client=tv_simply,web_safari,mweb",
    ]
    if cookies := os.environ.get("POCKET_POD_COOKIES"):
        cmd += ["--cookies", cookies]
    if proxy := os.environ.get("POCKET_POD_PROXY"):
        cmd += ["--proxy", proxy]
    cmd += ["-o", str(out_path.with_suffix("")) + ".%(ext)s", url]
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as e:
        log.warning("yt-dlp failed: %s", (e.stderr or "")[-400:])
        return False
    return out_path.exists()


@dataclass
class DownloadDeps:
    """Injection seam for tests. Production defaults use yt-dlp."""
    fetch_meta: Callable[[str], dict]
    run_ytdlp:  Callable[[str, Path], bool]


def default_deps() -> DownloadDeps:
    return DownloadDeps(fetch_meta=_ytdlp_meta, run_ytdlp=_ytdlp_download)


def regenerate_feed(state: State, meta: FeedMeta, base_url: str, out_path: Path) -> None:
    feed_eps = [
        FeedEpisode(
            video_id=e.video_id,
            title=e.title,
            channel=e.channel,
            duration_sec=e.duration_sec,
            url=e.url,
            summary=e.summary,
            published_at=e.published_at,
            asset_url=f"{base_url.rstrip('/')}/data/downloads/{e.asset_filename}",
            asset_bytes=e.asset_bytes,
        )
        for e in state.episodes
    ]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(build_feed_xml(meta, feed_eps))


def download_one(
    *,
    candidate: Candidate,
    state_path: Path,
    downloads_dir: Path,
    feed_path: Path,
    feed_meta: FeedMeta,
    base_url: str,
    deps: DownloadDeps | None = None,
) -> bool:
    deps = deps or default_deps()
    state = load_state(state_path)
    # mark in_progress + clear prior error
    if candidate.video_id not in state.in_progress:
        state.in_progress.append(candidate.video_id)
    state.last_errors.pop(candidate.video_id, None)
    save_state(state_path, state)

    try:
        try:
            info = deps.fetch_meta(candidate.url)
        except DownloadError as e:
            raise RuntimeError(f"metadata fetch failed: {e}") from e

        summary = _extract_summary(info.get("description") or "")
        duration_sec = int(info.get("duration") or candidate.duration_sec)
        upload_yyyymmdd = info.get("upload_date") or candidate.upload_date.replace("-", "")
        published_iso = datetime.strptime(upload_yyyymmdd, "%Y%m%d") \
            .replace(tzinfo=timezone.utc).isoformat()

        asset_filename = _asset_filename(candidate, published_iso)
        asset_path = downloads_dir / asset_filename

        if not deps.run_ytdlp(candidate.url, asset_path):
            raise RuntimeError("yt-dlp download returned failure")

        asset_bytes = asset_path.stat().st_size
        episode = StoredEpisode(
            video_id=candidate.video_id,
            title=candidate.title,
            channel=candidate.channel_name,
            duration_sec=duration_sec,
            url=candidate.url,
            summary=summary,
            published_at=published_iso,
            asset_filename=asset_filename,
            asset_bytes=asset_bytes,
            downloaded_at=_now_kst_iso(),
        )

        # re-load to capture concurrent edits, then persist
        state = load_state(state_path)
        state.episodes.append(episode)
        state.candidates = [c for c in state.candidates if c.video_id != candidate.video_id]
        if candidate.video_id in state.in_progress:
            state.in_progress.remove(candidate.video_id)
        state.last_errors.pop(candidate.video_id, None)
        save_state(state_path, state)

        regenerate_feed(state, feed_meta, base_url, feed_path)
        return True

    except Exception as e:
        log.exception("download failed for %s", candidate.video_id)
        state = load_state(state_path)
        if candidate.video_id in state.in_progress:
            state.in_progress.remove(candidate.video_id)
        state.last_errors[candidate.video_id] = str(e)
        save_state(state_path, state)
        return False
```

- [ ] **Step 4: 테스트 실행 → PASS**

```bash
pytest tests/test_downloader.py -v
```

Expected: 4 passed

- [ ] **Step 5: 커밋**

```bash
git add scripts/downloader.py tests/test_downloader.py
git commit -m "feat(downloader): single-candidate m4a + episode append + feed regen"
```

---

## Task 6: `server.py` — Range 지원 정적 서버

기존 `/Users/jupiter/youtube_audio_tool/server.py`를 이식. 포트 8000, 0.0.0.0 바인딩, `data/` + `feed.xml` 서빙.

**Files:**
- Create: `server.py`
- Create: `tests/test_server.py`

- [ ] **Step 1: `tests/test_server.py` 작성**

```python
from __future__ import annotations
import socket
import threading
import time
import urllib.request
from pathlib import Path

import pytest

import server as srv


@pytest.fixture
def running_server(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "hello.m4a").write_bytes(b"abcdefghij")  # 10 bytes
    (tmp_path / "feed.xml").write_text("<rss/>")

    # find a free port
    s = socket.socket()
    s.bind(("", 0))
    port = s.getsockname()[1]
    s.close()

    httpd = srv.build_server(port)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    # give socket a beat to listen
    time.sleep(0.05)
    yield port
    httpd.shutdown()


def test_serves_feed(running_server):
    port = running_server
    body = urllib.request.urlopen(f"http://127.0.0.1:{port}/feed.xml").read()
    assert body == b"<rss/>"


def test_range_request_returns_206(running_server):
    port = running_server
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/data/hello.m4a",
        headers={"Range": "bytes=2-5"},
    )
    with urllib.request.urlopen(req) as resp:
        assert resp.status == 206
        assert resp.headers["Content-Range"] == "bytes 2-5/10"
        assert resp.read() == b"cdef"
```

- [ ] **Step 2: 테스트 실행 → 실패 확인**

```bash
pytest tests/test_server.py -v
```

Expected: ImportError

- [ ] **Step 3: `server.py` 작성**

```python
from __future__ import annotations
import http.server
import os
import re
import socketserver
import sys


PORT = int(os.environ.get("POCKET_POD_SERVER_PORT", "8000"))


class ThreadingHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class RangeRequestHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        path = self.translate_path(self.path)
        if not os.path.isfile(path):
            return super().do_GET()
        range_header = self.headers.get("Range")
        if not range_header:
            return super().do_GET()
        m = re.match(r"bytes=(\d+)-(\d*)", range_header)
        if not m:
            return super().do_GET()
        start = int(m.group(1))
        end = int(m.group(2)) if m.group(2) else os.path.getsize(path) - 1
        size = os.path.getsize(path)
        if start >= size:
            self.send_error(416, "Requested Range Not Satisfiable")
            return
        end = min(end, size - 1)
        self.send_response(206)
        self.send_header("Content-Type", self.guess_type(path))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.send_header("Content-Length", str(end - start + 1))
        self.end_headers()
        with open(path, "rb") as f:
            f.seek(start)
            remaining = end - start + 1
            buf = 64 * 1024
            while remaining > 0:
                chunk = f.read(min(remaining, buf))
                if not chunk:
                    break
                try:
                    self.wfile.write(chunk)
                except (ConnectionResetError, BrokenPipeError):
                    break
                remaining -= len(chunk)


def build_server(port: int) -> ThreadingHTTPServer:
    return ThreadingHTTPServer(("", port), RangeRequestHandler)


def main() -> int:
    cwd = os.environ.get("POCKET_POD_SERVER_ROOT") or os.path.dirname(
        os.path.abspath(__file__))
    os.chdir(cwd)
    httpd = build_server(PORT)
    print(f"[server] http://0.0.0.0:{PORT}  serving {cwd}", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        httpd.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: 테스트 실행 → PASS**

```bash
pytest tests/test_server.py -v
```

Expected: 2 passed

- [ ] **Step 5: 커밋**

```bash
git add server.py tests/test_server.py
git commit -m "feat(server): Range-aware static server (:8000) for rss + m4a"
```

---

## Task 7: `app.py` — Flask 콘솔 (라우트 + 단일 워커)

라우트별로 점진 추가. 백그라운드 워커는 `queue.Queue` + 데몬 스레드. Flask `test_client`로 라우트 smoke 테스트.

**Files:**
- Create: `app.py`
- Create: `tests/test_app.py`

- [ ] **Step 1: `tests/test_app.py` 작성**

```python
from __future__ import annotations
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts.state import Candidate, State, StoredEpisode, save_state
from scripts.watchlist import ChannelEntry, Defaults, Watchlist, save_watchlist


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("POCKET_POD_STATE_PATH", str(tmp_path / "state.json"))
    monkeypatch.setenv("POCKET_POD_WATCHLIST_PATH", str(tmp_path / "watchlist.yaml"))
    monkeypatch.setenv("POCKET_POD_DOWNLOADS_DIR", str(tmp_path / "downloads"))
    monkeypatch.setenv("POCKET_POD_FEED_PATH", str(tmp_path / "feed.xml"))
    monkeypatch.setenv("POCKET_POD_BASE_URL", "http://test:8000")
    save_watchlist(tmp_path / "watchlist.yaml", Watchlist())
    save_state(tmp_path / "state.json", State())

    import importlib, app as app_module
    importlib.reload(app_module)
    app_module.app.config["TESTING"] = True
    with app_module.app.test_client() as c:
        yield c, tmp_path, app_module


def test_index_empty_state_shows_hint(client):
    c, _, _ = client
    rv = c.get("/")
    assert rv.status_code == 200
    assert b"Refresh" in rv.data


def test_curate_route_triggers_curator_and_redirects(client):
    c, tmp_path, _ = client
    cand = Candidate(
        video_id="a", channel_id="UC", channel_name="A", channel_alias="",
        title="t", duration_sec=1, view_count=10, upload_date="2026-05-20",
        days_old=1, url="https://yt/a", thumbnail_url="", score=10.0,
    )
    with patch("app.run_curation", return_value=1) as m:
        # actually persist candidate so redirect page shows it
        def fake(wl, st):
            from scripts.state import load_state, save_state
            s = load_state(st)
            s.candidates = [cand]
            save_state(st, s)
            return 1
        m.side_effect = fake
        rv = c.post("/curate", follow_redirects=True)
    assert rv.status_code == 200
    assert b"a" in rv.data    # video_id rendered


def test_skip_marks_skipped_and_removes_from_candidates(client):
    c, tmp_path, _ = client
    from scripts.state import load_state, save_state
    s = load_state(tmp_path / "state.json")
    s.candidates = [Candidate(
        video_id="vv", channel_id="UC", channel_name="A", channel_alias="",
        title="t", duration_sec=1, view_count=10, upload_date="2026-05-20",
        days_old=1, url="https://yt/vv", thumbnail_url="", score=10.0,
    )]
    save_state(tmp_path / "state.json", s)

    rv = c.post("/skip/vv", follow_redirects=False)
    assert rv.status_code in (302, 303)
    s2 = load_state(tmp_path / "state.json")
    assert s2.candidates == []
    assert [x.video_id for x in s2.skipped] == ["vv"]


def test_watchlist_add_and_remove(client):
    c, tmp_path, _ = client
    rv = c.post("/watchlist/add", data={
        "url": "https://www.youtube.com/@karpathy",
        "alias": "카파시",
    }, follow_redirects=False)
    assert rv.status_code in (302, 303)
    from scripts.watchlist import load_watchlist
    wl = load_watchlist(tmp_path / "watchlist.yaml")
    assert [c2.url for c2 in wl.channels] == ["https://www.youtube.com/@karpathy"]

    rv = c.post("/watchlist/remove",
                data={"url": "https://www.youtube.com/@karpathy"})
    wl2 = load_watchlist(tmp_path / "watchlist.yaml")
    assert wl2.channels == []


def test_download_enqueues_and_marks_in_progress(client):
    c, tmp_path, app_module = client
    from scripts.state import load_state, save_state
    s = load_state(tmp_path / "state.json")
    cand = Candidate(
        video_id="dl", channel_id="UC", channel_name="A", channel_alias="",
        title="t", duration_sec=1, view_count=10, upload_date="2026-05-20",
        days_old=1, url="https://yt/dl", thumbnail_url="", score=10.0,
    )
    s.candidates = [cand]
    save_state(tmp_path / "state.json", s)

    # Replace worker function with a probe that records calls instead of running yt-dlp.
    captured = []
    def probe(candidate, **kw):
        captured.append(candidate.video_id)
        return True
    with patch.object(app_module, "download_one", side_effect=probe):
        rv = c.post("/download/dl", follow_redirects=False)
        assert rv.status_code in (302, 303)
        # drain the queue synchronously
        app_module.download_queue.join()
    assert captured == ["dl"]


def test_episodes_page_lists_downloaded(client):
    c, tmp_path, _ = client
    from scripts.state import load_state, save_state
    s = load_state(tmp_path / "state.json")
    s.episodes = [StoredEpisode(
        video_id="ep", title="hello", channel="ch", duration_sec=60,
        url="https://yt/ep", summary="s",
        published_at="2026-05-20T00:00:00+00:00",
        asset_filename="2026-05-20_ep_hello.m4a",
        asset_bytes=1234, downloaded_at="2026-05-25T00:00:00+09:00",
    )]
    save_state(tmp_path / "state.json", s)
    rv = c.get("/episodes")
    assert rv.status_code == 200
    assert b"hello" in rv.data
    assert b"2026-05-20_ep_hello.m4a" in rv.data
```

- [ ] **Step 2: 테스트 실행 → 실패 확인**

```bash
pytest tests/test_app.py -v
```

Expected: ImportError (app 모듈 없음)

- [ ] **Step 3: `app.py` 작성**

```python
from __future__ import annotations
import os
import queue
import threading
from datetime import datetime, timezone, timedelta
from pathlib import Path

from flask import Flask, redirect, render_template, request, url_for

from scripts.curator import run_curation
from scripts.downloader import default_deps, download_one
from scripts.rss_builder import FeedMeta
from scripts.state import Candidate, SkippedEntry, load_state, save_state
from scripts.watchlist import ChannelEntry, load_watchlist, save_watchlist


def _env_path(key: str, default: str) -> Path:
    return Path(os.environ.get(key, default))


STATE_PATH       = _env_path("POCKET_POD_STATE_PATH",     "data/state.json")
WATCHLIST_PATH   = _env_path("POCKET_POD_WATCHLIST_PATH", "config/watchlist.yaml")
DOWNLOADS_DIR    = _env_path("POCKET_POD_DOWNLOADS_DIR",  "data/downloads")
FEED_PATH        = _env_path("POCKET_POD_FEED_PATH",      "feed.xml")
BASE_URL         = os.environ.get("POCKET_POD_BASE_URL",  "http://localhost:8000")
FEED_TITLE       = os.environ.get("POCKET_POD_FEED_TITLE","pocket-pod")
FEED_AUTHOR      = os.environ.get("POCKET_POD_FEED_AUTHOR","pocket-pod")

FEED_META = FeedMeta(
    title=FEED_TITLE,
    description="Personal YouTube → audio podcast",
    link=BASE_URL,
    author=FEED_AUTHOR,
    image_url=f"{BASE_URL.rstrip('/')}/cover.png",
    category="Technology",
)


app = Flask(__name__)
download_queue: queue.Queue[Candidate] = queue.Queue()


def _kst_now() -> str:
    return datetime.now(timezone(timedelta(hours=9))).isoformat()


def _worker_loop():
    while True:
        cand = download_queue.get()
        try:
            download_one(
                candidate=cand,
                state_path=STATE_PATH,
                downloads_dir=DOWNLOADS_DIR,
                feed_path=FEED_PATH,
                feed_meta=FEED_META,
                base_url=BASE_URL,
                deps=default_deps(),
            )
        finally:
            download_queue.task_done()


_worker_thread = threading.Thread(target=_worker_loop, daemon=True)
_worker_thread.start()


# ---------- routes ----------

@app.route("/")
def index():
    state = load_state(STATE_PATH)
    return render_template(
        "candidates.html",
        state=state,
        base_url=BASE_URL,
    )


@app.route("/curate", methods=["POST"])
def curate():
    run_curation(WATCHLIST_PATH, STATE_PATH)
    return redirect(url_for("index"))


@app.route("/skip/<video_id>", methods=["POST"])
def skip(video_id: str):
    state = load_state(STATE_PATH)
    state.candidates = [c for c in state.candidates if c.video_id != video_id]
    if not any(s.video_id == video_id for s in state.skipped):
        state.skipped.append(SkippedEntry(video_id=video_id, skipped_at=_kst_now()))
    save_state(STATE_PATH, state)
    return redirect(url_for("index"))


@app.route("/download/<video_id>", methods=["POST"])
def download(video_id: str):
    state = load_state(STATE_PATH)
    cand = next((c for c in state.candidates if c.video_id == video_id), None)
    if cand is None:
        return redirect(url_for("index"))
    if video_id not in state.in_progress:
        state.in_progress.append(video_id)
        save_state(STATE_PATH, state)
    download_queue.put(cand)
    return redirect(url_for("index"))


@app.route("/watchlist", methods=["GET"])
def watchlist_page():
    wl = load_watchlist(WATCHLIST_PATH)
    return render_template("watchlist.html", watchlist=wl)


@app.route("/watchlist/add", methods=["POST"])
def watchlist_add():
    wl = load_watchlist(WATCHLIST_PATH)
    url = (request.form.get("url") or "").strip()
    if not url:
        return redirect(url_for("watchlist_page"))
    alias    = (request.form.get("alias") or "").strip() or None
    lookback = request.form.get("lookback_days") or None
    topk     = request.form.get("top_k") or None
    wl.add_channel(ChannelEntry(
        url=url,
        alias=alias,
        lookback_days=int(lookback) if lookback else None,
        top_k=int(topk) if topk else None,
    ))
    save_watchlist(WATCHLIST_PATH, wl)
    return redirect(url_for("watchlist_page"))


@app.route("/watchlist/remove", methods=["POST"])
def watchlist_remove():
    wl = load_watchlist(WATCHLIST_PATH)
    url = (request.form.get("url") or "").strip()
    wl.remove_channel(url)
    save_watchlist(WATCHLIST_PATH, wl)
    return redirect(url_for("watchlist_page"))


@app.route("/episodes")
def episodes_page():
    state = load_state(STATE_PATH)
    return render_template(
        "episodes.html",
        state=state,
        base_url=BASE_URL,
    )


@app.route("/episodes/delete/<video_id>", methods=["POST"])
def episode_delete(video_id: str):
    state = load_state(STATE_PATH)
    ep = next((e for e in state.episodes if e.video_id == video_id), None)
    if ep is not None:
        asset = DOWNLOADS_DIR / ep.asset_filename
        if asset.exists():
            asset.unlink()
        state.episodes = [e for e in state.episodes if e.video_id != video_id]
        save_state(STATE_PATH, state)
        from scripts.downloader import regenerate_feed
        regenerate_feed(state, FEED_META, BASE_URL, FEED_PATH)
    return redirect(url_for("episodes_page"))


def main() -> int:
    port = int(os.environ.get("POCKET_POD_APP_PORT", "8001"))
    app.run(host="0.0.0.0", port=port, debug=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: 템플릿이 없어서 라우트 테스트가 실패하므로 다음 Task에서 템플릿 추가 후 다시 실행. 우선 import만 검증**

```bash
python -c "import app; print('ok')"
```

Expected: `ok` (Flask 임포트 성공)

- [ ] **Step 5: 커밋 (템플릿은 다음 task)**

```bash
git add app.py tests/test_app.py
git commit -m "feat(app): flask routes + single-worker download queue (templates pending)"
```

---

## Task 8: Jinja2 템플릿 (`templates/`)

라우트와 한 셋트로 구현. 다음 4개 파일을 만들고 Task 7의 테스트를 마저 통과시킨다.

**Files:**
- Create: `templates/base.html`
- Create: `templates/candidates.html`
- Create: `templates/watchlist.html`
- Create: `templates/episodes.html`

- [ ] **Step 1: `templates/base.html`**

```html
<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <title>pocket-pod</title>
  <style>
    body { font-family: -apple-system, BlinkMacSystemFont, sans-serif;
           max-width: 920px; margin: 24px auto; padding: 0 16px; color: #222; }
    nav { display: flex; gap: 12px; padding: 8px 0; border-bottom: 1px solid #eee; }
    nav a { text-decoration: none; color: #444; }
    nav a.active { font-weight: 600; color: #000; }
    .feed-url { background: #f6f6f6; padding: 8px 12px; margin: 12px 0;
                font-family: monospace; font-size: 13px; }
    .card { display: flex; gap: 12px; padding: 12px 0; border-bottom: 1px solid #f0f0f0; }
    .card img { width: 168px; height: 95px; object-fit: cover; background: #ddd; }
    .card .meta { flex: 1; }
    .card h3 { margin: 0 0 4px; font-size: 16px; }
    .card .sub { color: #666; font-size: 13px; }
    .card .actions { margin-top: 8px; display: flex; gap: 8px; }
    button { font-size: 13px; padding: 4px 10px; cursor: pointer; }
    .badge-progress { color: #b65; }
    .badge-error { color: #c33; }
    form.inline { display: inline; }
    .empty { color: #999; padding: 24px 0; text-align: center; }
  </style>
</head>
<body>
  <nav>
    <a href="/" class="{{ 'active' if active == 'candidates' else '' }}">Candidates</a>
    <a href="/watchlist" class="{{ 'active' if active == 'watchlist' else '' }}">Watchlist</a>
    <a href="/episodes" class="{{ 'active' if active == 'episodes' else '' }}">Episodes</a>
  </nav>
  {% block body %}{% endblock %}
</body>
</html>
```

- [ ] **Step 2: `templates/candidates.html`**

```html
{% extends "base.html" %}
{% set active = "candidates" %}
{% block body %}
  <div class="feed-url">
    Subscribe: {{ base_url }}/feed.xml
  </div>

  <div style="display:flex; justify-content: space-between; align-items: center;">
    <div>Last curated: {{ state.last_curated_at or "—" }}</div>
    <form method="post" action="/curate" class="inline">
      <button type="submit">↻ Refresh Candidates</button>
    </form>
  </div>

  {% if not state.candidates %}
    <div class="empty">
      아직 큐레이션을 안 돌렸어. [Refresh Candidates] 눌러봐.
    </div>
  {% endif %}

  {% for c in state.candidates %}
    <div class="card">
      {% if c.thumbnail_url %}<img src="{{ c.thumbnail_url }}" alt="">{% endif %}
      <div class="meta">
        <h3>{{ c.title }}</h3>
        <div class="sub">
          {{ c.channel_alias or c.channel_name }}
          · {{ c.upload_date }} ({{ c.days_old }}d)
          · {{ "%d:%02d"|format(c.duration_sec // 60, c.duration_sec % 60) }}
        </div>
        <div class="sub">{{ "{:,}".format(c.view_count) }} views</div>
        <div class="actions">
          {% if c.video_id in state.in_progress %}
            <span class="badge-progress">⏳ downloading...</span>
          {% elif state.last_errors.get(c.video_id) %}
            <span class="badge-error">⚠ {{ state.last_errors[c.video_id] }}</span>
            <form method="post" action="/download/{{ c.video_id }}" class="inline">
              <button type="submit">↺ Retry</button>
            </form>
            <form method="post" action="/skip/{{ c.video_id }}" class="inline">
              <button type="submit">✕ Skip</button>
            </form>
          {% else %}
            <form method="post" action="/download/{{ c.video_id }}" class="inline">
              <button type="submit">▶ Download</button>
            </form>
            <form method="post" action="/skip/{{ c.video_id }}" class="inline">
              <button type="submit">✕ Skip</button>
            </form>
          {% endif %}
        </div>
      </div>
    </div>
  {% endfor %}
{% endblock %}
```

- [ ] **Step 3: `templates/watchlist.html`**

```html
{% extends "base.html" %}
{% set active = "watchlist" %}
{% block body %}
  <h2>Defaults</h2>
  <div class="sub">
    lookback_days = {{ watchlist.defaults.lookback_days }},
    top_k = {{ watchlist.defaults.top_k }}
    <em>(yaml 직접 편집)</em>
  </div>

  <h2>Channels ({{ watchlist.channels|length }})</h2>
  {% if not watchlist.channels %}
    <div class="empty">아직 등록한 채널이 없어.</div>
  {% endif %}
  {% for ch in watchlist.channels %}
    <div class="card">
      <div class="meta">
        <h3>{{ ch.alias or ch.url }}</h3>
        <div class="sub">{{ ch.url }}</div>
        <div class="sub">
          lookback: {{ ch.lookback_days or "default" }} ·
          top_k: {{ ch.top_k or "default" }}
        </div>
        <div class="actions">
          <form method="post" action="/watchlist/remove" class="inline">
            <input type="hidden" name="url" value="{{ ch.url }}">
            <button type="submit">Remove</button>
          </form>
        </div>
      </div>
    </div>
  {% endfor %}

  <h2>Add channel</h2>
  <form method="post" action="/watchlist/add">
    <p>URL <input name="url" size="60" required></p>
    <p>Alias <input name="alias"></p>
    <p>Lookback days <input name="lookback_days" size="4"> (비우면 default)</p>
    <p>Top K <input name="top_k" size="4"> (비우면 default)</p>
    <p><button type="submit">Add</button></p>
  </form>
{% endblock %}
```

- [ ] **Step 4: `templates/episodes.html`**

```html
{% extends "base.html" %}
{% set active = "episodes" %}
{% block body %}
  <div class="feed-url">
    Feed: <a href="/feed.xml">/feed.xml</a>
    · Served by server.py on {{ base_url }}
  </div>

  <h2>Episodes ({{ state.episodes|length }})</h2>
  {% if not state.episodes %}
    <div class="empty">아직 다운로드한 에피소드가 없어.</div>
  {% endif %}

  {% for ep in state.episodes|reverse %}
    <div class="card">
      <div class="meta">
        <h3>{{ ep.title }}</h3>
        <div class="sub">
          {{ ep.channel }}
          · {{ "%d:%02d"|format(ep.duration_sec // 60, ep.duration_sec % 60) }}
          · {{ "%.1f MB"|format(ep.asset_bytes / 1048576) }}
          · downloaded {{ ep.downloaded_at }}
        </div>
        <div class="sub">{{ ep.asset_filename }}</div>
        <div class="actions">
          <a href="{{ base_url }}/data/downloads/{{ ep.asset_filename }}"
             target="_blank">▶ Play</a>
          <form method="post" action="/episodes/delete/{{ ep.video_id }}"
                class="inline"
                onsubmit="return confirm('삭제하시겠습니까?');">
            <button type="submit">✕ Delete</button>
          </form>
        </div>
      </div>
    </div>
  {% endfor %}
{% endblock %}
```

- [ ] **Step 5: 테스트 실행 → PASS**

```bash
pytest tests/test_app.py -v
```

Expected: 6 passed

- [ ] **Step 6: 전체 테스트 통과 확인**

```bash
pytest -v
```

Expected: 전 테스트 PASS (state, watchlist, rss_builder, episode, curator, downloader, server, app)

- [ ] **Step 7: 커밋**

```bash
git add templates/
git commit -m "feat(ui): jinja templates for candidates/watchlist/episodes"
```

---

## Task 9: README 재작성

기존 README는 GitHub Actions/Pages 워크플로우 기준. 로컬 LAN 워크플로우로 재작성.

**Files:**
- Modify: `README.md` (전면 재작성)

- [ ] **Step 1: 새 `README.md` 작성**

```markdown
# pocket-pod

Personal YouTube → audio podcast pipeline that runs on **your LAN**.
Curates videos from a channel watchlist (recent + top view_count), extracts audio
with yt-dlp, publishes an iTunes-compatible RSS that local podcast apps can
subscribe to.

**Design:** [docs/superpowers/specs/2026-05-25-pocket-pod-redesign.md](docs/superpowers/specs/2026-05-25-pocket-pod-redesign.md)
**Plan:** [docs/superpowers/plans/2026-05-25-pocket-pod-impl.md](docs/superpowers/plans/2026-05-25-pocket-pod-impl.md)

## How it works

1. **Watchlist** — `config/watchlist.yaml`에 채널 등록. 웹 UI에서도 추가/삭제 가능.
2. **Curate** — `python -m scripts.curator` 또는 웹 UI의 [↻ Refresh Candidates]
   버튼이 각 채널의 최근 N일 영상을 yt-dlp flat extract로 가져와 조회수 상위 K개를
   후보로 제시.
3. **Approve** — 웹 콘솔 (`:8001`) 에서 후보에 [▶ Download] / [✕ Skip].
4. **Download** — 백그라운드 단일 워커가 m4a 추출 → `data/downloads/` 저장 →
   `feed.xml` 재생성.
5. **Subscribe** — 폰/태블릿의 podcast 앱에서 `http://<LAN IP>:8000/feed.xml` 구독.

## Quick start

```bash
git clone <repo>
cd pocket-pod
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 매번 실행
source .venv/bin/activate
POCKET_POD_BASE_URL=http://192.168.45.81:8000 python server.py &
POCKET_POD_BASE_URL=http://192.168.45.81:8000 python app.py
```

- 콘솔: <http://192.168.45.81:8001>
- 구독 URL: <http://192.168.45.81:8000/feed.xml>

## Environment variables

| 변수 | 용도 | 기본값 |
|------|------|--------|
| `POCKET_POD_BASE_URL` | RSS asset URL prefix | `http://localhost:8000` |
| `POCKET_POD_APP_PORT` | Flask 콘솔 포트 | `8001` |
| `POCKET_POD_SERVER_PORT` | 정적 서버 포트 | `8000` |
| `POCKET_POD_SERVER_ROOT` | 정적 서버 working dir | repo root |
| `POCKET_POD_STATE_PATH` | state.json 경로 | `data/state.json` |
| `POCKET_POD_WATCHLIST_PATH` | watchlist.yaml 경로 | `config/watchlist.yaml` |
| `POCKET_POD_DOWNLOADS_DIR` | 오디오 저장 디렉토리 | `data/downloads` |
| `POCKET_POD_FEED_PATH` | feed.xml 출력 | `feed.xml` |
| `POCKET_POD_FEED_TITLE` | RSS title | `pocket-pod` |
| `POCKET_POD_FEED_AUTHOR` | RSS author | `pocket-pod` |
| `POCKET_POD_COOKIES` | yt-dlp `--cookies` 경로 | — |
| `POCKET_POD_PROXY` | yt-dlp `--proxy` URL | — |

## Anti-bot

YouTube가 bot으로 의심해 `Sign in to confirm you're not a bot` 에러가 나면:

1. 브라우저에서 youtube.com 로그인 → `cookies.txt`로 export
2. `POCKET_POD_COOKIES=/path/to/cookies.txt` 지정

거주지 proxy가 있으면 `POCKET_POD_PROXY=http://...`도 가능.

## Tests

```bash
pytest -v
# 실제 yt-dlp 호출은 마커로 분리 (필요 시):
pytest -m integration
```

## Manual cleanup of old gh-pages assets

이전 GitHub Actions 흐름의 잔재(`gh-pages` 브랜치, weekly releases)를 정리하려면:

```bash
gh release list --limit 100
gh release delete <tag> --yes
git push origin :gh-pages
```
```

- [ ] **Step 2: 커밋**

```bash
git add README.md
git commit -m "docs: rewrite README for local LAN curation workflow"
```

---

## Task 10: 종단 smoke test + 운영 디렉토리 확인

실제 yt-dlp 호출은 안 하지만, 둘 다 띄워서 라우트가 살아있는지 + state/watchlist round-trip이 디스크에 반영되는지 수동 확인.

**Files:** (변경 없음, 검증만)

- [ ] **Step 1: 서버 부팅 확인 (두 터미널)**

터미널 A:
```bash
source .venv/bin/activate
POCKET_POD_BASE_URL=http://127.0.0.1:8000 python server.py
```
Expected stdout: `[server] http://0.0.0.0:8000  serving ...`

터미널 B:
```bash
source .venv/bin/activate
POCKET_POD_BASE_URL=http://127.0.0.1:8000 python app.py
```
Expected stdout: Flask 부팅 로그, `Running on http://0.0.0.0:8001`.

- [ ] **Step 2: 메인 페이지 확인**

```bash
curl -s http://127.0.0.1:8001/ | grep -E "Refresh Candidates|Subscribe"
```
Expected: 두 문자열 모두 매치

- [ ] **Step 3: watchlist 추가/조회**

```bash
curl -s -X POST -d "url=https://www.youtube.com/@AndrejKarpathy&alias=카파시" \
  http://127.0.0.1:8001/watchlist/add
curl -s http://127.0.0.1:8001/watchlist | grep -E "Karpathy|카파시"
cat config/watchlist.yaml
```
Expected:
- 응답에 채널 노출
- yaml에 `url: https://www.youtube.com/@AndrejKarpathy` 항목

- [ ] **Step 4: server.py가 정적 파일 서빙하는지 확인**

```bash
echo "<rss/>" > feed.xml
curl -sI http://127.0.0.1:8000/feed.xml | head -1
```
Expected: `HTTP/1.0 200 OK`

- [ ] **Step 5: 정리 + 커밋 없음**

수동 smoke test이므로 커밋할 변경 없음. 두 프로세스 Ctrl-C로 종료.

- [ ] **Step 6: 전체 테스트 마지막으로 한 번 더 통과 확인**

```bash
pytest -v
```
Expected: 전체 PASS

---

## Verification checklist (spec 요구 ↔ 구현)

이 plan을 끝낸 후 다음을 직접 확인:

- [ ] **§4 분리 구조** — `server.py`(:8000) ≠ `app.py`(:8001) 별 프로세스. (Task 6 + Task 7)
- [ ] **§5.1 watchlist.yaml + per-channel override** — Task 2 `EffectiveConfig`.
- [ ] **§5.2 state.json atomic write + corrupt 복구** — Task 1 `os.replace` + `.bak`.
- [ ] **§6.1 yt-dlp flat extract + anti-bot opts** — Task 4 `_ytdl_opts`.
- [ ] **§6.2 점수 = view_count + lookback 윈도우** — Task 4 `curate()`.
- [ ] **§6.3 lockfile/동시성** — `download_queue.put` 단일 워커로 직렬화 (Task 7). watchlist/state는 atomic write로 충돌 시 마지막 쓰기 승.
- [ ] **§7.1 9개 라우트** — Task 7.
- [ ] **§7.3 단일 워커 + in_progress 마킹** — Task 7 `_worker_loop`.
- [ ] **§8.1 description = summary + 원본 URL** — Task 3 + Task 5 `_extract_summary`.
- [ ] **§8.2 audio_filename 규칙** — Task 5 `_asset_filename` (`{YYYY-MM-DD}_{video_id}_{slug}.m4a`).
- [ ] **§8.3 자동 retention 없음** — Task 5에 cleanup 로직 없음. ✓
- [ ] **§9 에러 매트릭스** — `DownloadError`는 channel-skip (Task 4), download 실패는 `last_errors` 기록 (Task 5).
- [ ] **§10 테스트 구조** — Task 1~7의 각 test 파일.
- [ ] **§11.1 마이그레이션** — Task 0.
- [ ] **§12 실행** — README (Task 9).

---

## 실행 권장 순서

1. Task 0 (정리) — main에서 분기 후 가장 먼저
2. Task 1 → 2 → 3 (영속화 + RSS 본문) — 다른 모든 task의 의존성
3. Task 4 (curator) → Task 5 (downloader) — 라이브러리 레이어 완성
4. Task 6 (server) — Task 4/5에 의존 안 함, 병렬 가능
5. Task 7 + Task 8 (Flask + 템플릿) — 한 셋트
6. Task 9 (README)
7. Task 10 (smoke)
