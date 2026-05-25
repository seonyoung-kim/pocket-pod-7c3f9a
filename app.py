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
