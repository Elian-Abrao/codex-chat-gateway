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
