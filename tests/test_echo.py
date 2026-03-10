from __future__ import annotations

import unittest

from codex_chat_gateway.channel_adapters.base import ChannelAdapter
from codex_chat_gateway.models import InboundMessage
from codex_chat_gateway.models import OutboundMessage
from codex_chat_gateway.services import EchoGateway


class FakeAdapter(ChannelAdapter):
    def __init__(self) -> None:
        self.started = False
        self.sent_messages: list[OutboundMessage] = []

    @property
    def channel_name(self) -> str:
        return "fake"

    async def start(self, handler) -> None:
        self.started = True
        self._handler = handler

    async def wait(self) -> None:
        return None

    async def send_message(self, message: OutboundMessage) -> None:
        self.sent_messages.append(message)

    async def close(self) -> None:
        return None


class EchoGatewayTests(unittest.IsolatedAsyncioTestCase):
    async def test_echo_gateway_replies_with_text_prefix(self) -> None:
        adapter = FakeAdapter()
        gateway = EchoGateway(adapter=adapter, reply_prefix="mirror: ")

        await gateway.handle_message(
            InboundMessage(
                message_id="msg_1",
                channel="whatsapp",
                chat_id="5511999999999@s.whatsapp.net",
                sender_id="5511999999999@s.whatsapp.net",
                text="hello",
            )
        )

        self.assertEqual(len(adapter.sent_messages), 1)
        self.assertEqual(adapter.sent_messages[0].text, "mirror: hello")

    async def test_echo_gateway_ignores_empty_text(self) -> None:
        adapter = FakeAdapter()
        gateway = EchoGateway(adapter=adapter)

        await gateway.handle_message(
            InboundMessage(
                message_id="msg_1",
                channel="whatsapp",
                chat_id="5511999999999@s.whatsapp.net",
                sender_id="5511999999999@s.whatsapp.net",
                text="   ",
            )
        )

        self.assertEqual(adapter.sent_messages, [])
