"""A deterministic in-process HTTP server for crawler tests.

Serves configurable routes (HTML pages, redirects, images, raw files) on a
local port so tests never depend on the live internet.
"""

from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, HTTPServer


class RouteSpec:
    def __init__(self, body: bytes, content_type: str = "text/html; charset=utf-8"):
        self.body = body
        self.content_type = content_type


class SimpleRouter:
    """Maps path -> handler. Handlers can be bytes, callables, or status codes."""

    def __init__(self) -> None:
        self.routes: dict[str, object] = {}

    def add(self, path: str, body: bytes | str, content_type: str = "text/html; charset=utf-8") -> None:
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.routes[path] = RouteSpec(body, content_type)

    def add_status(self, path: str, status: int) -> None:
        self.routes[path] = status

    def add_redirect(self, path: str, location: str, status: int = 302) -> None:
        self.routes[path] = ("redirect", location, status)

    def route(self, path: str):
        """Return (status, headers, body)."""
        spec = self.routes.get(path)
        if spec is None:
            return 404, {}, b"Not Found"
        if isinstance(spec, int):
            return spec, {"Content-Type": "text/plain"}, b""
        if isinstance(spec, tuple) and spec and spec[0] == "redirect":
            return spec[2], {"Location": spec[1]}, b""
        return 200, {"Content-Type": spec.content_type}, spec.body


def make_server() -> tuple[HTTPServer, SimpleRouter, str]:
    router = SimpleRouter()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            status, headers, body = router.route(self.path)
            self.send_response(status)
            for k, v in headers.items():
                self.send_header(k, v)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if body:
                self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    base = f"http://127.0.0.1:{port}"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, router, base


class ServerScope:
    """Context manager combining a running server + router + base URL."""

    def __init__(self) -> None:
        self.server, self.router, self.base = make_server()

    def url(self, path: str) -> str:
        return self.base + path

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()

    def __enter__(self) -> "ServerScope":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()