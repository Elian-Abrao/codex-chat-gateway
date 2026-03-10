from __future__ import annotations

import unittest

from codex_chat_gateway.session_store import InMemorySessionStore


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
