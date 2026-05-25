from __future__ import annotations
import argparse
import logging
import os
import re
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit, quote

from yt_dlp import YoutubeDL, DownloadError

from scripts.state import Candidate, State, load_state, save_state
from scripts.watchlist import ChannelEntry, Watchlist, load_watchlist


_VIDEO_ID_PATTERNS = [
    re.compile(r"youtube\.com/watch\?[^#]*?v=([A-Za-z0-9_-]{11})"),
    re.compile(r"youtu\.be/([A-Za-z0-9_-]{11})"),
    re.compile(r"youtube\.com/shorts/([A-Za-z0-9_-]{11})"),
    re.compile(r"youtube\.com/embed/([A-Za-z0-9_-]{11})"),
    re.compile(r"^([A-Za-z0-9_-]{11})$"),
]


def extract_video_id(url_or_id: str) -> str | None:
    """YouTube URL 또는 video_id 11자 토큰에서 video_id 추출."""
    s = (url_or_id or "").strip()
    for pat in _VIDEO_ID_PATTERNS:
        m = pat.search(s)
        if m:
            return m.group(1)
    return None


log = logging.getLogger(__name__)

_MOBILE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1"
)


def _safe_channel_url(channel_url: str) -> str:
    """yt-dlp 가 한글 핸들 URL을 raw로 받으면 인식 실패한다.
    path만 percent-encode 하되 이미 인코딩된 `%XX`는 그대로 둔다."""
    parts = urlsplit(channel_url)
    safe_path = quote(parts.path, safe="/@-._~%")
    return urlunsplit(parts._replace(path=safe_path))


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
    # 채널 /videos 는 tab 페이지. mobile UA 와 player_client 옵션은 둘 다
    # tab 페이지 파서와 호환되지 않아 "Unable to recognize tab page" 를 일으킨다.
    # 두 옵션은 영상 단위 deep fetch / download 쪽에만 적용한다.
    opts: dict = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": "in_playlist",
        "playlistend": limit,
    }
    if cookies := os.environ.get("POCKET_POD_COOKIES"):
        opts["cookiefile"] = cookies
    if proxy := os.environ.get("POCKET_POD_PROXY"):
        opts["proxy"] = proxy
    return opts


def _ytdlp_video_meta(video_id: str) -> dict:
    """단일 영상의 deep metadata. flat extract에서 누락된 필드 보강용.
    `process=False` 로 호출해 format selection 단계를 건너뛴다
    (player_client/format 옵션이 metadata-only fetch와 충돌해 "Requested format is
    not available"을 일으키는 경우를 회피)."""
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
        return ydl.extract_info(
            f"https://www.youtube.com/watch?v={video_id}",
            download=False, process=False)


def _enrich_if_missing(v: VideoMeta) -> VideoMeta:
    """flat extract에서 view_count 또는 upload_date가 비면 deep fetch로 보강.
    deep fetch도 실패하거나 여전히 비면 원본 그대로 반환 (상위 필터가 제외)."""
    if v.view_count is not None and v.upload_date_yyyymmdd:
        return v
    if not v.video_id:
        return v
    try:
        info = _ytdlp_video_meta(v.video_id)
    except DownloadError as e:
        log.warning("deep meta failed for %s: %s", v.video_id, e)
        return v
    return VideoMeta(
        video_id=v.video_id,
        channel_id=info.get("channel_id") or v.channel_id,
        channel_name=info.get("channel") or v.channel_name,
        title=info.get("title") or v.title,
        duration_sec=int(info.get("duration") or v.duration_sec),
        view_count=v.view_count if v.view_count is not None else info.get("view_count"),
        upload_date_yyyymmdd=v.upload_date_yyyymmdd or info.get("upload_date"),
        thumbnail_url=v.thumbnail_url or info.get("thumbnail", ""),
    )


def video_id_to_candidate(video_id: str, alias: str | None = None) -> Candidate:
    """수동 추가용: video_id 만으로 deep fetch 해서 Candidate 생성.
    anti-bot 등으로 fetch 실패하면 DownloadError 전파."""
    info = _ytdlp_video_meta(video_id)
    today = date.today()
    upload_yyyymmdd = info.get("upload_date") or today.strftime("%Y%m%d")
    up = _parse_upload(upload_yyyymmdd)
    view_count = int(info.get("view_count") or 0)
    return Candidate(
        video_id=video_id,
        channel_id=info.get("channel_id") or "",
        channel_name=info.get("channel") or info.get("uploader") or "",
        channel_alias=alias or "",
        title=info.get("title") or "",
        duration_sec=int(info.get("duration") or 0),
        view_count=view_count,
        upload_date=up.isoformat(),
        days_old=(today - up).days,
        url=f"https://www.youtube.com/watch?v={video_id}",
        thumbnail_url=info.get("thumbnail") or "",
        score=float(view_count),
    )


def fetch_channel_videos(channel_url: str, limit: int,
                         channel_overrides: dict | None = None) -> list[VideoMeta]:
    """Fetch up to `limit` recent videos from a channel via yt-dlp flat extract."""
    target = _safe_channel_url(channel_url.rstrip("/"))
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
    return [_enrich_if_missing(v) for v in out]


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
