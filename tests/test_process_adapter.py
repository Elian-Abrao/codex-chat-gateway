from __future__ import annotations

import logging
import unittest

from codex_chat_gateway.channel_adapters.process import _normalize_worker_stderr_line


class ProcessAdapterTests(unittest.TestCase):
    def test_transient_baileys_counter_error_is_downgraded_to_debug(self) -> None:
        level, message = _normalize_worker_stderr_line(
            '{"level":50,"msg":"failed to decrypt message","err":{"name":"MessageCounterError"}}'
        )

        self.assertEqual(level, logging.DEBUG)
        self.assertEqual(message, "failed to decrypt message")

    def test_prekey_bundle_session_repair_is_downgraded_to_debug(self) -> None:
        level, message = _normalize_worker_stderr_line("Closing open session in favor of incoming prekey bundle")

        self.assertEqual(level, logging.DEBUG)
        self.assertEqual(message, "Closing open session in favor of incoming prekey bundle")

    def test_regular_worker_stderr_stays_at_info(self) -> None:
        level, message = _normalize_worker_stderr_line("WhatsApp connection opened.")

        self.assertEqual(level, logging.INFO)
        self.assertEqual(message, "WhatsApp connection opened.")
