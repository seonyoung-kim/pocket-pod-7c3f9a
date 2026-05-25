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
