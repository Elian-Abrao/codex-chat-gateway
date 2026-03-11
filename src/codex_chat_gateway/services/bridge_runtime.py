from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
from typing import Any
from typing import AsyncIterator
from typing import Literal

from ..runtime_client import BridgeClient
from ..session_store import InMemorySessionStore
from ..session_store import PendingBridgeRequest

BridgeUpdateMode = Literal["commentary", "reasoning", "action", "final"]
FINAL_REPLY_HEADER = "[Codex]"
COMMENTARY_REPLY_HEADER = "[Codex • andamento]"
REASONING_REPLY_HEADER = "[Codex • raciocínio]"
ACTION_REPLY_HEADER = "[Codex • ações]"


@dataclass(slots=True)
class BridgeUpdate:
    mode: BridgeUpdateMode
    text: str | None = None
    pending_request: PendingBridgeRequest | None = None
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class BridgeTurnRunner:
    bridge_client: BridgeClient
    session_store: InMemorySessionStore
    show_commentary: bool = False
    show_reasoning: bool = False
    show_actions: bool = False

    def _format_final_reply(self, text: str) -> str:
        return f"{FINAL_REPLY_HEADER}\n{text.strip()}"

    def _format_commentary_reply(self, text: str) -> str:
        return f"{COMMENTARY_REPLY_HEADER}\n{text.strip()}"

    def _format_reasoning_reply(self, text: str) -> str:
        return f"{REASONING_REPLY_HEADER}\n{text.strip()}"

    def _format_action_reply(self, text: str) -> str:
        quoted = "\n".join(f"> {line}" for line in text.strip().splitlines())
        return f"{ACTION_REPLY_HEADER}\n{quoted}"

    def _format_action_text(self, event: dict[str, object], normalized: str) -> str:
        event_type = event.get("event")
        details = event.get("details", {})
        if not isinstance(details, dict):
            details = {}

        if event_type == "action":
            action_type = event.get("actionType")
            if action_type == "command_execution":
                item = details.get("item", {})
                if isinstance(item, dict):
                    command = item.get("command")
                    if isinstance(command, str) and command:
                        return f"executando comando: {command}"
                lowered = normalized.lower()
                if lowered.startswith("executing command:"):
                    return f"executando comando: {normalized.split(':', 1)[1].strip()}"
                return normalized
            if action_type == "mcp_tool_call":
                item = details.get("item", {})
                if isinstance(item, dict):
                    server = item.get("server") or "?"
                    tool = item.get("tool") or "?"
                    return f"tool MCP: {server}/{tool}"
                return normalized
            if action_type == "dynamic_tool_call":
                item = details.get("item", {})
                if isinstance(item, dict):
                    tool = item.get("tool") or "?"
                    return f"tool: {tool}"
                return normalized
            if action_type == "tool_call":
                tool = details.get("tool") or "?"
                return f"tool solicitada: {tool}"
            if action_type == "file_change":
                return "alterações de arquivos preparadas"

        if event_type == "approval_request":
            approval_type = event.get("approvalType")
            if approval_type == "command_execution":
                command = details.get("command") or "<comando desconhecido>"
                return f"aprovação necessária para comando: {command}"
            if approval_type == "file_change":
                return "aprovação necessária para alterações de arquivos"

        if event_type == "input_request":
            return "aguardando entrada do usuário para continuar"

        return normalized

    async def stream_prompt(
        self,
        *,
        session_key: str,
        prompt: str,
    ) -> AsyncIterator[BridgeUpdate]:
        session = self.session_store.get_or_create(session_key)
        thread_id = session.thread_id
        async for event in self.bridge_client.stream_consumer_chat(
            prompt,
            thread_id=thread_id,
            summary="detailed" if self.show_reasoning else "none",
        ):
            event_type = event.get("event")
            event_thread_id = event.get("threadId")
            if isinstance(event_thread_id, str) and event_thread_id:
                thread_id = event_thread_id
                self.session_store.set_thread_id(session_key, thread_id)

            text = event.get("text")
            if not isinstance(text, str):
                continue

            normalized = text.strip()
            if not normalized:
                continue

            if event_type == "commentary":
                if self.show_commentary:
                    yield BridgeUpdate("commentary", self._format_commentary_reply(normalized))
                continue

            if event_type == "reasoning_summary":
                if self.show_reasoning:
                    yield BridgeUpdate("reasoning", self._format_reasoning_reply(normalized))
                continue

            if event_type in {"action", "approval_request", "input_request"}:
                pending_request: PendingBridgeRequest | None = None
                should_emit = self.show_actions
                if event_type in {"approval_request", "input_request"}:
                    request_id = event.get("requestId")
                    if request_id is not None:
                        pending_request = PendingBridgeRequest(
                            request_id=request_id,
                            kind=event_type,
                            text=normalized,
                            thread_id=thread_id,
                            turn_id=event.get("turnId") if isinstance(event.get("turnId"), str) else None,
                            approval_type=event.get("approvalType") if isinstance(event.get("approvalType"), str) else None,
                            details=event.get("details") if isinstance(event.get("details"), dict) else {},
                        )
                    should_emit = True
                if should_emit:
                    yield BridgeUpdate(
                        "action",
                        self._format_action_reply(self._format_action_text(event, normalized)),
                        pending_request=pending_request,
                        details=event.get("details") if isinstance(event.get("details"), dict) else {},
                    )
                continue

            if event_type == "final":
                yield BridgeUpdate("final", self._format_final_reply(normalized))
                continue

            if event_type == "error":
                yield BridgeUpdate("final", self._format_final_reply(f"Erro do bridge: {normalized}"))
