"""Minimal synchronous ASGI test client (httpx/TestClient are unavailable in this environment)."""
from __future__ import annotations

import asyncio
import json
from urllib.parse import urlsplit


class Response:
    def __init__(self, status: int, headers: dict, body: bytes):
        self.status_code, self.headers, self.content = status, headers, body

    @property
    def text(self) -> str:
        return self.content.decode("utf-8", "replace")

    def json(self):
        return json.loads(self.content or b"null")


class Client:
    def __init__(self, app):
        self.app = app

    def request(self, method: str, url: str, **kw) -> Response:
        return asyncio.run(self.arequest(method, url, **kw))

    async def arequest(self, method: str, url: str, *, json_body=None, data: bytes | None = None, headers: dict | None = None, token: str | None = None) -> Response:
        parts = urlsplit(url)
        h = {k.lower(): v for k, v in (headers or {}).items()}
        body = data or b""
        if json_body is not None:
            body = json.dumps(json_body).encode()
            h.setdefault("content-type", "application/json")
        if token:
            h["authorization"] = f"Bearer {token}"
        h.setdefault("content-length", str(len(body)))
        scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": method.upper(), "scheme": "http", "path": parts.path,
                 "raw_path": parts.path.encode(), "query_string": parts.query.encode(), "root_path": "",
                 "headers": [(k.encode(), v.encode()) for k, v in h.items()], "client": ("127.0.0.1", 1234), "server": ("test", 80)}

        async def run() -> Response:
            sent = {"done": False}
            out = {"status": 500, "headers": {}, "body": b""}

            async def receive():
                if not sent["done"]:
                    sent["done"] = True
                    return {"type": "http.request", "body": body, "more_body": False}
                await asyncio.sleep(3600)

            async def send(msg):
                if msg["type"] == "http.response.start":
                    out["status"] = msg["status"]
                    out["headers"] = {k.decode().lower(): v.decode() for k, v in msg["headers"]}
                elif msg["type"] == "http.response.body":
                    out["body"] += msg.get("body", b"")

            await self.app(scope, receive, send)
            return Response(out["status"], out["headers"], out["body"])

        return await run()

    def get(self, url, **kw):
        return self.request("GET", url, **kw)

    def post(self, url, **kw):
        return self.request("POST", url, **kw)
