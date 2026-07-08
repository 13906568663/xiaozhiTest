from __future__ import annotations

import json
from contextlib import AbstractContextManager
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from typing import Any, Callable
from urllib.parse import parse_qs, urlsplit


@dataclass
class MockHttpRequest:
    method: str
    path: str
    query: dict[str, list[str]]
    headers: dict[str, str]
    json_body: Any
    raw_body: str


RouteHandler = Callable[[MockHttpRequest], Any]


class MockHttpApiServer(AbstractContextManager["MockHttpApiServer"]):
    def __init__(self, routes: dict[str, RouteHandler]) -> None:
        self.routes = routes
        self.requests: list[MockHttpRequest] = []
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), self._build_handler())
        self._thread = Thread(target=self._server.serve_forever, daemon=True)

    @property
    def base_url(self) -> str:
        host, port = self._server.server_address
        return f"http://{host}:{port}"

    def __enter__(self) -> "MockHttpApiServer":
        self._thread.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=2)

    def _build_handler(self) -> type[BaseHTTPRequestHandler]:
        mock_server = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                self._handle()

            def do_POST(self) -> None:
                self._handle()

            def do_PUT(self) -> None:
                self._handle()

            def do_PATCH(self) -> None:
                self._handle()

            def do_DELETE(self) -> None:
                self._handle()

            def log_message(self, format: str, *args: Any) -> None:
                return

            def _handle(self) -> None:
                split_url = urlsplit(self.path)
                content_length = int(self.headers.get("Content-Length", "0") or "0")
                raw_body_bytes = self.rfile.read(content_length) if content_length > 0 else b""
                raw_body = raw_body_bytes.decode("utf-8") if raw_body_bytes else ""
                json_body: Any = None
                if raw_body:
                    try:
                        json_body = json.loads(raw_body)
                    except json.JSONDecodeError:
                        json_body = None

                request = MockHttpRequest(
                    method=self.command,
                    path=split_url.path,
                    query=parse_qs(split_url.query, keep_blank_values=True),
                    headers={key: value for key, value in self.headers.items()},
                    json_body=json_body,
                    raw_body=raw_body,
                )
                mock_server.requests.append(request)

                handler = mock_server.routes.get(split_url.path)
                if handler is None:
                    self.send_response(404)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(b'{"error":"not found"}')
                    return

                response = handler(request)
                status_code = 200
                response_headers: dict[str, str] = {"Content-Type": "application/json"}
                response_body: Any = response

                if isinstance(response, tuple):
                    if len(response) == 2:
                        status_code, response_body = response
                    elif len(response) == 3:
                        status_code, response_body, response_headers = response

                self.send_response(status_code)
                for key, value in response_headers.items():
                    self.send_header(key, value)
                self.end_headers()
                self.wfile.write(
                    json.dumps(response_body, ensure_ascii=False, default=str).encode("utf-8")
                )

        return Handler
