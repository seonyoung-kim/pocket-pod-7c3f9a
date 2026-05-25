from __future__ import annotations
import logging
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Callable

from yt_dlp import YoutubeDL, DownloadError

from scripts.episode import _SLUG_RE
from scripts.rss_builder import FeedEpisode, FeedMeta, build_feed_xml
from scripts.state import Candidate, State, StoredEpisode, load_state, save_state


log = logging.getLogger(__name__)


def _ytdlp_binary() -> str:
    """LaunchAgent 같은 PATH 가 빈약한 환경에서도 venv 의 yt-dlp 를 찾을 수 있게.
    1) sys.executable 옆의 yt-dlp (venv)  2) PATH lookup  3) "yt-dlp" raw fallback."""
    candidate = Path(sys.executable).parent / "yt-dlp"
    if candidate.exists():
        return str(candidate)
    return shutil.which("yt-dlp") or "yt-dlp"


def _ffmpeg_location() -> str | None:
    """yt-dlp 가 m4a post-process 시 ffmpeg/ffprobe 필요. LaunchAgent PATH 가
    homebrew bin 을 포함하지 않으므로 위치 명시. 환경변수 override 가능."""
    if env := os.environ.get("POCKET_POD_FFMPEG"):
        return env
    for path in ("/opt/homebrew/bin", "/usr/local/bin", "/usr/bin"):
        if (Path(path) / "ffmpeg").exists():
            return path
    return None

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
    """description / duration / upload_date 만 필요한 metadata fetch.
    `process=False` 로 format selection 단계를 건너뛴다 (player_client/format
    옵션이 metadata-only fetch 와 충돌하는 케이스 회피)."""
    opts: dict = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
    }
    if cookies := os.environ.get("POCKET_POD_COOKIES"):
        opts["cookiefile"] = cookies
    if proxy := os.environ.get("POCKET_POD_PROXY"):
        opts["proxy"] = proxy
    with YoutubeDL(opts) as ydl:
        return ydl.extract_info(url, download=False, process=False)


def _ytdlp_download(url: str, out_path: Path) -> bool:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # 기본 player_client (yt-dlp default) 사용. tv_simply/web_safari/mweb 명시는
    # 일부 영상에서 GVS PO Token 요구로 audio stream 접근이 막힌다. cookies/proxy
    # env 가 있으면 그쪽이 anti-bot 우회를 담당.
    cmd = [
        _ytdlp_binary(),
        "-f", "bestaudio[ext=m4a]/bestaudio",
        "--extract-audio",
        "--audio-format", "m4a",
        "--no-playlist",
        "--no-progress",
        "--user-agent", _MOBILE_UA,
    ]
    if ffmpeg_dir := _ffmpeg_location():
        cmd += ["--ffmpeg-location", ffmpeg_dir]
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
        asset_path.parent.mkdir(parents=True, exist_ok=True)

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
