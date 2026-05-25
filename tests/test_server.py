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
