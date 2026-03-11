from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
import logging
import asyncio
from contextlib import suppress

from ..channel_adapters import ChannelAdapter
from ..models import InboundMessage
from ..models import OutboundMessage
from ..runtime_client import BridgeClient
from ..session_store import InMemorySessionStore
from ..session_store import PendingBridgeRequest
from .bridge_runtime import BridgeTurnRunner
from .pending_requests import build_pending_approval_result
from .group_target import matches_target_group
from .group_target import session_key_for_message
from .pending_requests import build_input_answers
from .pending_requests import format_busy_message
from .pending_requests import format_pending_request_message
from .pending_requests import format_pending_resolution_message
from .pending_requests import pending_accepts_approval_commands
from .pending_requests import parse_pending_command

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class BridgeChatGateway:
    adapter: ChannelAdapter
    bridge_client: BridgeClient
    session_store: InMemorySessionStore
    allowed_group_subjects: set[str]
    allowed_group_chat_ids: set[str]
    send_replies: bool = True
    show_commentary: bool = False
    show_reasoning: bool = False
    show_actions: bool = False
    approval_policy: str | None = None
    sandbox: str | None = None
    _turn_tasks: set[asyncio.Task[None]] = field(default_factory=set)

    @property
    def bridge_turn_runner(self) -> BridgeTurnRunner:
        return BridgeTurnRunner(
            bridge_client=self.bridge_client,
            session_store=self.session_store,
            show_commentary=self.show_commentary,
            show_reasoning=self.show_reasoning,
            show_actions=self.show_actions,
            approval_policy=self.approval_policy,
            sandbox=self.sandbox,
        )

    async def _send_reply(
        self,
        message: InboundMessage,
        *,
        text: str,
        mode: str,
    ) -> None:
        normalized = text.strip()
        if not self.send_replies or not normalized:
            return
        await self.adapter.send_message(
            OutboundMessage.from_inbound(
                message,
                text=normalized,
                metadata={"mode": mode},
            )
        )

    def _track_task(self, task: asyncio.Task[None]) -> None:
        self._turn_tasks.add(task)

        def _done(done_task: asyncio.Task[None]) -> None:
            self._turn_tasks.discard(done_task)
            with suppress(asyncio.CancelledError):
                exception = done_task.exception()
                if exception is not None:
                    logger.exception("Bridge turn task failed", exc_info=exception)

        task.add_done_callback(_done)

    def _matches_target_group(self, message: InboundMessage) -> bool:
        return matches_target_group(
            message,
            allowed_group_subjects=self.allowed_group_subjects,
            allowed_group_chat_ids=self.allowed_group_chat_ids,
        )

    async def _send_action_reply(self, message: InboundMessage, text: str) -> None:
        await self._send_reply(message, text=f"[Codex • ações]\n> {text.replace(chr(10), chr(10) + '> ')}", mode="bridge_action")

    async def _run_bridge_turn(self, message: InboundMessage, *, session_key: str, prompt: str) -> None:
        session = self.session_store.get_or_create(session_key)
        self.session_store.set_active_turn(session_key, True)
        try:
            async for update in self.bridge_turn_runner.stream_prompt(
                session_key=session_key,
                prompt=prompt,
            ):
                text = update.text
                if update.pending_request is not None:
                    self.session_store.set_pending_request(session_key, update.pending_request)
                    text = f"[Codex • ações]\n> {format_pending_request_message(update.pending_request).replace(chr(10), chr(10) + '> ')}"
                if update.mode == "final":
                    logger.info("Bridge response received assistant=%r", update.text)
                    self.session_store.clear_pending_request(session_key)
                if text:
                    await self._send_reply(message, text=text, mode=f"bridge_{update.mode}")
        except Exception as exc:
            logger.exception("Bridge turn failed for chat=%s", message.chat_id, exc_info=exc)
            self.session_store.clear_pending_request(session_key)
            await self._send_reply(message, text=f"[Codex]\nErro do gateway: {exc}", mode="bridge_final")
        finally:
            self.session_store.set_active_turn(session_key, False)

    async def _respond_pending_request(
        self,
        message: InboundMessage,
        *,
        session_key: str,
        pending_request: PendingBridgeRequest,
        action: str,
        argument: str | None = None,
    ) -> bool:
        if action == "pending":
            await self._send_action_reply(message, format_pending_request_message(pending_request))
            return True

        if action in {"approve", "reject"}:
            if not pending_accepts_approval_commands(pending_request):
                await self._send_action_reply(message, "a solicitação pendente não aceita /approve ou /reject")
                return True
            try:
                await self.bridge_client.respond_server_request(
                    pending_request.request_id,
                    result=build_pending_approval_result(pending_request, action),
                )
            except Exception as exc:
                await self._send_action_reply(message, f"falha ao responder ao bridge: {exc}")
                return True
            self.session_store.clear_pending_request(session_key)
            await self._send_action_reply(message, format_pending_resolution_message(action))
            return True

        if action == "answer":
            if pending_request.kind != "input_request":
                await self._send_action_reply(message, "a solicitação pendente não aceita /answer")
                return True
            try:
                answers = build_input_answers(pending_request, argument or "")
            except ValueError as exc:
                await self._send_action_reply(message, str(exc))
                return True
            try:
                await self.bridge_client.respond_server_request(
                    pending_request.request_id,
                    result={"answers": answers},
                )
            except Exception as exc:
                await self._send_action_reply(message, f"falha ao responder ao bridge: {exc}")
                return True
            self.session_store.clear_pending_request(session_key)
            await self._send_action_reply(message, format_pending_resolution_message(action))
            return True

        return False

    async def handle_message(self, message: InboundMessage) -> None:
        if not self._matches_target_group(message):
            logger.info(
                "Ignoring group message outside configured target groups chat=%s subject=%r",
                message.chat_id,
                message.metadata.get("groupSubject"),
            )
            return
        prompt = (message.text or "").strip()
        if not prompt:
            logger.info("Ignoring group message without text.")
            return

        key = session_key_for_message(message)
        session = self.session_store.get_or_create(key)
        pending_command = parse_pending_command(prompt)
        if pending_command is not None:
            if session.pending_request is None:
                await self._send_action_reply(message, "nenhuma solicitação pendente")
                return
            await self._respond_pending_request(
                message,
                session_key=key,
                pending_request=session.pending_request,
                action=pending_command.action,
                argument=pending_command.argument,
            )
            return

        if session.pending_request is not None:
            await self._send_action_reply(message, format_pending_request_message(session.pending_request))
            return
        if session.active_turn:
            await self._send_action_reply(message, format_busy_message(has_pending_request=False))
            return
        logger.info(
            "Forwarding WhatsApp group message to bridge chat=%s sender=%s subject=%r thread=%r",
            message.chat_id,
            message.sender_id,
            message.metadata.get("groupSubject"),
            session.thread_id,
        )
        task = asyncio.create_task(self._run_bridge_turn(message, session_key=key, prompt=prompt))
        self._track_task(task)

    async def run(self) -> None:
        await self.adapter.start(self.handle_message)
        try:
            await self.adapter.wait()
        finally:
            for task in tuple(self._turn_tasks):
                task.cancel()
            for task in tuple(self._turn_tasks):
                with suppress(asyncio.CancelledError):
                    await task
            await self.adapter.close()
