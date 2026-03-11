from __future__ import annotations

import unittest
from unittest.mock import patch

from codex_chat_gateway.runtime_client.bridge import BridgeClient


class _FakeStreamingResponse:
    def __init__(self, lines: list[bytes]) -> None:
        self._lines = lines
        self._index = 0

    def __enter__(self) -> _FakeStreamingResponse:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def readline(self) -> bytes:
        if self._index >= len(self._lines):
            return b""
        line = self._lines[self._index]
        self._index += 1
        return line


class BridgeClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_stream_consumer_chat_reads_sse_incrementally(self) -> None:
        client = BridgeClient("http://127.0.0.1:8787", timeout=5.0)
        response = _FakeStreamingResponse(
            [
                b"event: status\n",
                b'data: {"threadId":"thr_1","message":"Thread started."}\n',
                b"\n",
                b"event: final\n",
                b'data: {"threadId":"thr_1","turnId":"turn_1","text":"ok"}\n',
                b"\n",
            ]
        )

        with patch("codex_chat_gateway.runtime_client.bridge.request.urlopen", return_value=response):
            events = [event async for event in client.stream_consumer_chat("Reply with OK only.")]

        self.assertEqual(
            events,
            [
                {
                    "threadId": "thr_1",
                    "message": "Thread started.",
                    "event": "status",
                },
                {
                    "threadId": "thr_1",
                    "turnId": "turn_1",
                    "text": "ok",
                    "event": "final",
                },
            ],
        )

    async def test_read_thread_and_resume_thread_use_expected_endpoints(self) -> None:
        client = BridgeClient("http://127.0.0.1:8787", timeout=5.0)
        responses = [
            b'{"thread":{"id":"thr_1","status":{"type":"notLoaded"}}}',
            b'{"thread":{"id":"thr_1","status":{"type":"idle"}}}',
        ]
        calls: list[str] = []

        class _FakeJsonResponse:
            def __init__(self, body: bytes) -> None:
                self._body = body

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb) -> None:
                return None

            def read(self) -> bytes:
                return self._body

        def fake_urlopen(request_obj, timeout=0):
            calls.append(f"{request_obj.method} {request_obj.full_url}")
            return _FakeJsonResponse(responses.pop(0))

        with patch("codex_chat_gateway.runtime_client.bridge.request.urlopen", side_effect=fake_urlopen):
            read_result = await client.read_thread("thr_1")
            resume_result = await client.resume_thread("thr_1")

        self.assertEqual(read_result["thread"]["status"]["type"], "notLoaded")
        self.assertEqual(resume_result["thread"]["status"]["type"], "idle")
        self.assertEqual(
            calls,
            [
                "GET http://127.0.0.1:8787/v1/threads/thr_1",
                "POST http://127.0.0.1:8787/v1/threads/thr_1/resume",
            ],
        )
