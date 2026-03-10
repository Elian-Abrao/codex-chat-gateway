from __future__ import annotations

from dataclasses import dataclass
import logging

from ..channel_adapters import ChannelAdapter
from ..models import InboundMessage
from ..models import OutboundMessage

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class EchoGateway:
    adapter: ChannelAdapter
    reply_prefix: str = "echo: "

    async def handle_message(self, message: InboundMessage) -> None:
        text = (message.text or "").strip()
        if not text:
            logger.info(
                "Ignoring inbound message without text chat=%s sender=%s attachments=%d",
                message.chat_id,
                message.sender_id,
                len(message.attachments),
            )
            return
        reply = OutboundMessage.from_inbound(
            message,
            text=f"{self.reply_prefix}{text}",
            metadata={"mode": "echo"},
        )
        logger.info("Echo reply prepared for chat=%s", message.chat_id)
        await self.adapter.send_message(reply)

    async def run(self) -> None:
        await self.adapter.start(self.handle_message)
        try:
            await self.adapter.wait()
        finally:
            await self.adapter.close()
