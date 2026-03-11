from __future__ import annotations

import asyncio
import json
from typing import Any
from typing import AsyncIterator
from urllib import request


class BridgeClient:
    def __init__(self, base_url: str, timeout: float = 120.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    async def chat(
        self,
        prompt: str,
        *,
        thread_id: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"prompt": prompt, **kwargs}
        if thread_id is not None:
            payload["threadId"] = thread_id
        return await asyncio.to_thread(self._post_json, "/v1/chat", payload)

    async def stream_chat(
        self,
        prompt: str,
        *,
        thread_id: str | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[dict[str, Any]]:
        async for event in self._stream_json_events(
            "/v1/chat/stream",
            prompt,
            thread_id=thread_id,
            inject_event_name=False,
            **kwargs,
        ):
            yield event

    async def stream_consumer_chat(
        self,
        prompt: str,
        *,
        thread_id: str | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[dict[str, Any]]:
        async for event in self._stream_json_events(
            "/v1/chat/consumer-stream",
            prompt,
            thread_id=thread_id,
            inject_event_name=True,
            **kwargs,
        ):
            yield event

    async def _stream_json_events(
        self,
        path: str,
        prompt: str,
        *,
        thread_id: str | None,
        inject_event_name: bool,
        **kwargs: Any,
    ) -> AsyncIterator[dict[str, Any]]:
        payload: dict[str, Any] = {"prompt": prompt, **kwargs}
        if thread_id is not None:
            payload["threadId"] = thread_id

        queue: asyncio.Queue[object] = asyncio.Queue()
        done = object()
        loop = asyncio.get_running_loop()

        def worker() -> None:
            body = json.dumps(payload).encode("utf-8")
            req = request.Request(
                f"{self._base_url}{path}",
                data=body,
                headers={
                    "Accept": "text/event-stream",
                    "Content-Type": "application/json",
                },
                method="POST",
            )
            try:
                with request.urlopen(req, timeout=self._timeout) as response:
                    current_event: str | None = None
                    data_lines: list[str] = []
                    for raw_line in response:
                        line = raw_line.decode("utf-8").rstrip("\r\n")
                        if line.startswith("event: "):
                            current_event = line[7:]
                            continue
                        if line.startswith("data: "):
                            data_lines.append(line[6:])
                            continue
                        if line:
                            continue
                        if not data_lines:
                            current_event = None
                            continue
                        payload = json.loads("\n".join(data_lines))
                        if inject_event_name and current_event and "event" not in payload:
                            payload["event"] = current_event
                        loop.call_soon_threadsafe(queue.put_nowait, payload)
                        current_event = None
                        data_lines = []
                    if data_lines:
                        payload = json.loads("\n".join(data_lines))
                        if inject_event_name and current_event and "event" not in payload:
                            payload["event"] = current_event
                        loop.call_soon_threadsafe(queue.put_nowait, payload)
            except Exception as exc:  # pragma: no cover - exercised through async surface
                loop.call_soon_threadsafe(queue.put_nowait, exc)
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, done)

        task = asyncio.create_task(asyncio.to_thread(worker))
        try:
            while True:
                item = await queue.get()
                if item is done:
                    break
                if isinstance(item, Exception):
                    raise item
                yield item
        finally:
            await task

    async def respond_server_request(
        self,
        request_id: str | int,
        *,
        result: Any = None,
        error: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload = {
            "requestId": request_id,
            "result": result,
            "error": error,
        }
        return await asyncio.to_thread(self._post_json, "/v1/server-requests/respond", payload)

    def _post_json(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(payload).encode("utf-8")
        req = request.Request(
            f"{self._base_url}{path}",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with request.urlopen(req, timeout=self._timeout) as response:
            return json.loads(response.read().decode("utf-8"))
