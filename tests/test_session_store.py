from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from codex_chat_gateway.session_store import InMemorySessionStore
from codex_chat_gateway.session_store import JsonSessionStore
from codex_chat_gateway.session_store import PendingBridgeRequest


class SessionStoreTests(unittest.TestCase):
    def test_get_or_create_reuses_same_session(self) -> None:
        store = InMemorySessionStore()

        first = store.get_or_create("whatsapp:group")
        second = store.get_or_create("whatsapp:group")

        self.assertIs(first, second)

    def test_set_thread_id_updates_session(self) -> None:
        store = InMemorySessionStore()

        store.set_thread_id("whatsapp:group", "thr_1")

        self.assertEqual(store.get("whatsapp:group").thread_id, "thr_1")

    def test_set_pending_request_updates_session(self) -> None:
        store = InMemorySessionStore()
        pending = PendingBridgeRequest(
            request_id="req_1",
            kind="approval_request",
            text="approval needed",
        )

        store.set_pending_request("whatsapp:group", pending)

        self.assertEqual(store.get("whatsapp:group").pending_request, pending)

    def test_clear_pending_request_returns_previous_request(self) -> None:
        store = InMemorySessionStore()
        pending = PendingBridgeRequest(
            request_id="req_1",
            kind="input_request",
            text="input needed",
        )
        store.set_pending_request("whatsapp:group", pending)

        cleared = store.clear_pending_request("whatsapp:group")

        self.assertEqual(cleared, pending)
        self.assertIsNone(store.get("whatsapp:group").pending_request)

    def test_json_session_store_persists_thread_and_pending_request(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            path = Path(tempdir) / "sessions.json"
            store = JsonSessionStore(path)
            pending = PendingBridgeRequest(
                request_id="req_2",
                kind="approval_request",
                text="approval needed",
                thread_id="thr_1",
                details={"command": "pwd"},
            )

            store.set_thread_id("whatsapp:group", "thr_1")
            store.set_pending_request("whatsapp:group", pending)
            store.set_active_turn("whatsapp:group", True)

            reloaded = JsonSessionStore(path)
            session = reloaded.get("whatsapp:group")

            self.assertIsNotNone(session)
            self.assertEqual(session.thread_id, "thr_1")
            self.assertFalse(session.active_turn)
            self.assertIsNotNone(session.pending_request)
            self.assertEqual(session.pending_request.request_id, "req_2")
            self.assertEqual(session.pending_request.details["command"], "pwd")

    def test_json_session_store_clears_pending_request_and_repersists(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            path = Path(tempdir) / "sessions.json"
            store = JsonSessionStore(path)
            store.set_pending_request(
                "whatsapp:group",
                PendingBridgeRequest(
                    request_id="req_3",
                    kind="input_request",
                    text="question",
                ),
            )

            cleared = store.clear_pending_request("whatsapp:group")
            reloaded = JsonSessionStore(path)

            self.assertIsNotNone(cleared)
            self.assertIsNone(reloaded.get("whatsapp:group").pending_request)
