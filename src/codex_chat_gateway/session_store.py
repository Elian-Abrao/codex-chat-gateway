from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class ConversationSession:
    key: str
    thread_id: str | None = None


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
