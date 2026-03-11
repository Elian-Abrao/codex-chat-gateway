from __future__ import annotations

import asyncio
from dataclasses import dataclass
from dataclasses import field
import sys
from contextlib import suppress
from typing import Callable

from ..channel_adapters import ChannelAdapter
from ..models import InboundMessage
from ..models import OutboundMessage
from ..runtime_client import BridgeClient
from ..session_store import InMemorySessionStore
from .pending_requests import build_input_answers
from .pending_requests import build_pending_approval_result
from .bridge_runtime import BridgeTurnRunner
from .group_target import matches_target_group
from .group_target import session_key_for_message
from .pending_requests import format_busy_message
from .pending_requests import format_pending_request_message
from .pending_requests import format_pending_resolution_message
from .pending_requests import pending_accepts_approval_commands
from .pending_requests import parse_pending_command


@dataclass(slots=True)
class ConsoleGateway:
    adapter: ChannelAdapter
    allowed_group_subjects: set[str]
    allowed_group_chat_ids: set[str]
    bridge_client: BridgeClient | None = None
    session_store: InMemorySessionStore = field(default_factory=InMemorySessionStore)
    show_commentary: bool = False
    show_reasoning: bool = False
    show_actions: bool = False
    send_bridge_replies: bool = True
    output: Callable[[str], None] = print
    _active_chat_id: str | None = None
    _manual_message_counter: int = 0
    _turn_tasks: set[asyncio.Task[None]] = field(default_factory=set)

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
        self._write("  /pending    show the current pending bridge request")
        self._write("  /approve    approve the current pending request")
        self._write("  /reject     reject the current pending request")
        self._write("  /answer ... answer the current pending input request")
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

    def _should_forward_update_to_whatsapp(self, mode: str, *, force: bool = False) -> bool:
        if force:
            return self.send_bridge_replies
        if mode == "final":
            return self.send_bridge_replies
        if mode == "commentary":
            return self.send_bridge_replies and self.show_commentary
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

    def _track_task(self, task: asyncio.Task[None]) -> None:
        self._turn_tasks.add(task)

        def _done(done_task: asyncio.Task[None]) -> None:
            self._turn_tasks.discard(done_task)
            with suppress(asyncio.CancelledError):
                exception = done_task.exception()
                if exception is not None:
                    self._write(f"[codex][error]\n{exception}")

        task.add_done_callback(_done)

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

    async def _send_action_update(
        self,
        message: InboundMessage,
        text: str,
        *,
        forward_to_whatsapp: bool,
    ) -> None:
        formatted = f"[Codex • ações]\n> {text.replace(chr(10), chr(10) + '> ')}"
        self._write(self._format_codex("action", formatted))
        if forward_to_whatsapp:
            await self.adapter.send_message(
                OutboundMessage.from_inbound(
                    message,
                    text=formatted,
                    metadata={"mode": "bridge_action"},
                )
            )

    async def _respond_pending_request(
        self,
        message: InboundMessage,
        *,
        session_key: str,
        action: str,
        argument: str | None = None,
        forward_to_whatsapp: bool,
    ) -> bool:
        pending_request = self.session_store.get_or_create(session_key).pending_request
        if pending_request is None:
            await self._send_action_update(message, "nenhuma solicitação pendente", forward_to_whatsapp=forward_to_whatsapp)
            return True
        if action == "pending":
            await self._send_action_update(
                message,
                format_pending_request_message(pending_request),
                forward_to_whatsapp=forward_to_whatsapp,
            )
            return True
        if action in {"approve", "reject"}:
            if not pending_accepts_approval_commands(pending_request):
                await self._send_action_update(
                    message,
                    "a solicitação pendente não aceita /approve ou /reject",
                    forward_to_whatsapp=forward_to_whatsapp,
                )
                return True
            try:
                await self.bridge_client.respond_server_request(  # type: ignore[union-attr]
                    pending_request.request_id,
                    result=build_pending_approval_result(pending_request, action),
                )
            except Exception as exc:
                await self._send_action_update(
                    message,
                    f"falha ao responder ao bridge: {exc}",
                    forward_to_whatsapp=forward_to_whatsapp,
                )
                return True
            self.session_store.clear_pending_request(session_key)
            await self._send_action_update(
                message,
                format_pending_resolution_message(action),
                forward_to_whatsapp=forward_to_whatsapp,
            )
            return True
        if action == "answer":
            if pending_request.kind != "input_request":
                await self._send_action_update(
                    message,
                    "a solicitação pendente não aceita /answer",
                    forward_to_whatsapp=forward_to_whatsapp,
                )
                return True
            try:
                answers = build_input_answers(pending_request, argument or "")
            except ValueError as exc:
                await self._send_action_update(message, str(exc), forward_to_whatsapp=forward_to_whatsapp)
                return True
            try:
                await self.bridge_client.respond_server_request(  # type: ignore[union-attr]
                    pending_request.request_id,
                    result={"answers": answers},
                )
            except Exception as exc:
                await self._send_action_update(
                    message,
                    f"falha ao responder ao bridge: {exc}",
                    forward_to_whatsapp=forward_to_whatsapp,
                )
                return True
            self.session_store.clear_pending_request(session_key)
            await self._send_action_update(
                message,
                format_pending_resolution_message(action),
                forward_to_whatsapp=forward_to_whatsapp,
            )
            return True
        return False

    async def _stream_codex_for_message(self, message: InboundMessage) -> None:
        prompt = (message.text or "").strip()
        if not prompt or self.bridge_turn_runner is None:
            return
        session_key = session_key_for_message(message)
        self.session_store.set_active_turn(session_key, True)
        try:
            self._write("[codex][status]\nProcessando...")
            async for update in self.bridge_turn_runner.stream_prompt(
                session_key=session_key,
                prompt=prompt,
            ):
                text = update.text
                force_forward = False
                if update.pending_request is not None:
                    self.session_store.set_pending_request(session_key, update.pending_request)
                    text = f"[Codex • ações]\n> {format_pending_request_message(update.pending_request).replace(chr(10), chr(10) + '> ')}"
                    force_forward = True
                if update.mode == "final":
                    self.session_store.clear_pending_request(session_key)
                if text:
                    self._write(self._format_codex(update.mode, text))
                    if self._should_forward_update_to_whatsapp(update.mode, force=force_forward):
                        await self.adapter.send_message(
                            OutboundMessage.from_inbound(
                                message,
                                text=text,
                                metadata={"mode": f"bridge_{update.mode}"},
                            )
                        )
        except Exception as exc:
            self.session_store.clear_pending_request(session_key)
            text = f"[Codex]\nErro do gateway: {exc}"
            self._write(self._format_codex("error", text))
            if self.send_bridge_replies:
                await self.adapter.send_message(
                    OutboundMessage.from_inbound(
                        message,
                        text=text,
                        metadata={"mode": "bridge_final"},
                    )
                )
        finally:
            self.session_store.set_active_turn(session_key, False)

    async def handle_message(self, message: InboundMessage) -> None:
        if not self._matches_target_group(message):
            return
        self._remember_target_chat(message)
        self._write(self._format_inbound(message))
        session_key = session_key_for_message(message)
        session = self.session_store.get_or_create(session_key)
        command = parse_pending_command((message.text or "").strip())
        if command is not None and self.bridge_client is not None:
            await self._respond_pending_request(
                message,
                session_key=session_key,
                action=command.action,
                argument=command.argument,
                forward_to_whatsapp=self.send_bridge_replies,
            )
            return
        if session.pending_request is not None:
            await self._send_action_update(
                message,
                format_pending_request_message(session.pending_request),
                forward_to_whatsapp=self.send_bridge_replies,
            )
            return
        if session.active_turn:
            await self._send_action_update(
                message,
                format_busy_message(has_pending_request=False),
                forward_to_whatsapp=self.send_bridge_replies,
            )
            return
        task = asyncio.create_task(self._stream_codex_for_message(message))
        self._track_task(task)

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
        pending_command = parse_pending_command(command)
        if pending_command is not None:
            if self.bridge_turn_runner is None:
                self._write("[codex][error] bridge não configurado para este console")
                return True
            chat_id = self._resolve_target_chat_id()
            if chat_id is None:
                raise RuntimeError(
                    "target WhatsApp group is not resolved yet; use --group-chat-id or wait for one inbound group message"
                )
            await self._respond_pending_request(
                self._synthetic_message(chat_id=chat_id, text=command),
                session_key=f"{self.adapter.channel_name}:{chat_id}",
                action=pending_command.action,
                argument=pending_command.argument,
                forward_to_whatsapp=self.send_bridge_replies,
            )
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
            session_key = f"{self.adapter.channel_name}:{chat_id}"
            session = self.session_store.get_or_create(session_key)
            if session.pending_request is not None:
                await self._send_action_update(
                    self._synthetic_message(chat_id=chat_id, text=command),
                    format_pending_request_message(session.pending_request),
                    forward_to_whatsapp=self.send_bridge_replies,
                )
                return True
            if session.active_turn:
                self._write("[codex][busy]\nAinda existe um turno em andamento; aguarde a resposta atual terminar.")
                return True
            task = asyncio.create_task(
                self._stream_codex_for_message(
                    self._synthetic_message(chat_id=chat_id, text=command[7:].strip())
                )
            )
            self._track_task(task)
            return True

        chat_id = await self._send_whatsapp_message(command, source="terminal")
        if self.bridge_turn_runner is not None:
            session_key = f"{self.adapter.channel_name}:{chat_id}"
            session = self.session_store.get_or_create(session_key)
            if session.pending_request is not None:
                await self._send_action_update(
                    self._synthetic_message(chat_id=chat_id, text=command),
                    format_pending_request_message(session.pending_request),
                    forward_to_whatsapp=self.send_bridge_replies,
                )
                return True
            if session.active_turn:
                self._write("[codex][busy]\nAinda existe um turno em andamento; aguarde a resposta atual terminar.")
                return True
            task = asyncio.create_task(self._stream_codex_for_message(self._synthetic_message(chat_id=chat_id, text=command)))
            self._track_task(task)
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
            for task in tuple(self._turn_tasks):
                task.cancel()
            for task in tuple(self._turn_tasks):
                with suppress(asyncio.CancelledError):
                    await task
            await self.adapter.close()
