from __future__ import annotations

from abc import ABC
from abc import abstractmethod
from typing import Awaitable, Callable

from ..models import InboundMessage
from ..models import OutboundMessage

MessageHandler = Callable[[InboundMessage], Awaitable[None]]


class ChannelAdapter(ABC):
    @property
    @abstractmethod
    def channel_name(self) -> str: ...

    @abstractmethod
    async def start(self, handler: MessageHandler) -> None: ...

    @abstractmethod
    async def wait(self) -> None: ...

    @abstractmethod
    async def send_message(self, message: OutboundMessage) -> None: ...

    @abstractmethod
    async def close(self) -> None: ...
