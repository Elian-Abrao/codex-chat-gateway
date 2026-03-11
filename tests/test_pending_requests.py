from __future__ import annotations

import unittest

from codex_chat_gateway.services.pending_requests import build_input_answers
from codex_chat_gateway.services.pending_requests import build_pending_approval_result
from codex_chat_gateway.services.pending_requests import format_pending_request_message
from codex_chat_gateway.services.pending_requests import pending_accepts_approval_commands
from codex_chat_gateway.session_store import PendingBridgeRequest


class PendingRequestFormattingTests(unittest.TestCase):
    def test_formats_mcp_tool_approval_as_friendly_message(self) -> None:
        pending = PendingBridgeRequest(
            request_id="req_1",
            kind="input_request",
            text="User input is required to continue.",
            details={
                "questions": [
                    {
                        "id": "mcp_tool_call_approval_call_abc123",
                    }
                ]
            },
        )

        message = format_pending_request_message(pending)

        self.assertEqual(
            message,
            "o Codex quer usar uma ferramenta MCP para continuar\nuse /approve ou /reject",
        )
        self.assertNotIn("mcp_tool_call_approval_call_abc123", message)

    def test_formats_single_question_with_label(self) -> None:
        pending = PendingBridgeRequest(
            request_id="req_2",
            kind="input_request",
            text="User input is required to continue.",
            details={
                "questions": [
                    {
                        "id": "city",
                        "label": "Cidade",
                    }
                ]
            },
        )

        message = format_pending_request_message(pending)

        self.assertEqual(
            message,
            "o Codex precisa de uma resposta para continuar\npergunta: Cidade\nuse /answer <texto> ou /answer {\"campo\":\"valor\"}",
        )

    def test_mcp_tool_approval_accepts_approval_commands(self) -> None:
        pending = PendingBridgeRequest(
            request_id="req_3",
            kind="input_request",
            text="User input is required to continue.",
            details={
                "questions": [
                    {
                        "id": "mcp_tool_call_approval_call_abc123",
                    }
                ]
            },
        )

        self.assertTrue(pending_accepts_approval_commands(pending))
        self.assertEqual(
            build_pending_approval_result(pending, "approve"),
            {"answers": {"mcp_tool_call_approval_call_abc123": "approve"}},
        )
        self.assertEqual(
            build_pending_approval_result(pending, "reject"),
            {"answers": {"mcp_tool_call_approval_call_abc123": "reject"}},
        )

    def test_answer_approve_maps_to_single_mcp_approval_question(self) -> None:
        pending = PendingBridgeRequest(
            request_id="req_4",
            kind="input_request",
            text="User input is required to continue.",
            details={
                "questions": [
                    {
                        "id": "mcp_tool_call_approval_call_abc123",
                    }
                ]
            },
        )

        self.assertEqual(
            build_input_answers(pending, "approve"),
            {"mcp_tool_call_approval_call_abc123": "approve"},
        )
