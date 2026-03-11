from __future__ import annotations

from dataclasses import dataclass
import logging

from ..channel_adapters import ChannelAdapter
from ..models import InboundMessage
from ..models import OutboundMessage
from ..runtime_client import BridgeClient
from ..session_store import InMemorySessionStore
from .bridge_runtime import BridgeTurnRunner
from .group_target import matches_target_group
from .group_target import session_key_for_message

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

    @property
    def bridge_turn_runner(self) -> BridgeTurnRunner:
        return BridgeTurnRunner(
            bridge_client=self.bridge_client,
            session_store=self.session_store,
            show_commentary=self.show_commentary,
            show_reasoning=self.show_reasoning,
            show_actions=self.show_actions,
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

    def _matches_target_group(self, message: InboundMessage) -> bool:
        return matches_target_group(
            message,
            allowed_group_subjects=self.allowed_group_subjects,
            allowed_group_chat_ids=self.allowed_group_chat_ids,
        )

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
        async for update in self.bridge_turn_runner.stream_prompt(
            session_key=key,
            prompt=prompt,
        ):
            mode = f"bridge_{update.mode}"
            if update.mode == "final":
                logger.info("Bridge response received assistant=%r", update.text)
            await self._send_reply(message, text=update.text, mode=mode)

    async def run(self) -> None:
        await self.adapter.start(self.handle_message)
        try:
            await self.adapter.wait()
        finally:
            await self.adapter.close()
