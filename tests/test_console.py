from __future__ import annotations

import unittest

from codex_chat_gateway.channel_adapters.base import ChannelAdapter
from codex_chat_gateway.models import InboundMessage
from codex_chat_gateway.models import OutboundMessage
from codex_chat_gateway.runtime_client import BridgeClient
from codex_chat_gateway.services.console import ConsoleGateway


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
    async def chat(self, prompt: str, *, thread_id: str | None = None, **kwargs):
        raise AssertionError("console tests should use stream_consumer_chat")

    async def stream_consumer_chat(self, prompt: str, *, thread_id: str | None = None, **kwargs):
        yield {"event": "status", "phase": "thread_started", "threadId": "thr_1", "message": "Thread started."}
        yield {"event": "status", "phase": "turn_started", "threadId": "thr_1", "turnId": "turn_1", "message": "Turn started."}
        yield {
            "event": "commentary",
            "threadId": "thr_1",
            "turnId": "turn_1",
            "text": "Vou verificar agora.",
        }
        yield {
            "event": "action",
            "threadId": "thr_1",
            "turnId": "turn_1",
            "text": "Executing command: uptime",
            "actionType": "command_execution",
        }
        yield {
            "event": "final",
            "threadId": "thr_1",
            "turnId": "turn_1",
            "text": "ok",
        }


class ConsoleGatewayTests(unittest.IsolatedAsyncioTestCase):
    async def test_terminal_text_sends_to_whatsapp_and_codex(self) -> None:
        adapter = FakeAdapter()
        terminal: list[str] = []
        gateway = ConsoleGateway(
            adapter=adapter,
            bridge_client=FakeBridgeClient("http://127.0.0.1:8787"),
            allowed_group_subjects=set(),
            allowed_group_chat_ids={"123@g.us"},
            output=terminal.append,
        )

        keep_going = await gateway.handle_console_line("ping")

        self.assertTrue(keep_going)
        self.assertEqual(
            [message.text for message in adapter.sent_messages],
            ["ping", "[Codex]\nok"],
        )
        self.assertIn("[whatsapp][out][terminal] ping", terminal)
        self.assertIn("[codex][status]\nProcessando...", terminal)
        self.assertIn("[codex][commentary]\n[Codex • andamento]\nVou verificar agora.", terminal)
        self.assertIn("[codex][action]\n[Codex • ações]\n> executando comando: uptime", terminal)
        self.assertIn("[codex][final]\n[Codex]\nok", terminal)

    async def test_inbound_group_message_is_mirrored_to_terminal(self) -> None:
        adapter = FakeAdapter()
        terminal: list[str] = []
        gateway = ConsoleGateway(
            adapter=adapter,
            bridge_client=FakeBridgeClient("http://127.0.0.1:8787"),
            allowed_group_subjects={"Codex"},
            allowed_group_chat_ids=set(),
            send_bridge_replies=False,
            output=terminal.append,
        )

        await gateway.handle_message(
            InboundMessage(
                message_id="msg_1",
                channel="whatsapp",
                chat_id="123@g.us",
                sender_id="55110000@s.whatsapp.net",
                text="oi",
                is_group=True,
                metadata={"groupSubject": "Codex", "pushName": "Elian"},
            )
        )

        self.assertEqual(adapter.sent_messages, [])
        self.assertIn("[whatsapp][in][Codex][Elian] oi", terminal)
        self.assertIn("[codex][status]\nProcessando...", terminal)
        self.assertIn("[codex][final]\n[Codex]\nok", terminal)
