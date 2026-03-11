from __future__ import annotations

import asyncio
from dataclasses import dataclass
from dataclasses import field
from typing import Any
from typing import AsyncIterator
from typing import Literal

from ..models import Attachment
from ..runtime_client import BridgeClient
from ..session_store import InMemorySessionStore
from ..session_store import PendingBridgeRequest
from .attachment_directives import extract_attachment_directives

BridgeUpdateMode = Literal["commentary", "reasoning", "action", "final"]
FINAL_REPLY_HEADER = "[Codex]"
COMMENTARY_REPLY_HEADER = "[Codex • andamento]"
REASONING_REPLY_HEADER = "[Codex • raciocínio]"
ACTION_REPLY_HEADER = "[Codex • ações]"


@dataclass(slots=True)
class BridgeUpdate:
    mode: BridgeUpdateMode
    text: str | None = None
    attachments: list[Attachment] = field(default_factory=list)
    pending_request: PendingBridgeRequest | None = None
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class BridgeTurnRunner:
    bridge_client: BridgeClient
    session_store: InMemorySessionStore
    show_commentary: bool = False
    show_reasoning: bool = False
    show_actions: bool = False
    approval_policy: str | None = None
    sandbox: str | None = None

    def _extract_turn(self, payload: dict[str, Any], turn_id: str | None) -> dict[str, Any] | None:
        thread = payload.get("thread")
        if not isinstance(thread, dict):
            return None
        turns = thread.get("turns")
        if not isinstance(turns, list):
            return None
        if turn_id is None:
            for turn in reversed(turns):
                if isinstance(turn, dict):
                    return turn
            return None
        for turn in turns:
            if isinstance(turn, dict) and turn.get("id") == turn_id:
                return turn
        return None

    def _extract_turn_final_text(self, turn: dict[str, Any]) -> str | None:
        items = turn.get("items")
        if not isinstance(items, list):
            return None
        fallback_text: str | None = None
        for item in items:
            if not isinstance(item, dict):
                continue
            if item.get("type") != "agentMessage":
                continue
            text = item.get("text")
            if not isinstance(text, str) or not text.strip():
                continue
            phase = item.get("phase")
            if phase == "final_answer":
                return text.strip()
            if fallback_text is None:
                fallback_text = text.strip()
        return fallback_text

    def _extract_turn_error(self, turn: dict[str, Any]) -> str | None:
        error = turn.get("error")
        if isinstance(error, str) and error.strip():
            return error.strip()
        if isinstance(error, dict):
            message = error.get("message")
            if isinstance(message, str) and message.strip():
                return message.strip()
        return None

    def _format_final_reply(self, text: str) -> str:
        return f"{FINAL_REPLY_HEADER}\n{text.strip()}"

    def _format_commentary_reply(self, text: str) -> str:
        return f"{COMMENTARY_REPLY_HEADER}\n{text.strip()}"

    def _format_reasoning_reply(self, text: str) -> str:
        return f"{REASONING_REPLY_HEADER}\n{text.strip()}"

    def _format_action_reply(self, text: str) -> str:
        quoted = "\n".join(f"> {line}" for line in text.strip().splitlines())
        return f"{ACTION_REPLY_HEADER}\n{quoted}"

    def _extract_attachments(self, event: dict[str, Any]) -> list[Attachment]:
        raw_attachments = event.get("attachments")
        if not isinstance(raw_attachments, list):
            return []
        attachments: list[Attachment] = []
        for item in raw_attachments:
            if not isinstance(item, dict):
                continue
            try:
                attachments.append(Attachment.from_dict(item))
            except (KeyError, TypeError, ValueError):
                continue
        return attachments

    def _extract_attachment_error_note(self, event: dict[str, Any]) -> str | None:
        details = event.get("details")
        if not isinstance(details, dict):
            return None
        errors = details.get("attachmentErrors")
        if not isinstance(errors, list):
            return None
        normalized = [str(item).strip() for item in errors if str(item).strip()]
        if not normalized:
            return None
        lines = ["Obs.: não consegui anexar alguns arquivos:"]
        lines.extend(f"- {item}" for item in normalized)
        return "\n".join(lines)

    def _build_final_update(
        self,
        *,
        text: str | None,
        attachments: list[Attachment],
        error_note: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> BridgeUpdate:
        final_body = text.strip() if isinstance(text, str) else ""
        if error_note:
            final_body = f"{final_body}\n\n{error_note}" if final_body else error_note
        if not final_body and attachments:
            noun = "anexo" if len(attachments) == 1 else "anexos"
            final_body = f"Enviei {len(attachments)} {noun}."
        formatted = self._format_final_reply(final_body) if final_body else None
        return BridgeUpdate("final", formatted, attachments=attachments, details=details or {})

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
            approvalPolicy=self.approval_policy,
            sandbox=self.sandbox,
        ):
            event_type = event.get("event")
            event_thread_id = event.get("threadId")
            if isinstance(event_thread_id, str) and event_thread_id:
                thread_id = event_thread_id
                self.session_store.set_thread_id(session_key, thread_id)

            text = event.get("text")
            normalized = text.strip() if isinstance(text, str) else ""

            if event_type == "commentary":
                if not normalized:
                    continue
                if self.show_commentary:
                    yield BridgeUpdate("commentary", self._format_commentary_reply(normalized))
                continue

            if event_type == "reasoning_summary":
                if not normalized:
                    continue
                if self.show_reasoning:
                    yield BridgeUpdate("reasoning", self._format_reasoning_reply(normalized))
                continue

            if event_type in {"action", "approval_request", "input_request"}:
                if not normalized:
                    continue
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
                attachments = self._extract_attachments(event)
                error_note = self._extract_attachment_error_note(event)
                yield self._build_final_update(text=normalized, attachments=attachments, error_note=error_note)
                continue

            if event_type == "error":
                error_text = normalized or str(event.get("message") or "erro desconhecido")
                yield BridgeUpdate("final", self._format_final_reply(f"Erro do bridge: {error_text}"))

    async def recover_pending_turn(
        self,
        *,
        session_key: str,
        thread_id: str | None,
        turn_id: str | None,
        timeout_s: float = 20.0,
        poll_interval_s: float = 0.5,
    ) -> BridgeUpdate | None:
        if thread_id is None:
            return None

        deadline = asyncio.get_running_loop().time() + timeout_s
        while True:
            payload = await self.bridge_client.resume_thread(thread_id)
            thread = payload.get("thread")
            if isinstance(thread, dict):
                resumed_thread_id = thread.get("id")
                if isinstance(resumed_thread_id, str) and resumed_thread_id:
                    self.session_store.set_thread_id(session_key, resumed_thread_id)
            turn = self._extract_turn(payload, turn_id)
            if isinstance(turn, dict):
                status = turn.get("status")
                if status == "completed":
                    final_text = self._extract_turn_final_text(turn)
                    if final_text:
                        parsed = extract_attachment_directives(final_text)
                        error_note = None
                        if parsed.errors:
                            error_note = "Obs.: não consegui anexar alguns arquivos:\n" + "\n".join(
                                f"- {item}" for item in parsed.errors
                            )
                        return self._build_final_update(
                            text=parsed.text,
                            attachments=parsed.attachments,
                            error_note=error_note,
                            details={"recovered": True, "turnStatus": status},
                        )
                    return None
                if status in {"failed", "cancelled", "interrupted"}:
                    error_text = self._extract_turn_error(turn) or f"Turn finalizado com status {status}."
                    return BridgeUpdate(
                        "final",
                        self._format_final_reply(f"Erro do bridge: {error_text}"),
                        details={"recovered": True, "turnStatus": status},
                    )

            if asyncio.get_running_loop().time() >= deadline:
                return None
            await asyncio.sleep(poll_interval_s)
