from __future__ import annotations

from dataclasses import dataclass
import logging

from ..channel_adapters import ChannelAdapter
from ..models import InboundMessage
from ..models import OutboundMessage
from ..runtime_client import BridgeClient
from ..session_store import InMemorySessionStore

logger = logging.getLogger(__name__)
FINAL_REPLY_HEADER = "[Codex]"
REASONING_REPLY_HEADER = "[Codex • raciocínio]"
ACTION_REPLY_HEADER = "[Codex • ações]"
REASONING_CHUNK_TARGET = 160


def session_key_for_message(message: InboundMessage) -> str:
    return f"{message.channel}:{message.chat_id}"


@dataclass(slots=True)
class BridgeChatGateway:
    adapter: ChannelAdapter
    bridge_client: BridgeClient
    session_store: InMemorySessionStore
    allowed_group_subjects: set[str]
    allowed_group_chat_ids: set[str]
    send_replies: bool = True
    show_reasoning: bool = False
    show_actions: bool = False

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

    def _format_final_reply(self, text: str) -> str:
        return f"{FINAL_REPLY_HEADER}\n{text.strip()}"

    def _format_reasoning_reply(self, text: str) -> str:
        return f"{REASONING_REPLY_HEADER}\n{text.strip()}"

    def _format_action_reply(self, text: str) -> str:
        quoted = "\n".join(f"> {line}" for line in text.strip().splitlines())
        return f"{ACTION_REPLY_HEADER}\n{quoted}"

    def _matches_target_group(self, message: InboundMessage) -> bool:
        if not message.is_group:
            return False
        if self.allowed_group_chat_ids and message.chat_id in self.allowed_group_chat_ids:
            return True
        group_subject = (message.metadata.get("groupSubject") or "").strip()
        if self.allowed_group_subjects and group_subject in self.allowed_group_subjects:
            return True
        return not self.allowed_group_chat_ids and not self.allowed_group_subjects

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
        logger.info(
            "Forwarding WhatsApp group message to bridge chat=%s sender=%s subject=%r thread=%r",
            message.chat_id,
            message.sender_id,
            message.metadata.get("groupSubject"),
            session.thread_id,
        )
        thread_id = session.thread_id
        assistant_fragments: list[str] = []
        reasoning_buffer = ""
        agent_message_phases: dict[str, str | None] = {}
        announced_events: set[str] = set()

        async def flush_reasoning() -> None:
            nonlocal reasoning_buffer
            if not self.show_reasoning:
                reasoning_buffer = ""
                return
            chunk = reasoning_buffer.strip()
            if not chunk:
                return
            await self._send_reply(
                message,
                text=self._format_reasoning_reply(chunk),
                mode="bridge_reasoning",
            )
            reasoning_buffer = ""

        async def announce_action(key: str, text: str) -> None:
            if not self.show_actions:
                return
            if key in announced_events:
                return
            announced_events.add(key)
            await flush_reasoning()
            await self._send_reply(
                message,
                text=self._format_action_reply(text),
                mode="bridge_action",
            )

        async for event in self.bridge_client.stream_chat(
            prompt,
            thread_id=thread_id,
            summary="detailed" if self.show_reasoning else "none",
        ):
            event_type = event.get("type")
            payload = event.get("payload", {})
            if not isinstance(payload, dict):
                payload = {}

            event_thread_id = event.get("threadId")
            if isinstance(event_thread_id, str) and event_thread_id:
                thread_id = event_thread_id
                self.session_store.set_thread_id(key, thread_id)

            if event_type == "item/started":
                item = payload.get("item", {})
                if not isinstance(item, dict):
                    continue
                item_type = item.get("type")
                item_id = item.get("id")
                if item_type == "agentMessage" and isinstance(item_id, str):
                    phase = item.get("phase")
                    agent_message_phases[item_id] = phase if isinstance(phase, str) else None
                    continue
                if item_type == "commandExecution" and isinstance(item_id, str):
                    command = item.get("command") or "<sem comando>"
                    await announce_action(
                        f"commandExecution:{item_id}",
                        f"executando comando: {command}",
                    )
                    continue
                if item_type == "mcpToolCall" and isinstance(item_id, str):
                    server = item.get("server") or "?"
                    tool = item.get("tool") or "?"
                    await announce_action(
                        f"mcpToolCall:{item_id}",
                        f"tool MCP: {server}/{tool}",
                    )
                    continue
                if item_type == "dynamicToolCall" and isinstance(item_id, str):
                    tool = item.get("tool") or "?"
                    await announce_action(
                        f"dynamicToolCall:{item_id}",
                        f"tool: {tool}",
                    )
                    continue
                continue

            if event_type == "item/reasoning/summaryTextDelta":
                delta = payload.get("delta", "")
                if isinstance(delta, str) and delta:
                    reasoning_buffer += delta
                    if self.show_reasoning and (
                        len(reasoning_buffer) >= REASONING_CHUNK_TARGET
                        or reasoning_buffer.endswith((".", "!", "?", "\n"))
                    ):
                        await flush_reasoning()
                continue

            if event_type == "item/tool/call":
                request_id = event.get("requestId")
                tool = payload.get("tool") or "<tool desconhecida>"
                await announce_action(
                    f"toolCall:{request_id or tool}",
                    f"tool solicitada: {tool}",
                )
                continue

            if event_type == "item/commandExecution/requestApproval":
                request_id = event.get("requestId")
                command = payload.get("command") or "<comando desconhecido>"
                await announce_action(
                    f"commandApproval:{request_id or command}",
                    f"aprovação necessária para comando: {command}",
                )
                continue

            if event_type == "item/fileChange/requestApproval":
                request_id = event.get("requestId")
                await announce_action(
                    f"fileApproval:{request_id or 'file-change'}",
                    "aprovação necessária para alterações de arquivos",
                )
                continue

            if event_type == "item/tool/requestUserInput":
                request_id = event.get("requestId")
                await announce_action(
                    f"userInput:{request_id or 'tool-input'}",
                    "aguardando entrada do usuário para continuar",
                )
                continue

            if event_type == "item/agentMessage/delta":
                item_id = payload.get("itemId")
                if not isinstance(item_id, str):
                    continue
                phase = agent_message_phases.get(item_id)
                delta = payload.get("delta", "")
                if isinstance(delta, str) and phase in (None, "final_answer"):
                    assistant_fragments.append(delta)
                continue

            if event_type == "turn/completed":
                break

        await flush_reasoning()
        assistant_text = "".join(assistant_fragments).strip()
        logger.info("Bridge response received thread=%r assistant=%r", thread_id, assistant_text)
        if assistant_text:
            await self._send_reply(
                message,
                text=self._format_final_reply(assistant_text),
                mode="bridge_final",
            )

    async def run(self) -> None:
        await self.adapter.start(self.handle_message)
        try:
            await self.adapter.wait()
        finally:
            await self.adapter.close()
