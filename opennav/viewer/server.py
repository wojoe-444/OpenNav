"""`opennav serve`: a local web app for visual review of official vs modeled routes.

The UI is the React app in web/ (built into opennav/viewer/static/). This module
serves that bundle plus a small JSON API on 127.0.0.1 only:

  GET  /api/health                       {"ok": true, "data_dir": ...}
  GET  /api/cases                        every case, whether it has ground truth, cached scores
  GET  /api/cases/<id>?model=opennav     official + modeled + score + divergence for one case
  POST /api/cases/<id>/rerun?model=...   recompute the modeled side (after changing the engine)

Add an endpoint by adding a method to `Api` and a line in `ROUTES`; the web app
calls it through `web/src/lib/api.ts`.
"""
from __future__ import annotations

import json
import mimetypes
import re
import sys
import threading
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse

from ..cases import data_dir
from .compare import MODELS, Comparer

STATIC = Path(__file__).resolve().parent / "static"

# Explicit types for the bundle: on Windows, mimetypes reads the registry, which
# can map .js to text/plain, and browsers refuse to run module scripts served so.
CONTENT_TYPES = {
    ".html": "text/html", ".js": "text/javascript", ".mjs": "text/javascript", ".css": "text/css",
    ".svg": "image/svg+xml", ".json": "application/json", ".png": "image/png",
    ".woff2": "font/woff2", ".woff": "font/woff",
}


class ApiError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


class Api:
    def __init__(self):
        self.comparer = Comparer()

    def health(self, q: dict[str, str]) -> Any:
        return {"ok": True, "data_dir": str(data_dir()), "models": list(MODELS)}

    def cases(self, q: dict[str, str]) -> Any:
        return self.comparer.cases()

    def case(self, q: dict[str, str], case_id: str) -> Any:
        return self._compare(case_id, q.get("model", "opennav"), rerun=False)

    def rerun(self, q: dict[str, str], case_id: str) -> Any:
        return self._compare(case_id, q.get("model", "opennav"), rerun=True)

    def _compare(self, case_id: str, model: str, rerun: bool) -> Any:
        try:
            return self.comparer.compare(case_id, model, rerun=rerun)
        except KeyError as e:
            raise ApiError(HTTPStatus.NOT_FOUND, f"unknown case or model: {e.args[0]}") from None


# (method, path regex, Api method name)
ROUTES: list[tuple[str, re.Pattern[str], str]] = [
    ("GET", re.compile(r"^/api/health$"), "health"),
    ("GET", re.compile(r"^/api/cases$"), "cases"),
    ("GET", re.compile(r"^/api/cases/([\w\-]+)$"), "case"),
    ("POST", re.compile(r"^/api/cases/([\w\-]+)/rerun$"), "rerun"),
]


def make_handler(api: Api, static_dir: Path = STATIC) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "opennav"

        def log_message(self, fmt: str, *args: Any) -> None:  # quieter than the default
            if not self.path.startswith("/assets/"):
                super().log_message(fmt, *args)

        def do_GET(self) -> None:
            self._dispatch("GET")

        def do_POST(self) -> None:
            self._dispatch("POST")

        def _dispatch(self, method: str) -> None:
            url = urlparse(self.path)
            if url.path.startswith("/api/"):
                return self._api(method, url.path, {k: v[-1] for k, v in parse_qs(url.query).items()})
            if method != "GET":
                return self._send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)
            self._static(url.path)

        def _api(self, method: str, path: str, q: dict[str, str]) -> None:
            for m, rx, name in ROUTES:
                hit = rx.match(path)
                if hit and m == method:
                    fn: Callable[..., Any] = getattr(api, name)
                    try:
                        return self._send_json(fn(q, *hit.groups()))
                    except ApiError as e:
                        return self._send_json({"error": str(e)}, e.status)
                    except Exception as e:  # keep the server up; show the error in the UI
                        return self._send_json({"error": f"{type(e).__name__}: {e}"}, HTTPStatus.INTERNAL_SERVER_ERROR)
            self._send_json({"error": f"no route for {method} {path}"}, HTTPStatus.NOT_FOUND)

        def _static(self, path: str) -> None:
            rel = path.lstrip("/") or "index.html"
            target = (static_dir / rel).resolve()
            if not target.is_relative_to(static_dir.resolve()) or not target.is_file():
                target = static_dir / "index.html"  # hash router: every page is index.html
            if not target.is_file():
                body = (b"The web app is not built. Run `npm install` and `npm run build` in web/, "
                        b"or `npm run dev` there for the dev server.")
                return self._send(body, "text/plain; charset=utf-8", HTTPStatus.NOT_FOUND)
            ctype = (CONTENT_TYPES.get(target.suffix.lower()) or mimetypes.guess_type(target.name)[0]
                     or "application/octet-stream")
            if ctype.startswith("text/") or ctype in ("application/json", "image/svg+xml"):
                ctype += "; charset=utf-8"
            cache = "public, max-age=31536000, immutable" if "/assets/" in path else "no-cache"
            self._send(target.read_bytes(), ctype, HTTPStatus.OK, cache)

        def _send_json(self, obj: Any, status: int = HTTPStatus.OK) -> None:
            self._send(json.dumps(obj).encode(), "application/json", status, "no-store")

        def _send(self, body: bytes, ctype: str, status: int, cache: str = "no-cache") -> None:
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", cache)
            self.end_headers()
            self.wfile.write(body)

    return Handler


class _Server(ThreadingHTTPServer):
    # On Windows SO_REUSEADDR lets a second server bind a port that is already in
    # use, so requests could go to the other app. Fail instead, and try the next port.
    allow_reuse_address = sys.platform != "win32"
    daemon_threads = True


def bind(host: str, port: int, handler, tries: int = 20) -> ThreadingHTTPServer:
    """Bind to `port`, or the next free port after it (another app may hold 8765)."""
    for p in range(port, port + tries):
        try:
            return _Server((host, p), handler)
        except OSError:
            if p == port:
                print(f"port {port} is in use, trying the next ones")
    raise OSError(f"no free port in {port}-{port + tries - 1}; pass --port")


def serve(host: str = "127.0.0.1", port: int = 8765, open_browser: bool = True, warm: str | None = None) -> None:
    api = Api()
    httpd = bind(host, port, make_handler(api))
    url = f"http://{'localhost' if host in ('127.0.0.1', '0.0.0.0') else host}:{httpd.server_address[1]}/"
    print(f"OpenNav viewer on {url}  (data: {data_dir()})  Ctrl+C to stop")
    if not (STATIC / "index.html").is_file():
        print("note: web app not built; run `npm install && npm run build` in web/")
    if warm:
        # Load the road graph and run the model in the background so the first page is fast.
        threading.Thread(target=lambda: _warm(api, warm), daemon=True).start()
    if open_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


def _warm(api: Api, case_id: str) -> None:
    try:
        api.comparer.compare(case_id)
        print(f"model ready for {case_id}")
    except Exception as e:
        print(f"warm-up of {case_id} failed: {e}")
