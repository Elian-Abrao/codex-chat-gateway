from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

from .base import ChannelAdapter
from .base import MessageHandler
from ..models import InboundMessage
from ..models import OutboundMessage

logger = logging.getLogger(__name__)


class JsonlSubprocessChannelAdapter(ChannelAdapter):
    def __init__(
        self,
        *,
        channel_name: str,
        command: list[str],
        cwd: str | Path | None = None,
        env: dict[str, str] | None = None,
    ) -> None:
        self._channel_name = channel_name
        self._command = command
        self._cwd = str(cwd) if cwd is not None else None
        self._env = env
        self._process: asyncio.subprocess.Process | None = None
        self._handler: MessageHandler | None = None
        self._stdout_task: asyncio.Task[None] | None = None
        self._stderr_task: asyncio.Task[None] | None = None
        self._ready = asyncio.Event()

    @property
    def channel_name(self) -> str:
        return self._channel_name

    @property
    def ready(self) -> bool:
        return self._ready.is_set()

    async def start(self, handler: MessageHandler) -> None:
        if self._process is not None:
            raise RuntimeError(f"{self.channel_name} adapter already started")

        self._handler = handler
        self._process = await asyncio.create_subprocess_exec(
            *self._command,
            cwd=self._cwd,
            env=self._env,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        self._stdout_task = asyncio.create_task(self._read_stdout())
        self._stderr_task = asyncio.create_task(self._read_stderr())
        await self._wait_until_ready()

    async def _wait_until_ready(self) -> None:
        assert self._process is not None
        wait_task = asyncio.create_task(self._process.wait())
        ready_task = asyncio.create_task(self._ready.wait())
        done, pending = await asyncio.wait(
            {wait_task, ready_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
        if ready_task in done:
            return
        raise RuntimeError(f"{self.channel_name} worker exited before signalling readiness")

    async def _read_stdout(self) -> None:
        assert self._process is not None
        assert self._process.stdout is not None
        while True:
            raw_line = await self._process.stdout.readline()
            if not raw_line:
                return
            line = raw_line.decode("utf-8").strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                logger.warning("%s worker emitted invalid JSON: %s", self.channel_name, line)
                continue
            await self._handle_event(payload)

    async def _read_stderr(self) -> None:
        assert self._process is not None
        assert self._process.stderr is not None
        while True:
            raw_line = await self._process.stderr.readline()
            if not raw_line:
                return
            line = raw_line.decode("utf-8").rstrip()
            if line:
                logger.info("%s worker: %s", self.channel_name, line)

    async def _handle_event(self, payload: dict[str, Any]) -> None:
        event_type = payload.get("type")
        if event_type == "ready":
            self._ready.set()
            logger.info("%s worker ready", self.channel_name)
            return
        if event_type == "log":
            level = payload.get("level", "info")
            message = payload.get("message", "")
            log_method = getattr(logger, level, logger.info)
            log_method("%s worker: %s", self.channel_name, message)
            return
        if event_type == "message":
            if self._handler is None:
                raise RuntimeError(f"{self.channel_name} adapter has no handler registered")
            message = InboundMessage.from_dict(payload["message"])
            logger.info(
                "%s inbound message chat=%s sender=%s text=%r attachments=%d",
                self.channel_name,
                message.chat_id,
                message.sender_id,
                message.text,
                len(message.attachments),
            )
            await self._handler(message)
            return
        if event_type == "error":
            logger.error("%s worker error: %s", self.channel_name, payload.get("message"))
            return
        logger.warning("%s worker emitted unknown event: %s", self.channel_name, payload)

    async def wait(self) -> None:
        if self._process is None:
            raise RuntimeError(f"{self.channel_name} adapter not started")
        await self._process.wait()
        if self._stdout_task is not None:
            await self._stdout_task
        if self._stderr_task is not None:
            await self._stderr_task

    async def send_message(self, message: OutboundMessage) -> None:
        if self._process is None or self._process.stdin is None:
            raise RuntimeError(f"{self.channel_name} adapter not started")
        logger.info(
            "%s outbound message chat=%s text=%r attachments=%d",
            self.channel_name,
            message.chat_id,
            message.text,
            len(message.attachments),
        )
        self._process.stdin.write(
            json.dumps(
                {
                    "type": "send_message",
                    "message": message.to_dict(),
                },
                ensure_ascii=False,
            ).encode("utf-8")
            + b"\n"
        )
        await self._process.stdin.drain()

    async def close(self) -> None:
        if self._process is None:
            return
        if self._process.stdin is not None and not self._process.stdin.is_closing():
            self._process.stdin.close()
        if self._process.returncode is None:
            self._process.terminate()
            try:
                await asyncio.wait_for(self._process.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                self._process.kill()
                await self._process.wait()
        if self._stdout_task is not None:
            self._stdout_task.cancel()
        if self._stderr_task is not None:
            self._stderr_task.cancel()
        self._process = None
