from __future__ import annotations

import unittest
from pathlib import Path

from codex_chat_gateway.channel_adapters import available_builtin_adapters
from codex_chat_gateway.channel_adapters import create_builtin_adapter
from codex_chat_gateway.cli import _default_session_store_path
from codex_chat_gateway.cli import build_parser


class CliTests(unittest.TestCase):
    def test_parser_accepts_echo_command(self) -> None:
        args = build_parser().parse_args(["echo", "--channel", "whatsapp-baileys"])

        self.assertEqual(args.command, "echo")
        self.assertEqual(args.channel, "whatsapp-baileys")

    def test_builtin_adapter_factory_knows_whatsapp_baileys(self) -> None:
        self.assertIn("whatsapp-baileys", available_builtin_adapters())
        adapter = create_builtin_adapter("whatsapp-baileys")
        self.assertEqual(adapter.channel_name, "whatsapp")
        self.assertEqual(adapter._env["LOG_LEVEL"], "warn")

    def test_parser_accepts_bridge_chat_command(self) -> None:
        args = build_parser().parse_args(
            ["bridge-chat", "--group-subject", "Codex", "--bridge-url", "http://127.0.0.1:8787"]
        )

        self.assertEqual(args.command, "bridge-chat")
        self.assertEqual(args.group_subject, ["Codex"])
        self.assertFalse(args.log_only)
        self.assertFalse(args.show_commentary)
        self.assertFalse(args.show_reasoning)
        self.assertFalse(args.show_actions)
        self.assertIsNone(args.session_store)

    def test_parser_accepts_optional_progress_flags(self) -> None:
        args = build_parser().parse_args(
            [
                "bridge-chat",
                "--group-subject",
                "Codex",
                "--show-commentary",
                "--show-reasoning",
                "--show-actions",
            ]
        )

        self.assertTrue(args.show_commentary)
        self.assertTrue(args.show_reasoning)
        self.assertTrue(args.show_actions)

    def test_parser_accepts_console_command(self) -> None:
        args = build_parser().parse_args(
            [
                "console",
                "--group-chat-id",
                "123@g.us",
                "--bridge-url",
                "http://127.0.0.1:8787",
            ]
        )

        self.assertEqual(args.command, "console")
        self.assertEqual(args.group_chat_id, ["123@g.us"])
        self.assertEqual(args.bridge_url, "http://127.0.0.1:8787")
        self.assertFalse(args.log_only)
        self.assertFalse(args.show_commentary)
        self.assertIsNone(args.session_store)

    def test_parser_accepts_console_progress_flags(self) -> None:
        args = build_parser().parse_args(
            [
                "console",
                "--group-chat-id",
                "123@g.us",
                "--show-commentary",
                "--show-reasoning",
                "--show-actions",
            ]
        )

        self.assertTrue(args.show_commentary)
        self.assertTrue(args.show_reasoning)
        self.assertTrue(args.show_actions)

    def test_parser_accepts_runtime_execution_flags(self) -> None:
        args = build_parser().parse_args(
            [
                "bridge-chat",
                "--group-subject",
                "Codex",
                "--approval-policy",
                "never",
                "--sandbox",
                "danger-full-access",
                "--full-auto",
            ]
        )

        self.assertEqual(args.approval_policy, "never")
        self.assertEqual(args.sandbox, "danger-full-access")
        self.assertTrue(args.full_auto)

    def test_default_session_store_path_uses_auth_dir_parent(self) -> None:
        self.assertEqual(
            _default_session_store_path(".state/whatsapp"),
            Path(".state") / "sessions.json",
        )
