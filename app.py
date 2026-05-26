from __future__ import annotations
import os
import queue
import socket
import threading
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import urlparse

from flask import Flask, flash, redirect, render_template, request, url_for

from scripts.curator import extract_video_id, run_curation, video_id_to_candidate
from scripts.downloader import default_deps, download_one, regenerate_feed
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
FEED_IMAGE_URL   = os.environ.get(
    "POCKET_POD_FEED_IMAGE_URL",
    f"{BASE_URL.rstrip('/')}/cover.png",
)

FEED_META = FeedMeta(
    title=FEED_TITLE,
    description="Personal YouTube → audio podcast",
    link=BASE_URL,
    author=FEED_AUTHOR,
    image_url=FEED_IMAGE_URL,
    category="Technology",
)


app = Flask(__name__)
app.secret_key = os.environ.get("POCKET_POD_SECRET", "pocket-pod-dev-secret")
download_queue: queue.Queue[Candidate] = queue.Queue()

# /curate 중복 호출 방어 — non-blocking lock + flag.
_curate_lock = threading.Lock()
_curate_running = False


def _detect_lan_ip() -> str:
    """현재 머신의 외부향 LAN IP. UDP 소켓 'connect' 는 패킷을 보내지 않고
    OS 라우팅 테이블만 조회하므로 오프라인이어도 부담 없다."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


SERVER_PORT = int(os.environ.get("POCKET_POD_SERVER_PORT", "8000"))
APP_PORT    = int(os.environ.get("POCKET_POD_APP_PORT",    "8001"))


def _live_base_url() -> str:
    """feed.xml 의 asset_url / image_url 에 박을 base. 네트워크 IP 가 바뀌어도
    매 호출마다 새 LAN IP 를 사용하므로 재시작 없이 따라간다."""
    return f"http://{_detect_lan_ip()}:{SERVER_PORT}"


def _live_feed_meta(base_url: str) -> FeedMeta:
    return FeedMeta(
        title=FEED_TITLE,
        description="Personal YouTube → audio podcast",
        link=base_url,
        author=FEED_AUTHOR,
        image_url=f"{base_url.rstrip('/')}/cover.png",
        category="Technology",
    )


@app.context_processor
def _inject_feed_meta() -> dict:
    """모든 템플릿에서 podcast cover / title / curate 진행 상태를 사용 가능."""
    lan_ip = _detect_lan_ip()
    live_base = f"http://{lan_ip}:{SERVER_PORT}"
    env_host = urlparse(BASE_URL).hostname or ""
    return {
        "feed_title": FEED_TITLE,
        "feed_image_url": f"{live_base}/cover.png",
        "curate_running": _curate_running,
        "lan_ip": lan_ip,
        "server_port": SERVER_PORT,
        "app_port": APP_PORT,
        "live_base_url": live_base,
        # POCKET_POD_BASE_URL 환경변수(plist 에 박혀있을 수 있음)와 현재 LAN IP 가
        # 다르면 사용자에게 알려준다. 실제 feed.xml 은 live IP 로 재생성되므로
        # 동작에는 문제 없지만, 설정 정리 필요성을 인지시키기 위함.
        "base_url_stale": bool(env_host) and env_host != lan_ip,
        "base_url_host": env_host,
    }


def _kst_now() -> str:
    return datetime.now(timezone(timedelta(hours=9))).isoformat()


def _worker_loop():
    while True:
        cand = download_queue.get()
        try:
            base = _live_base_url()
            download_one(
                candidate=cand,
                state_path=STATE_PATH,
                downloads_dir=DOWNLOADS_DIR,
                feed_path=FEED_PATH,
                feed_meta=_live_feed_meta(base),
                base_url=base,
                deps=default_deps(),
            )
        finally:
            download_queue.task_done()


_worker_thread = threading.Thread(target=_worker_loop, daemon=True)
_worker_thread.start()


def _startup_regen_feed() -> None:
    """앱 부팅 시 feed.xml 을 현재 LAN IP 로 재생성. 네트워크 IP 가 바뀌어도
    기존 episodes 의 asset_url 이 자동 동기화된다."""
    try:
        base = _live_base_url()
        regenerate_feed(load_state(STATE_PATH), _live_feed_meta(base), base, FEED_PATH)
    except Exception:
        pass  # state 비어있거나 디스크 이슈여도 부팅 자체는 진행


_startup_regen_feed()


# ---------- routes ----------

def _group_candidates_by_channel(candidates):
    """후보를 채널 단위 dict로 묶는다. dict insertion 순서가 보존되므로
    글로벌 정렬 순서(upload_date desc, view_count desc)대로 채널이 등장한다."""
    grouped: dict[str, list] = {}
    for c in candidates:
        key = c.channel_alias or c.channel_name or "(unknown)"
        grouped.setdefault(key, []).append(c)
    return grouped


@app.route("/")
def index():
    state = load_state(STATE_PATH)
    return render_template(
        "candidates.html",
        state=state,
        grouped=_group_candidates_by_channel(state.candidates),
        base_url=_live_base_url(),
    )


def _run_curate_in_bg() -> None:
    global _curate_running
    try:
        run_curation(WATCHLIST_PATH, STATE_PATH)
    finally:
        _curate_running = False
        _curate_lock.release()


@app.route("/curate", methods=["POST"])
def curate():
    """큐레이션은 채널당 30~90초 걸리므로 background thread 로 던지고 즉시 redirect.
    이미 실행 중이면 두 번째 호출은 no-op (lock acquire 실패)."""
    global _curate_running
    if not _curate_lock.acquire(blocking=False):
        return redirect(url_for("index"))
    _curate_running = True
    threading.Thread(target=_run_curate_in_bg, daemon=True).start()
    return redirect(url_for("index"))


@app.route("/candidates/add", methods=["POST"])
def candidates_add():
    """수동으로 YouTube URL 을 후보 리스트에 추가. anti-bot 등으로 메타 fetch 가
    실패하면 flash 로 알리고 후보는 추가하지 않는다."""
    url = (request.form.get("url") or "").strip()
    alias = (request.form.get("alias") or "").strip() or None
    if not url:
        flash("URL을 입력해줘.", "error")
        return redirect(url_for("index"))
    vid = extract_video_id(url)
    if not vid:
        flash(f"YouTube URL이 아닌 것 같아: {url}", "error")
        return redirect(url_for("index"))

    state = load_state(STATE_PATH)
    if any(c.video_id == vid for c in state.candidates):
        flash(f"이미 후보에 있어: {vid}", "info")
        return redirect(url_for("index"))
    if any(e.video_id == vid for e in state.episodes):
        flash(f"이미 다운로드한 영상이야: {vid}", "info")
        return redirect(url_for("index"))

    try:
        cand = video_id_to_candidate(vid, alias=alias)
    except Exception as e:
        flash(f"메타 fetch 실패 ({vid}): {e}", "error")
        return redirect(url_for("index"))

    state.candidates.insert(0, cand)
    # 한 번이라도 추가하면 last_curated_at 도 갱신해서 페이지에 stale 표시 안 보이게.
    state.last_curated_at = _kst_now()
    save_state(STATE_PATH, state)
    flash(f"추가됨: {cand.title or vid}", "info")
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


@app.route("/download-batch", methods=["POST"])
def download_batch():
    video_ids = request.form.getlist("video_id")
    if not video_ids:
        return redirect(url_for("index"))
    state = load_state(STATE_PATH)
    cands_by_id = {c.video_id: c for c in state.candidates}
    queued: list = []
    for vid in video_ids:
        cand = cands_by_id.get(vid)
        if cand is None:
            continue
        if vid not in state.in_progress:
            state.in_progress.append(vid)
        queued.append(cand)
    save_state(STATE_PATH, state)
    for cand in queued:
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
        base_url=_live_base_url(),
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
        base = _live_base_url()
        regenerate_feed(state, _live_feed_meta(base), base, FEED_PATH)
    return redirect(url_for("episodes_page"))


def main() -> int:
    port = int(os.environ.get("POCKET_POD_APP_PORT", "8001"))
    app.run(host="0.0.0.0", port=port, debug=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
