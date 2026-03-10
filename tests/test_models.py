from __future__ import annotations

import unittest

from codex_chat_gateway.models import Attachment
from codex_chat_gateway.models import InboundMessage
from codex_chat_gateway.models import OutboundMessage


class ModelTests(unittest.TestCase):
    def test_inbound_message_round_trips(self) -> None:
        payload = {
            "messageId": "msg_1",
            "channel": "whatsapp",
            "chatId": "123@g.us",
            "senderId": "5511999999999@s.whatsapp.net",
            "text": "hello",
            "isGroup": True,
            "mentions": ["5511888888888@s.whatsapp.net"],
            "attachments": [
                {
                    "kind": "image",
                    "mimeType": "image/jpeg",
                    "fileName": "photo.jpg",
                    "metadata": {"caption": "demo"},
                }
            ],
            "metadata": {"pushName": "Elian"},
        }

        message = InboundMessage.from_dict(payload)

        self.assertEqual(message.to_dict(), payload)

    def test_outbound_message_can_be_derived_from_inbound(self) -> None:
        inbound = InboundMessage(
            message_id="msg_1",
            channel="whatsapp",
            chat_id="5511999999999@s.whatsapp.net",
            sender_id="5511999999999@s.whatsapp.net",
            text="ping",
            attachments=[Attachment(kind="image")],
        )

        outbound = OutboundMessage.from_inbound(inbound, text="echo: ping")

        self.assertEqual(
            outbound.to_dict(),
            {
                "channel": "whatsapp",
                "chatId": "5511999999999@s.whatsapp.net",
                "text": "echo: ping",
                "replyToMessageId": "msg_1",
                "attachments": [],
                "metadata": {},
            },
        )
