from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
from typing import Any


@dataclass(slots=True)
class Attachment:
    kind: str
    mime_type: str | None = None
    url: str | None = None
    file_name: str | None = None
    size_bytes: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"kind": self.kind}
        if self.mime_type is not None:
            payload["mimeType"] = self.mime_type
        if self.url is not None:
            payload["url"] = self.url
        if self.file_name is not None:
            payload["fileName"] = self.file_name
        if self.size_bytes is not None:
            payload["sizeBytes"] = self.size_bytes
        if self.metadata:
            payload["metadata"] = self.metadata
        return payload

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Attachment:
        return cls(
            kind=data["kind"],
            mime_type=data.get("mimeType"),
            url=data.get("url"),
            file_name=data.get("fileName"),
            size_bytes=data.get("sizeBytes"),
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass(slots=True)
class InboundMessage:
    message_id: str
    channel: str
    chat_id: str
    sender_id: str
    text: str | None = None
    is_group: bool = False
    mentions: list[str] = field(default_factory=list)
    attachments: list[Attachment] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "messageId": self.message_id,
            "channel": self.channel,
            "chatId": self.chat_id,
            "senderId": self.sender_id,
            "text": self.text,
            "isGroup": self.is_group,
            "mentions": self.mentions,
            "attachments": [attachment.to_dict() for attachment in self.attachments],
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> InboundMessage:
        return cls(
            message_id=data["messageId"],
            channel=data["channel"],
            chat_id=data["chatId"],
            sender_id=data["senderId"],
            text=data.get("text"),
            is_group=bool(data.get("isGroup", False)),
            mentions=list(data.get("mentions") or []),
            attachments=[
                Attachment.from_dict(item) for item in (data.get("attachments") or [])
            ],
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass(slots=True)
class OutboundMessage:
    channel: str
    chat_id: str
    text: str | None = None
    reply_to_message_id: str | None = None
    attachments: list[Attachment] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "channel": self.channel,
            "chatId": self.chat_id,
            "text": self.text,
            "replyToMessageId": self.reply_to_message_id,
            "attachments": [attachment.to_dict() for attachment in self.attachments],
            "metadata": self.metadata,
        }

    @classmethod
    def from_inbound(
        cls,
        message: InboundMessage,
        *,
        text: str | None,
        metadata: dict[str, Any] | None = None,
    ) -> OutboundMessage:
        return cls(
            channel=message.channel,
            chat_id=message.chat_id,
            text=text,
            reply_to_message_id=message.message_id,
            metadata=metadata or {},
        )
