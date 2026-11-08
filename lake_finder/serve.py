"""Local preview server for the results map, with no caching and live reload.

    python -m lake_finder.serve [--dir results] [--port 8765]
    pythonw -m lake_finder.serve      # Windows: same, without a console window

Serves the folder on http://localhost:<port>/ with no-cache headers, so a reload always shows the
latest file. HTML pages get a small script injected (the files on disk are not changed) that reloads
the tab whenever any file in the folder changes, e.g. after a pipeline run or an edit to map.html.
"""
from __future__ import annotations

import argparse
import functools
import os
import socket
import sys
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

RELOAD_PATH = "/__reload"
SNIPPET = (b"<script>(()=>{const es=new EventSource('" + RELOAD_PATH.encode() + b"');"
           b"es.onmessage=()=>location.reload();})();</script>")


def _stamp(root: Path) -> float:
    """Latest modification time of any file in the folder (top level is enough for results/)."""
    return max((e.stat().st_mtime for e in os.scandir(root) if e.is_file()), default=0.0)


class Handler(SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Cache-Control", "no-store, must-revalidate")
        super().end_headers()

    def do_GET(self):
        if self.path == RELOAD_PATH:
            return self._events()
        path = Path(self.translate_path(self.path))
        if path.is_dir():
            path = path / "index.html"
        if path.suffix.lower() in (".html", ".htm") and path.is_file():
            body = path.read_bytes()
            i = body.lower().rfind(b"</body>")
            body = body[:i] + SNIPPET + body[i:] if i >= 0 else body + SNIPPET
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        super().do_GET()

    def _events(self):
        """Server-sent events: one message when the folder changes; the page then reloads."""
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        root = Path(self.directory)
        last = _stamp(root)
        try:
            while True:
                time.sleep(0.5)
                now = _stamp(root)
                if now != last:
                    time.sleep(0.3)  # let the writer finish
                    self.wfile.write(b"data: reload\n\n")
                    self.wfile.flush()
                    return
                self.wfile.write(b": ping\n\n")  # detects closed tabs
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass

    def log_message(self, fmt, *args):
        # sys.stderr is None under pythonw.exe (windowless on Windows), so skip logging there.
        if sys.stderr is not None and RELOAD_PATH not in str(args[0] if args else ""):
            super().log_message(fmt, *args)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dir", default="results", help="folder to serve (default: results)")
    ap.add_argument("--port", type=int, default=8765)
    a = ap.parse_args(argv)
    root = Path(a.dir).resolve()
    handler = functools.partial(Handler, directory=str(root))
    # "localhost" may resolve to ::1 or 127.0.0.1 depending on the OS/browser, so listen on both
    # loopbacks (and nothing else, so the server isn't reachable from the network).
    servers = []
    for fam, addr in ((socket.AF_INET, "127.0.0.1"), (socket.AF_INET6, "::1")):
        cls = type("Srv", (ThreadingHTTPServer,), {"address_family": fam, "daemon_threads": True})
        try:
            servers.append(cls((addr, a.port), handler))
        except OSError as e:
            raise SystemExit(f"Port {a.port} on {addr} is busy ({e}). Try --port <other>.")
    for s in servers[1:]:
        threading.Thread(target=s.serve_forever, daemon=True).start()
    print(f"Serving {root} at http://localhost:{a.port}/map.html (live reload on, no cache). Ctrl+C to stop.")
    try:
        servers[0].serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
