from __future__ import annotations

import unittest

from codex_chat_gateway.channel_adapters.base import ChannelAdapter
from codex_chat_gateway.models import InboundMessage
from codex_chat_gateway.models import OutboundMessage
from codex_chat_gateway.runtime_client import BridgeClient
from codex_chat_gateway.services import BridgeChatGateway
from codex_chat_gateway.session_store import InMemorySessionStore


class FakeAdapter(ChannelAdapter):
    def __init__(self) -> None:
        self.sent_messages: list[OutboundMessage] = []

    @property
    def channel_name(self) -> str:
        return "whatsapp"

    async def start(self, handler) -> None:
        self._handler = handler

    async def wait(self) -> None:
        return None

    async def send_message(self, message: OutboundMessage) -> None:
        self.sent_messages.append(message)

    async def close(self) -> None:
        return None


class FakeBridgeClient(BridgeClient):
    def __init__(self) -> None:
        self.calls: list[dict[str, str | None]] = []
        self.stream_calls: list[dict[str, str | None]] = []

    async def chat(self, prompt: str, *, thread_id: str | None = None, **kwargs) -> dict[str, str]:
        self.calls.append({"prompt": prompt, "thread_id": thread_id})
        return {
            "threadId": "thr_1",
            "assistantText": "ok",
        }

    async def stream_consumer_chat(self, prompt: str, *, thread_id: str | None = None, **kwargs):
        self.stream_calls.append(
            {
                "prompt": prompt,
                "thread_id": thread_id,
                "summary": kwargs.get("summary"),
            }
        )
        yield {"event": "status", "phase": "thread_started", "threadId": "thr_1", "message": "Thread started."}
        yield {"event": "status", "phase": "turn_started", "threadId": "thr_1", "turnId": "turn_1", "message": "Turn started."}
        yield {
            "event": "commentary",
            "threadId": "thr_1",
            "turnId": "turn_1",
            "text": "Vou verificar agora.",
        }
        yield {
            "event": "reasoning_summary",
            "threadId": "thr_1",
            "turnId": "turn_1",
            "text": "Analisando o pedido.",
        }
        yield {
            "event": "action",
            "threadId": "thr_1",
            "turnId": "turn_1",
            "text": "Executing command: pwd",
            "actionType": "command_execution",
        }
        yield {
            "event": "final",
            "threadId": "thr_1",
            "turnId": "turn_1",
            "text": "ok",
        }


class BridgeChatGatewayTests(unittest.IsolatedAsyncioTestCase):
    async def test_gateway_ignores_messages_outside_target_group(self) -> None:
        adapter = FakeAdapter()
        bridge = FakeBridgeClient()
        gateway = BridgeChatGateway(
            adapter=adapter,
            bridge_client=bridge,
            session_store=InMemorySessionStore(),
            allowed_group_subjects={"Codex"},
            allowed_group_chat_ids=set(),
            send_replies=False,
        )

        await gateway.handle_message(
            InboundMessage(
                message_id="msg_1",
                channel="whatsapp",
                chat_id="123@g.us",
                sender_id="other@s.whatsapp.net",
                text="hello",
                is_group=True,
                metadata={"fromMe": False, "groupSubject": "Other"},
            )
        )

        self.assertEqual(bridge.stream_calls, [])

    async def test_gateway_forwards_messages_in_matching_group(self) -> None:
        adapter = FakeAdapter()
        bridge = FakeBridgeClient()
        store = InMemorySessionStore()
        gateway = BridgeChatGateway(
            adapter=adapter,
            bridge_client=bridge,
            session_store=store,
            allowed_group_subjects={"Codex"},
            allowed_group_chat_ids=set(),
        )

        await gateway.handle_message(
            InboundMessage(
                message_id="msg_1",
                channel="whatsapp",
                chat_id="123@g.us",
                sender_id="other@s.whatsapp.net",
                text="Oi",
                is_group=True,
                metadata={"fromMe": False, "groupSubject": "Codex"},
            )
        )

        self.assertEqual(
            bridge.stream_calls,
            [{"prompt": "Oi", "thread_id": None, "summary": "none"}],
        )
        self.assertEqual(store.get("whatsapp:123@g.us").thread_id, "thr_1")
        self.assertEqual([message.text for message in adapter.sent_messages], ["[Codex]\nok"])

    async def test_gateway_can_emit_progress_updates_when_enabled(self) -> None:
        adapter = FakeAdapter()
        bridge = FakeBridgeClient()
        gateway = BridgeChatGateway(
            adapter=adapter,
            bridge_client=bridge,
            session_store=InMemorySessionStore(),
            allowed_group_subjects={"Codex"},
            allowed_group_chat_ids=set(),
            show_commentary=True,
            show_reasoning=True,
            show_actions=True,
        )

        await gateway.handle_message(
            InboundMessage(
                message_id="msg_1",
                channel="whatsapp",
                chat_id="123@g.us",
                sender_id="other@s.whatsapp.net",
                text="Oi",
                is_group=True,
                metadata={"fromMe": False, "groupSubject": "Codex"},
            )
        )

        self.assertEqual(
            bridge.stream_calls,
            [{"prompt": "Oi", "thread_id": None, "summary": "detailed"}],
        )
        self.assertEqual(len(adapter.sent_messages), 4)
        self.assertEqual(
            [message.text for message in adapter.sent_messages],
            [
                "[Codex • andamento]\nVou verificar agora.",
                "[Codex • raciocínio]\nAnalisando o pedido.",
                "[Codex • ações]\n> executando comando: pwd",
                "[Codex]\nok",
            ],
        )

    async def test_gateway_can_run_in_log_only_mode(self) -> None:
        adapter = FakeAdapter()
        bridge = FakeBridgeClient()
        gateway = BridgeChatGateway(
            adapter=adapter,
            bridge_client=bridge,
            session_store=InMemorySessionStore(),
            allowed_group_subjects={"Codex"},
            allowed_group_chat_ids=set(),
            send_replies=False,
        )

        await gateway.handle_message(
            InboundMessage(
                message_id="msg_1",
                channel="whatsapp",
                chat_id="123@g.us",
                sender_id="other@s.whatsapp.net",
                text="Oi",
                is_group=True,
                metadata={"fromMe": False, "groupSubject": "Codex"},
            )
        )

        self.assertEqual(adapter.sent_messages, [])
