from __future__ import annotations

from dataclasses import dataclass
from typing import AsyncIterator
from typing import Literal

from ..runtime_client import BridgeClient
from ..session_store import InMemorySessionStore

BridgeUpdateMode = Literal["commentary", "reasoning", "action", "final"]
FINAL_REPLY_HEADER = "[Codex]"
COMMENTARY_REPLY_HEADER = "[Codex • andamento]"
REASONING_REPLY_HEADER = "[Codex • raciocínio]"
ACTION_REPLY_HEADER = "[Codex • ações]"
REASONING_CHUNK_TARGET = 160
COMMENTARY_CHUNK_TARGET = 120


@dataclass(slots=True)
class BridgeUpdate:
    mode: BridgeUpdateMode
    text: str


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

    async def stream_prompt(
        self,
        *,
        session_key: str,
        prompt: str,
    ) -> AsyncIterator[BridgeUpdate]:
        session = self.session_store.get_or_create(session_key)
        thread_id = session.thread_id
        assistant_fragments: list[str] = []
        commentary_buffer = ""
        reasoning_buffer = ""
        agent_message_phases: dict[str, str | None] = {}
        announced_events: set[str] = set()

        def flush_commentary(force: bool = False) -> BridgeUpdate | None:
            nonlocal commentary_buffer
            if not self.show_commentary:
                commentary_buffer = ""
                return None
            chunk = commentary_buffer.strip()
            if not chunk:
                return None
            if not force and not (
                len(commentary_buffer) >= COMMENTARY_CHUNK_TARGET
                or commentary_buffer.endswith((".", "!", "?", "\n", ":"))
            ):
                return None
            commentary_buffer = ""
            return BridgeUpdate("commentary", self._format_commentary_reply(chunk))

        def flush_reasoning(force: bool = False) -> BridgeUpdate | None:
            nonlocal reasoning_buffer
            if not self.show_reasoning:
                reasoning_buffer = ""
                return None
            chunk = reasoning_buffer.strip()
            if not chunk:
                return None
            if not force and not (
                len(reasoning_buffer) >= REASONING_CHUNK_TARGET
                or reasoning_buffer.endswith((".", "!", "?", "\n"))
            ):
                return None
            reasoning_buffer = ""
            return BridgeUpdate("reasoning", self._format_reasoning_reply(chunk))

        def make_action_update(key: str, text: str) -> BridgeUpdate | None:
            if not self.show_actions or key in announced_events:
                return None
            announced_events.add(key)
            return BridgeUpdate("action", self._format_action_reply(text))

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
                self.session_store.set_thread_id(session_key, thread_id)

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
                    maybe_commentary = flush_commentary(force=True)
                    if maybe_commentary is not None:
                        yield maybe_commentary
                    maybe_reasoning = flush_reasoning(force=True)
                    if maybe_reasoning is not None:
                        yield maybe_reasoning
                    update = make_action_update(
                        f"commandExecution:{item_id}",
                        f"executando comando: {item.get('command') or '<sem comando>'}",
                    )
                    if update is not None:
                        yield update
                    continue
                if item_type == "mcpToolCall" and isinstance(item_id, str):
                    maybe_commentary = flush_commentary(force=True)
                    if maybe_commentary is not None:
                        yield maybe_commentary
                    maybe_reasoning = flush_reasoning(force=True)
                    if maybe_reasoning is not None:
                        yield maybe_reasoning
                    update = make_action_update(
                        f"mcpToolCall:{item_id}",
                        f"tool MCP: {item.get('server') or '?'}/{item.get('tool') or '?'}",
                    )
                    if update is not None:
                        yield update
                    continue
                if item_type == "dynamicToolCall" and isinstance(item_id, str):
                    maybe_commentary = flush_commentary(force=True)
                    if maybe_commentary is not None:
                        yield maybe_commentary
                    maybe_reasoning = flush_reasoning(force=True)
                    if maybe_reasoning is not None:
                        yield maybe_reasoning
                    update = make_action_update(
                        f"dynamicToolCall:{item_id}",
                        f"tool: {item.get('tool') or '?'}",
                    )
                    if update is not None:
                        yield update
                    continue
                continue

            if event_type == "item/agentMessage/delta":
                item_id = payload.get("itemId")
                if not isinstance(item_id, str):
                    continue
                phase = agent_message_phases.get(item_id)
                delta = payload.get("delta", "")
                if not isinstance(delta, str) or not delta:
                    continue
                if phase == "commentary":
                    commentary_buffer += delta
                    update = flush_commentary(force=False)
                    if update is not None:
                        yield update
                    continue
                if phase in (None, "final_answer"):
                    assistant_fragments.append(delta)
                continue

            if event_type == "item/reasoning/summaryTextDelta":
                delta = payload.get("delta", "")
                if isinstance(delta, str) and delta:
                    reasoning_buffer += delta
                    update = flush_reasoning(force=False)
                    if update is not None:
                        yield update
                continue

            if event_type == "item/tool/call":
                maybe_commentary = flush_commentary(force=True)
                if maybe_commentary is not None:
                    yield maybe_commentary
                maybe_reasoning = flush_reasoning(force=True)
                if maybe_reasoning is not None:
                    yield maybe_reasoning
                request_id = event.get("requestId")
                update = make_action_update(
                    f"toolCall:{request_id or payload.get('tool') or '<tool desconhecida>'}",
                    f"tool solicitada: {payload.get('tool') or '<tool desconhecida>'}",
                )
                if update is not None:
                    yield update
                continue

            if event_type == "item/commandExecution/requestApproval":
                maybe_commentary = flush_commentary(force=True)
                if maybe_commentary is not None:
                    yield maybe_commentary
                maybe_reasoning = flush_reasoning(force=True)
                if maybe_reasoning is not None:
                    yield maybe_reasoning
                request_id = event.get("requestId")
                update = make_action_update(
                    f"commandApproval:{request_id or payload.get('command') or '<comando desconhecido>'}",
                    f"aprovação necessária para comando: {payload.get('command') or '<comando desconhecido>'}",
                )
                if update is not None:
                    yield update
                continue

            if event_type == "item/fileChange/requestApproval":
                maybe_commentary = flush_commentary(force=True)
                if maybe_commentary is not None:
                    yield maybe_commentary
                maybe_reasoning = flush_reasoning(force=True)
                if maybe_reasoning is not None:
                    yield maybe_reasoning
                request_id = event.get("requestId")
                update = make_action_update(
                    f"fileApproval:{request_id or 'file-change'}",
                    "aprovação necessária para alterações de arquivos",
                )
                if update is not None:
                    yield update
                continue

            if event_type == "item/tool/requestUserInput":
                maybe_commentary = flush_commentary(force=True)
                if maybe_commentary is not None:
                    yield maybe_commentary
                maybe_reasoning = flush_reasoning(force=True)
                if maybe_reasoning is not None:
                    yield maybe_reasoning
                request_id = event.get("requestId")
                update = make_action_update(
                    f"userInput:{request_id or 'tool-input'}",
                    "aguardando entrada do usuário para continuar",
                )
                if update is not None:
                    yield update
                continue

            if event_type == "turn/completed":
                break

        update = flush_commentary(force=True)
        if update is not None:
            yield update

        update = flush_reasoning(force=True)
        if update is not None:
            yield update

        assistant_text = "".join(assistant_fragments).strip()
        if assistant_text:
            yield BridgeUpdate("final", self._format_final_reply(assistant_text))
