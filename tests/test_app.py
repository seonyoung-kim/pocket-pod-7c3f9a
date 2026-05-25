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
    c, tmp_path, app_module = client
    cand = Candidate(
        video_id="a", channel_id="UC", channel_name="A", channel_alias="",
        title="t", duration_sec=1, view_count=10, upload_date="2026-05-20",
        days_old=1, url="https://yt/a", thumbnail_url="", score=10.0,
    )
    with patch("app.run_curation", return_value=1) as m:
        def fake(wl, st):
            from scripts.state import load_state, save_state
            s = load_state(st)
            s.candidates = [cand]
            save_state(st, s)
            return 1
        m.side_effect = fake
        rv = c.post("/curate", follow_redirects=False)
        assert rv.status_code in (302, 303)
        # background thread 완료까지 대기 (lock 잡으면 thread는 release됨)
        with app_module._curate_lock:
            pass
    rv2 = c.get("/")
    assert rv2.status_code == 200
    assert b"a" in rv2.data    # video_id rendered


def test_curate_route_blocks_duplicate_while_running(client):
    c, tmp_path, app_module = client
    # 다른 curation 이 이미 실행 중인 상황 시뮬레이션
    assert app_module._curate_lock.acquire(blocking=False)
    captured = []
    try:
        with patch("app.run_curation", side_effect=lambda *a, **kw: captured.append(1)):
            rv = c.post("/curate", follow_redirects=False)
            assert rv.status_code in (302, 303)
        assert captured == []   # 두 번째 호출은 no-op
    finally:
        app_module._curate_lock.release()


def test_curate_button_shows_running_state(client):
    c, _, app_module = client
    app_module._curate_running = True
    try:
        rv = c.get("/")
        assert b"Refreshing" in rv.data
        assert b"disabled" in rv.data
    finally:
        app_module._curate_running = False


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
    # 영상 썸네일 URL이 YouTube 표준 패턴으로 자동 생성됨
    assert b"i.ytimg.com/vi/ep/hqdefault.jpg" in rv.data
    # podcast cover 헤더가 상단에 표시 (context_processor가 feed_image_url 주입)
    assert b"podcast-header" in rv.data
    assert b"cover.png" in rv.data


def test_download_batch_enqueues_multiple(client):
    c, tmp_path, app_module = client
    from scripts.state import load_state, save_state
    s = load_state(tmp_path / "state.json")
    s.candidates = [
        Candidate(video_id="v1", channel_id="UC", channel_name="A",
                  channel_alias="", title="t1", duration_sec=1, view_count=10,
                  upload_date="2026-05-20", days_old=1, url="https://yt/v1",
                  thumbnail_url="", score=10.0),
        Candidate(video_id="v2", channel_id="UC", channel_name="A",
                  channel_alias="", title="t2", duration_sec=1, view_count=20,
                  upload_date="2026-05-20", days_old=1, url="https://yt/v2",
                  thumbnail_url="", score=20.0),
        Candidate(video_id="v3", channel_id="UC", channel_name="A",
                  channel_alias="", title="t3", duration_sec=1, view_count=30,
                  upload_date="2026-05-20", days_old=1, url="https://yt/v3",
                  thumbnail_url="", score=30.0),
    ]
    save_state(tmp_path / "state.json", s)

    captured = []
    def probe(candidate, **kw):
        captured.append(candidate.video_id)
        return True

    with patch.object(app_module, "download_one", side_effect=probe):
        rv = c.post("/download-batch",
                    data={"video_id": ["v1", "v3"]},
                    follow_redirects=False)
        assert rv.status_code in (302, 303)
        app_module.download_queue.join()

    assert captured == ["v1", "v3"]
    s2 = load_state(tmp_path / "state.json")
    # in_progress is cleared by the worker probe? No — probe doesn't manage state.
    # The route adds both to in_progress before queueing.
    assert set(s2.in_progress) == {"v1", "v3"}


def test_download_batch_empty_form_redirects(client):
    """video_id 없이 POST해도 안전하게 redirect (no-op)."""
    c, tmp_path, app_module = client
    captured = []
    with patch.object(app_module, "download_one",
                       side_effect=lambda candidate, **kw: captured.append(candidate.video_id)):
        rv = c.post("/download-batch", data={})
        assert rv.status_code in (302, 303)
        app_module.download_queue.join()
    assert captured == []


def test_download_batch_ignores_unknown_video_ids(client):
    c, tmp_path, app_module = client
    from scripts.state import load_state, save_state
    s = load_state(tmp_path / "state.json")
    s.candidates = [
        Candidate(video_id="known", channel_id="UC", channel_name="A",
                  channel_alias="", title="t", duration_sec=1, view_count=10,
                  upload_date="2026-05-20", days_old=1, url="https://yt/k",
                  thumbnail_url="", score=10.0),
    ]
    save_state(tmp_path / "state.json", s)

    captured = []
    def probe(candidate, **kw):
        captured.append(candidate.video_id)
        return True

    with patch.object(app_module, "download_one", side_effect=probe):
        rv = c.post("/download-batch",
                    data={"video_id": ["known", "ghost"]},
                    follow_redirects=False)
        assert rv.status_code in (302, 303)
        app_module.download_queue.join()

    assert captured == ["known"]


def test_index_groups_candidates_by_channel(client):
    c, tmp_path, _ = client
    from scripts.state import load_state, save_state
    s = load_state(tmp_path / "state.json")
    s.candidates = [
        Candidate(video_id="a1", channel_id="UC1", channel_name="ChA",
                  channel_alias="에이", title="ta1", duration_sec=60,
                  view_count=100, upload_date="2026-05-24", days_old=1,
                  url="https://yt/a1", thumbnail_url="", score=100.0),
        Candidate(video_id="b1", channel_id="UC2", channel_name="ChB",
                  channel_alias="비", title="tb1", duration_sec=60,
                  view_count=99, upload_date="2026-05-23", days_old=2,
                  url="https://yt/b1", thumbnail_url="", score=99.0),
        Candidate(video_id="a2", channel_id="UC1", channel_name="ChA",
                  channel_alias="에이", title="ta2", duration_sec=60,
                  view_count=50, upload_date="2026-05-20", days_old=5,
                  url="https://yt/a2", thumbnail_url="", score=50.0),
    ]
    save_state(tmp_path / "state.json", s)
    rv = c.get("/")
    assert rv.status_code == 200
    body = rv.data.decode()
    # 두 채널 헤더가 다 나오고, 채널마다 카드 수가 정확히 표시
    assert "에이" in body
    assert "비" in body
    assert "(2)" in body and "(1)" in body
    # "에이" 섹션이 "비" 섹션보다 먼저 나옴 (글로벌 정렬상 a1이 더 최근)
    assert body.index("에이") < body.index("비")
