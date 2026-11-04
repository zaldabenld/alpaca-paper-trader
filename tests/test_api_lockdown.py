from __future__ import annotations

import asyncio
import json
import unittest
from typing import Any

from .helpers import configure_test_environment


configure_test_environment()

from alpaca_desktop import server


def call(method: str, path: str, host: str = "127.0.0.1:8765", headers: dict[str, str] | None = None,
         body: dict[str, Any] | None = None) -> tuple[int, dict[str, str], bytes]:
    """Drive the ASGI app directly (httpx/TestClient is not installed)."""
    raw_headers = [(b"host", host.encode())]
    payload = json.dumps(body).encode() if body is not None else b""
    if body is not None:
        raw_headers.append((b"content-type", b"application/json"))
    for name, value in (headers or {}).items():
        raw_headers.append((name.lower().encode(), value.encode()))
    scope = {
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": method,
        "scheme": "http", "path": path, "raw_path": path.encode(), "query_string": b"",
        "root_path": "", "headers": raw_headers, "client": ("127.0.0.1", 50000), "server": ("127.0.0.1", 8765),
    }
    messages = [{"type": "http.request", "body": payload, "more_body": False}]
    sent: list[dict[str, Any]] = []

    async def receive() -> dict[str, Any]:
        return messages.pop(0) if messages else {"type": "http.disconnect"}

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    asyncio.run(server.app(scope, receive, send))
    start = next(m for m in sent if m["type"] == "http.response.start")
    response_headers = {k.decode().lower(): v.decode() for k, v in start.get("headers", [])}
    content = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    return start["status"], response_headers, content


TOKEN = {"X-APT-Token": server.API_TOKEN}


class ApiLockdownTests(unittest.TestCase):
    def test_non_loopback_host_is_refused(self) -> None:
        status, _, _ = call("GET", "/api/health", host="attacker.example:8765")
        self.assertEqual(status, 400)

    def test_lookalike_and_missing_hosts_are_refused(self) -> None:
        for host in ("localhost.evil.example:8765", "127.0.0.1.nip.io:8765", "", "evil.example"):
            status, _, _ = call("GET", "/api/health", host=host)
            self.assertEqual(status, 400, host)

    def test_loopback_hosts_are_allowed(self) -> None:
        for host in ("127.0.0.1:8765", "localhost:8765", "[::1]:8765"):
            status, _, _ = call("GET", "/favicon.ico", host=host)
            self.assertEqual(status, 200, host)

    def test_state_changing_request_needs_the_token(self) -> None:
        status, _, content = call("POST", "/api/stop", body={"account_id": "missing"})
        self.assertEqual(status, 403)
        self.assertIn(b"invalid api token", content)
        status, _, _ = call("POST", "/api/stop", headers={"X-APT-Token": "wrong"}, body={"account_id": "missing"})
        self.assertEqual(status, 403)
        status, _, _ = call("DELETE", "/api/accounts/missing")
        self.assertEqual(status, 403)

    def test_valid_token_reaches_the_endpoint(self) -> None:
        status, _, content = call("POST", "/api/stop", headers=TOKEN, body={"account_id": "missing"})
        # The route itself answers (400 "Account was not found"), not the guard.
        self.assertNotEqual(status, 403, content)
        self.assertIn(b"Account was not found", content)

    def test_cross_origin_post_is_refused_even_with_token(self) -> None:
        headers = dict(TOKEN, Origin="http://localhost:3000")
        status, _, content = call("POST", "/api/stop", headers=headers, body={"account_id": "missing"})
        self.assertEqual(status, 403)
        self.assertIn(b"cross-origin", content)

    def test_index_page_carries_the_token(self) -> None:
        status, headers, content = call("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn(f'content="{server.API_TOKEN}"'.encode(), content)
        self.assertNotIn(b"__APT_API_TOKEN__", content)
        self.assertEqual(headers.get("cache-control"), "no-store")

    def test_health_allows_only_loopback_cross_port_reads(self) -> None:
        _, headers, _ = call("GET", "/api/health", headers={"Origin": "http://127.0.0.1:9999"})
        self.assertEqual(headers.get("access-control-allow-origin"), "http://127.0.0.1:9999")
        _, headers, _ = call("GET", "/api/health", headers={"Origin": "http://attacker.example"})
        self.assertNotIn("access-control-allow-origin", headers)
        _, headers, _ = call("GET", "/api/state", headers={"Origin": "http://127.0.0.1:9999"})
        self.assertNotIn("access-control-allow-origin", headers)


if __name__ == "__main__":
    unittest.main()
