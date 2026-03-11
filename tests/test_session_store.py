from __future__ import annotations

import unittest

from codex_chat_gateway.session_store import InMemorySessionStore
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
