from __future__ import annotations

import asyncio
from dataclasses import dataclass
from dataclasses import field
import sys
from typing import Callable

from ..channel_adapters import ChannelAdapter
from ..models import InboundMessage
from ..models import OutboundMessage
from ..runtime_client import BridgeClient
from ..session_store import InMemorySessionStore
from .bridge_runtime import BridgeTurnRunner
from .group_target import matches_target_group
from .group_target import session_key_for_message


@dataclass(slots=True)
class ConsoleGateway:
    adapter: ChannelAdapter
    allowed_group_subjects: set[str]
    allowed_group_chat_ids: set[str]
    bridge_client: BridgeClient | None = None
    session_store: InMemorySessionStore = field(default_factory=InMemorySessionStore)
    show_reasoning: bool = False
    show_actions: bool = False
    send_bridge_replies: bool = True
    output: Callable[[str], None] = print
    _active_chat_id: str | None = None
    _manual_message_counter: int = 0
    _bridge_lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    @property
    def bridge_turn_runner(self) -> BridgeTurnRunner | None:
        if self.bridge_client is None:
            return None
        return BridgeTurnRunner(
            bridge_client=self.bridge_client,
            session_store=self.session_store,
            show_commentary=True,
            show_actions=True,
            show_reasoning=self.show_reasoning,
        )

    def _write(self, line: str) -> None:
        self.output(line)

    def _matches_target_group(self, message: InboundMessage) -> bool:
        return matches_target_group(
            message,
            allowed_group_subjects=self.allowed_group_subjects,
            allowed_group_chat_ids=self.allowed_group_chat_ids,
        )

    def _remember_target_chat(self, message: InboundMessage) -> None:
        if self._matches_target_group(message):
            self._active_chat_id = message.chat_id

    def _resolve_target_chat_id(self) -> str | None:
        if len(self.allowed_group_chat_ids) == 1:
            return next(iter(self.allowed_group_chat_ids))
        return self._active_chat_id

    def _target_group_label(self) -> str:
        if len(self.allowed_group_subjects) == 1:
            return next(iter(self.allowed_group_subjects))
        if self._active_chat_id is not None:
            return self._active_chat_id
        if len(self.allowed_group_chat_ids) == 1:
            return next(iter(self.allowed_group_chat_ids))
        return "<target-group>"

    def _print_banner(self) -> None:
        self._write("Console commands:")
        self._write("  plain text  send to WhatsApp and, if bridge is configured, also ask Codex")
        self._write("  /wa <text>  send to WhatsApp only")
        self._write("  /codex <text>  ask Codex only")
        self._write("  /quit       exit")

    def _format_inbound(self, message: InboundMessage) -> str:
        subject = message.metadata.get("groupSubject") or message.chat_id
        sender = message.metadata.get("pushName") or message.sender_id
        text = message.text or "<sem texto>"
        return f"[whatsapp][in][{subject}][{sender}] {text}"

    def _format_outbound(self, source: str, text: str) -> str:
        return f"[whatsapp][out][{source}] {text}"

    def _format_codex(self, mode: str, text: str) -> str:
        return f"[codex][{mode}]\n{text}"

    def _should_forward_update_to_whatsapp(self, mode: str) -> bool:
        if mode == "final":
            return self.send_bridge_replies
        if mode == "reasoning":
            return self.send_bridge_replies and self.show_reasoning
        if mode == "action":
            return self.send_bridge_replies and self.show_actions
        return False

    async def _send_whatsapp_message(self, text: str, *, source: str) -> str:
        chat_id = self._resolve_target_chat_id()
        if chat_id is None:
            raise RuntimeError(
                "target WhatsApp group is not resolved yet; use --group-chat-id or wait for one inbound group message"
            )
        outbound = OutboundMessage(
            channel=self.adapter.channel_name,
            chat_id=chat_id,
            text=text,
            metadata={"mode": source},
        )
        await self.adapter.send_message(outbound)
        self._write(self._format_outbound(source, text))
        return chat_id

    def _synthetic_message(self, *, chat_id: str, text: str) -> InboundMessage:
        self._manual_message_counter += 1
        return InboundMessage(
            message_id=f"terminal-{self._manual_message_counter}",
            channel=self.adapter.channel_name,
            chat_id=chat_id,
            sender_id="terminal@local",
            text=text,
            is_group=True,
            metadata={
                "fromMe": True,
                "fromTerminal": True,
                "groupSubject": self._target_group_label(),
                "pushName": "Terminal",
            },
        )

    async def _stream_codex_for_message(self, message: InboundMessage) -> None:
        prompt = (message.text or "").strip()
        if not prompt or self.bridge_turn_runner is None:
            return
        if self._bridge_lock.locked():
            self._write("[codex][busy]\nAinda existe um turno em andamento; aguarde a resposta atual terminar.")
            return
        async with self._bridge_lock:
            self._write("[codex][status]\nProcessando...")
            async for update in self.bridge_turn_runner.stream_prompt(
                session_key=session_key_for_message(message),
                prompt=prompt,
            ):
                self._write(self._format_codex(update.mode, update.text))
                if self._should_forward_update_to_whatsapp(update.mode):
                    await self.adapter.send_message(
                        OutboundMessage.from_inbound(
                            message,
                            text=update.text,
                            metadata={"mode": f"bridge_{update.mode}"},
                        )
                    )

    async def handle_message(self, message: InboundMessage) -> None:
        if not self._matches_target_group(message):
            return
        self._remember_target_chat(message)
        self._write(self._format_inbound(message))
        await self._stream_codex_for_message(message)

    async def handle_console_line(self, line: str) -> bool:
        command = line.strip()
        if not command:
            return True
        if command in {"/quit", "/exit"}:
            return False
        if command == "/help":
            self._print_banner()
            return True
        if command.startswith("/wa "):
            await self._send_whatsapp_message(command[4:].strip(), source="terminal")
            return True
        if command.startswith("/codex "):
            if self.bridge_turn_runner is None:
                self._write("[codex][error] bridge não configurado para este console")
                return True
            chat_id = self._resolve_target_chat_id()
            if chat_id is None:
                raise RuntimeError(
                    "target WhatsApp group is not resolved yet; use --group-chat-id or wait for one inbound group message"
                )
            await self._stream_codex_for_message(
                self._synthetic_message(chat_id=chat_id, text=command[7:].strip())
            )
            return True

        chat_id = await self._send_whatsapp_message(command, source="terminal")
        if self.bridge_turn_runner is not None:
            await self._stream_codex_for_message(self._synthetic_message(chat_id=chat_id, text=command))
        return True

    async def _stdin_loop(self) -> None:
        while True:
            line = await asyncio.to_thread(sys.stdin.readline)
            if not line:
                return
            keep_going = await self.handle_console_line(line)
            if not keep_going:
                return

    async def run(self) -> None:
        await self.adapter.start(self.handle_message)
        self._print_banner()
        adapter_task = asyncio.create_task(self.adapter.wait())
        stdin_task = asyncio.create_task(self._stdin_loop())
        try:
            done, pending = await asyncio.wait(
                {adapter_task, stdin_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()
            for task in done:
                if task.cancelled():
                    continue
                exception = task.exception()
                if exception is not None:
                    raise exception
        finally:
            await self.adapter.close()
