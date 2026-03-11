from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
from typing import Any
from typing import Literal

PendingRequestKind = Literal["approval_request", "input_request"]


@dataclass(slots=True)
class PendingBridgeRequest:
    request_id: str | int
    kind: PendingRequestKind
    text: str
    thread_id: str | None = None
    turn_id: str | None = None
    approval_type: str | None = None
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ConversationSession:
    key: str
    thread_id: str | None = None
    active_turn: bool = False
    pending_request: PendingBridgeRequest | None = None


class InMemorySessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, ConversationSession] = {}

    def get(self, key: str) -> ConversationSession | None:
        return self._sessions.get(key)

    def get_or_create(self, key: str) -> ConversationSession:
        existing = self._sessions.get(key)
        if existing is not None:
            return existing
        session = ConversationSession(key=key)
        self._sessions[key] = session
        return session

    def set_thread_id(self, key: str, thread_id: str) -> None:
        session = self.get_or_create(key)
        session.thread_id = thread_id

    def set_active_turn(self, key: str, active: bool) -> ConversationSession:
        session = self.get_or_create(key)
        session.active_turn = active
        return session

    def set_pending_request(self, key: str, pending_request: PendingBridgeRequest) -> ConversationSession:
        session = self.get_or_create(key)
        session.pending_request = pending_request
        return session

    def clear_pending_request(self, key: str) -> PendingBridgeRequest | None:
        session = self.get_or_create(key)
        existing = session.pending_request
        session.pending_request = None
        return existing
