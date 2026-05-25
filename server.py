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
