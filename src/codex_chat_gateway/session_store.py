from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
import json
import logging
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any
from typing import Literal

PendingRequestKind = Literal["approval_request", "input_request"]
logger = logging.getLogger(__name__)


@dataclass(slots=True)
class PendingBridgeRequest:
    request_id: str | int
    kind: PendingRequestKind
    text: str
    thread_id: str | None = None
    turn_id: str | None = None
    approval_type: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "requestId": self.request_id,
            "kind": self.kind,
            "text": self.text,
            "threadId": self.thread_id,
            "turnId": self.turn_id,
            "approvalType": self.approval_type,
            "details": self.details,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PendingBridgeRequest:
        kind = data.get("kind")
        if kind not in {"approval_request", "input_request"}:
            raise ValueError(f"invalid pending request kind: {kind!r}")
        return cls(
            request_id=data["requestId"],
            kind=kind,
            text=str(data.get("text") or ""),
            thread_id=data.get("threadId") if isinstance(data.get("threadId"), str) else None,
            turn_id=data.get("turnId") if isinstance(data.get("turnId"), str) else None,
            approval_type=data.get("approvalType") if isinstance(data.get("approvalType"), str) else None,
            details=dict(data.get("details") or {}),
        )


@dataclass(slots=True)
class ConversationSession:
    key: str
    thread_id: str | None = None
    active_turn: bool = False
    pending_request: PendingBridgeRequest | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "key": self.key,
            "threadId": self.thread_id,
            "activeTurn": self.active_turn,
        }
        if self.pending_request is not None:
            payload["pendingRequest"] = self.pending_request.to_dict()
        return payload

    @classmethod
    def from_dict(
        cls,
        data: dict[str, Any],
        *,
        reset_active_turn: bool = True,
    ) -> ConversationSession:
        pending_request: PendingBridgeRequest | None = None
        raw_pending = data.get("pendingRequest")
        if isinstance(raw_pending, dict):
            pending_request = PendingBridgeRequest.from_dict(raw_pending)
        return cls(
            key=data["key"],
            thread_id=data.get("threadId") if isinstance(data.get("threadId"), str) else None,
            active_turn=False if reset_active_turn else bool(data.get("activeTurn", False)),
            pending_request=pending_request,
        )


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

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": 1,
            "sessions": [session.to_dict() for session in sorted(self._sessions.values(), key=lambda item: item.key)],
        }

    def _load_from_dict(self, payload: dict[str, Any]) -> None:
        sessions = payload.get("sessions")
        if not isinstance(sessions, list):
            raise ValueError("session store payload is missing a valid 'sessions' list")
        loaded: dict[str, ConversationSession] = {}
        for item in sessions:
            if not isinstance(item, dict):
                raise ValueError("session store contains a non-object session entry")
            session = ConversationSession.from_dict(item, reset_active_turn=True)
            loaded[session.key] = session
        self._sessions = loaded


class JsonSessionStore(InMemorySessionStore):
    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        super().__init__()
        self._load()

    @property
    def path(self) -> Path:
        return self._path

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("session store root must be an object")
            self._load_from_dict(payload)
        except Exception as exc:
            backup_path = self._path.with_suffix(self._path.suffix + ".corrupt")
            try:
                self._path.replace(backup_path)
            except OSError:
                backup_path = self._path
            logger.warning(
                "Failed to load persisted session store from %s; starting fresh. Backup=%s error=%s",
                self._path,
                backup_path,
                exc,
            )
            self._sessions = {}

    def _persist(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = self.to_dict()
        with NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=str(self._path.parent),
            prefix=f".{self._path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            temp_path = Path(handle.name)
        temp_path.replace(self._path)

    def set_thread_id(self, key: str, thread_id: str) -> None:
        super().set_thread_id(key, thread_id)
        self._persist()

    def set_active_turn(self, key: str, active: bool) -> ConversationSession:
        session = super().set_active_turn(key, active)
        self._persist()
        return session

    def set_pending_request(self, key: str, pending_request: PendingBridgeRequest) -> ConversationSession:
        session = super().set_pending_request(key, pending_request)
        self._persist()
        return session

    def clear_pending_request(self, key: str) -> PendingBridgeRequest | None:
        cleared = super().clear_pending_request(key)
        self._persist()
        return cleared
