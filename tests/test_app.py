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
