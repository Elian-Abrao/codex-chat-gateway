from __future__ import annotations

import asyncio
import unittest
from unittest.mock import patch

from codex_chat_gateway.channel_adapters.base import ChannelAdapter
from codex_chat_gateway.models import InboundMessage
from codex_chat_gateway.models import OutboundMessage
from codex_chat_gateway.runtime_client import BridgeClient
from codex_chat_gateway.services.console import ConsoleGateway
from codex_chat_gateway.session_store import PendingBridgeRequest


class FakeAdapter(ChannelAdapter):
    def __init__(self) -> None:
        self.sent_messages: list[OutboundMessage] = []

    @property
    def channel_name(self) -> str:
        return "whatsapp"

    async def start(self, handler) -> None:
        self._handler = handler

    async def wait(self) -> None:
        return None

    async def send_message(self, message: OutboundMessage) -> None:
        self.sent_messages.append(message)

    async def close(self) -> None:
        return None


class BlockingAdapter(FakeAdapter):
    def __init__(self) -> None:
        super().__init__()
        self.closed = False
        self._waiter = asyncio.Event()

    async def wait(self) -> None:
        await self._waiter.wait()

    async def close(self) -> None:
        self.closed = True
        self._waiter.set()


class FakeBridgeClient(BridgeClient):
    def __init__(self, base_url: str) -> None:
        super().__init__(base_url)
        self.respond_calls: list[dict[str, object]] = []
        self.stream_calls: list[dict[str, object]] = []

    async def chat(self, prompt: str, *, thread_id: str | None = None, **kwargs):
        raise AssertionError("console tests should use stream_consumer_chat")

    async def stream_consumer_chat(self, prompt: str, *, thread_id: str | None = None, **kwargs):
        self.stream_calls.append(
            {
                "prompt": prompt,
                "thread_id": thread_id,
                "summary": kwargs.get("summary"),
                "approvalPolicy": kwargs.get("approvalPolicy"),
                "sandbox": kwargs.get("sandbox"),
            }
        )
        if prompt == "needs approval":
            yield {"event": "status", "phase": "thread_started", "threadId": "thr_1", "message": "Thread started."}
            yield {"event": "status", "phase": "turn_started", "threadId": "thr_1", "turnId": "turn_1", "message": "Turn started."}
            yield {
                "event": "approval_request",
                "threadId": "thr_1",
                "turnId": "turn_1",
                "requestId": "req_1",
                "approvalType": "command_execution",
                "text": "Approval required for command execution.",
                "details": {"command": "rm -rf /tmp/demo"},
            }
            return
        if prompt == "needs input":
            yield {"event": "status", "phase": "thread_started", "threadId": "thr_1", "message": "Thread started."}
            yield {"event": "status", "phase": "turn_started", "threadId": "thr_1", "turnId": "turn_1", "message": "Turn started."}
            yield {
                "event": "input_request",
                "threadId": "thr_1",
                "turnId": "turn_1",
                "requestId": "req_2",
                "text": "User input is required to continue.",
                "details": {"questions": [{"id": "city", "label": "City"}]},
            }
            return
        yield {"event": "status", "phase": "thread_started", "threadId": "thr_1", "message": "Thread started."}
        yield {"event": "status", "phase": "turn_started", "threadId": "thr_1", "turnId": "turn_1", "message": "Turn started."}
        yield {
            "event": "commentary",
            "threadId": "thr_1",
            "turnId": "turn_1",
            "text": "Vou verificar agora.",
        }
        yield {
            "event": "action",
            "threadId": "thr_1",
            "turnId": "turn_1",
            "text": "Executing command: uptime",
            "actionType": "command_execution",
        }
        yield {
            "event": "final",
            "threadId": "thr_1",
            "turnId": "turn_1",
            "text": "ok",
        }

    async def respond_server_request(self, request_id: str | int, *, result: object = None, error: dict | None = None):
        self.respond_calls.append(
            {
                "request_id": request_id,
                "result": result,
                "error": error,
            }
        )
        return {"ok": True, "requestId": request_id}


class ConsoleGatewayTests(unittest.IsolatedAsyncioTestCase):
    async def _drain_gateway(self, gateway: ConsoleGateway) -> None:
        if gateway._turn_tasks:
            await asyncio.gather(*tuple(gateway._turn_tasks))

    async def test_terminal_text_sends_to_whatsapp_and_codex(self) -> None:
        adapter = FakeAdapter()
        terminal: list[str] = []
        gateway = ConsoleGateway(
            adapter=adapter,
            bridge_client=FakeBridgeClient("http://127.0.0.1:8787"),
            allowed_group_subjects=set(),
            allowed_group_chat_ids={"123@g.us"},
            output=terminal.append,
        )

        keep_going = await gateway.handle_console_line("ping")
        await self._drain_gateway(gateway)

        self.assertTrue(keep_going)
        self.assertEqual(
            [message.text for message in adapter.sent_messages],
            ["ping", "[Codex]\nok"],
        )
        self.assertIn("[whatsapp][out][terminal] ping", terminal)
        self.assertIn("[codex][status]\nProcessando...", terminal)
        self.assertIn("[codex][commentary]\n[Codex • andamento]\nVou verificar agora.", terminal)
        self.assertIn("[codex][action]\n[Codex • ações]\n> executando comando: uptime", terminal)
        self.assertIn("[codex][final]\n[Codex]\nok", terminal)

    async def test_inbound_group_message_is_mirrored_to_terminal(self) -> None:
        adapter = FakeAdapter()
        terminal: list[str] = []
        gateway = ConsoleGateway(
            adapter=adapter,
            bridge_client=FakeBridgeClient("http://127.0.0.1:8787"),
            allowed_group_subjects={"Codex"},
            allowed_group_chat_ids=set(),
            send_bridge_replies=False,
            output=terminal.append,
        )

        await gateway.handle_message(
            InboundMessage(
                message_id="msg_1",
                channel="whatsapp",
                chat_id="123@g.us",
                sender_id="55110000@s.whatsapp.net",
                text="oi",
                is_group=True,
                metadata={"groupSubject": "Codex", "pushName": "Elian"},
            )
        )
        await self._drain_gateway(gateway)

        self.assertEqual(adapter.sent_messages, [])
        self.assertIn("[whatsapp][in][Codex][Elian] oi", terminal)
        self.assertIn("[codex][status]\nProcessando...", terminal)
        self.assertIn("[codex][final]\n[Codex]\nok", terminal)

    async def test_console_passes_runtime_execution_profile(self) -> None:
        adapter = FakeAdapter()
        terminal: list[str] = []
        bridge = FakeBridgeClient("http://127.0.0.1:8787")
        gateway = ConsoleGateway(
            adapter=adapter,
            bridge_client=bridge,
            allowed_group_subjects=set(),
            allowed_group_chat_ids={"123@g.us"},
            send_bridge_replies=False,
            output=terminal.append,
            approval_policy="never",
            sandbox="danger-full-access",
        )

        keep_going = await gateway.handle_console_line("/codex ping")
        await self._drain_gateway(gateway)

        self.assertTrue(keep_going)
        self.assertEqual(adapter.sent_messages, [])
        self.assertIn("[codex][final]\n[Codex]\nok", terminal)
        self.assertEqual(
            bridge.stream_calls,
            [
                {
                    "prompt": "ping",
                    "thread_id": None,
                    "summary": "none",
                    "approvalPolicy": "never",
                    "sandbox": "danger-full-access",
                }
            ],
        )

    async def test_console_surfaces_pending_approval_requests(self) -> None:
        adapter = FakeAdapter()
        terminal: list[str] = []
        gateway = ConsoleGateway(
            adapter=adapter,
            bridge_client=FakeBridgeClient("http://127.0.0.1:8787"),
            allowed_group_subjects=set(),
            allowed_group_chat_ids={"123@g.us"},
            output=terminal.append,
        )

        keep_going = await gateway.handle_console_line("/codex needs approval")
        await self._drain_gateway(gateway)

        self.assertTrue(keep_going)
        self.assertEqual(
            [message.text for message in adapter.sent_messages],
            [
                "[Codex • ações]\n> aprovação necessária para comando: rm -rf /tmp/demo\n> use /approve ou /reject",
            ],
        )
        self.assertIn(
            "[codex][action]\n[Codex • ações]\n> aprovação necessária para comando: rm -rf /tmp/demo\n> use /approve ou /reject",
            terminal,
        )

    async def test_console_can_resolve_pending_approval_requests(self) -> None:
        adapter = FakeAdapter()
        terminal: list[str] = []
        bridge = FakeBridgeClient("http://127.0.0.1:8787")
        gateway = ConsoleGateway(
            adapter=adapter,
            bridge_client=bridge,
            allowed_group_subjects=set(),
            allowed_group_chat_ids={"123@g.us"},
            output=terminal.append,
        )
        gateway.session_store.set_pending_request(
            "whatsapp:123@g.us",
            PendingBridgeRequest(
                request_id="req_1",
                kind="approval_request",
                text="Approval required for command execution.",
                approval_type="command_execution",
                details={
                    "command": "rm -rf /tmp/demo",
                    "availableDecisions": [
                        "accept",
                        {"acceptWithExecpolicyAmendment": {"execpolicy_amendment": ["rm", "-rf"]}},
                        "cancel",
                    ],
                },
            ),
        )

        keep_going = await gateway.handle_console_line("/approve")

        self.assertTrue(keep_going)
        self.assertEqual(
            bridge.respond_calls,
            [{"request_id": "req_1", "result": {"decision": "accept"}, "error": None}],
        )
        self.assertIsNone(gateway.session_store.get("whatsapp:123@g.us").pending_request)
        self.assertEqual(
            [message.text for message in adapter.sent_messages],
            ["[Codex • ações]\n> aprovação enviada"],
        )
        self.assertIn("[codex][action]\n[Codex • ações]\n> aprovação enviada", terminal)

    async def test_console_can_resolve_pending_input_requests(self) -> None:
        adapter = FakeAdapter()
        terminal: list[str] = []
        bridge = FakeBridgeClient("http://127.0.0.1:8787")
        gateway = ConsoleGateway(
            adapter=adapter,
            bridge_client=bridge,
            allowed_group_subjects=set(),
            allowed_group_chat_ids={"123@g.us"},
            output=terminal.append,
        )
        gateway.session_store.set_pending_request(
            "whatsapp:123@g.us",
            PendingBridgeRequest(
                request_id="req_2",
                kind="input_request",
                text="User input is required to continue.",
                details={"questions": [{"id": "city", "label": "City"}]},
            ),
        )

        keep_going = await gateway.handle_console_line("/answer Campinas")

        self.assertTrue(keep_going)
        self.assertEqual(
            bridge.respond_calls,
            [{"request_id": "req_2", "result": {"answers": {"city": "Campinas"}}, "error": None}],
        )
        self.assertIsNone(gateway.session_store.get("whatsapp:123@g.us").pending_request)
        self.assertEqual(
            [message.text for message in adapter.sent_messages],
            ["[Codex • ações]\n> resposta enviada"],
        )
        self.assertIn("[codex][action]\n[Codex • ações]\n> resposta enviada", terminal)

    async def test_console_can_resolve_mcp_input_approvals_with_approve(self) -> None:
        adapter = FakeAdapter()
        terminal: list[str] = []
        bridge = FakeBridgeClient("http://127.0.0.1:8787")
        gateway = ConsoleGateway(
            adapter=adapter,
            bridge_client=bridge,
            allowed_group_subjects=set(),
            allowed_group_chat_ids={"123@g.us"},
            output=terminal.append,
        )
        gateway.session_store.set_pending_request(
            "whatsapp:123@g.us",
            PendingBridgeRequest(
                request_id="req_3",
                kind="input_request",
                text="User input is required to continue.",
                details={
                    "questions": [
                        {
                            "id": "mcp_tool_call_approval_call_abc123",
                            "options": [
                                {"label": "Approve Once"},
                                {"label": "Approve this Session"},
                                {"label": "Deny"},
                                {"label": "Cancel"},
                            ],
                        }
                    ]
                },
            ),
        )

        keep_going = await gateway.handle_console_line("/approve")

        self.assertTrue(keep_going)
        self.assertEqual(
            bridge.respond_calls,
            [
                {
                    "request_id": "req_3",
                    "result": {"answers": {"mcp_tool_call_approval_call_abc123": "Approve Once"}},
                    "error": None,
                }
            ],
        )
        self.assertIsNone(gateway.session_store.get("whatsapp:123@g.us").pending_request)
        self.assertEqual(
            [message.text for message in adapter.sent_messages],
            ["[Codex • ações]\n> aprovação enviada"],
        )
        self.assertIn("[codex][action]\n[Codex • ações]\n> aprovação enviada", terminal)

    async def test_console_blocks_new_prompts_while_pending_request_exists(self) -> None:
        adapter = FakeAdapter()
        terminal: list[str] = []
        bridge = FakeBridgeClient("http://127.0.0.1:8787")
        gateway = ConsoleGateway(
            adapter=adapter,
            bridge_client=bridge,
            allowed_group_subjects=set(),
            allowed_group_chat_ids={"123@g.us"},
            output=terminal.append,
        )
        gateway.session_store.set_pending_request(
            "whatsapp:123@g.us",
            PendingBridgeRequest(
                request_id="req_1",
                kind="approval_request",
                text="Approval required for command execution.",
                approval_type="command_execution",
                details={"command": "rm -rf /tmp/demo"},
            ),
        )

        keep_going = await gateway.handle_console_line("/codex outra tarefa")

        self.assertTrue(keep_going)
        self.assertEqual(bridge.respond_calls, [])
        self.assertEqual(
            [message.text for message in adapter.sent_messages],
            [
                "[Codex • ações]\n> aprovação necessária para comando: rm -rf /tmp/demo\n> use /approve ou /reject",
            ],
        )
        self.assertIn(
            "[codex][action]\n[Codex • ações]\n> aprovação necessária para comando: rm -rf /tmp/demo\n> use /approve ou /reject",
            terminal,
        )

    async def test_console_run_exits_cleanly_on_quit(self) -> None:
        adapter = BlockingAdapter()
        terminal: list[str] = []
        gateway = ConsoleGateway(
            adapter=adapter,
            bridge_client=None,
            allowed_group_subjects=set(),
            allowed_group_chat_ids={"123@g.us"},
            output=terminal.append,
        )

        with patch("sys.stdin.readline", side_effect=["/quit\n"]):
            await gateway.run()

        self.assertTrue(adapter.closed)
        self.assertIn("Console commands:", terminal[0])
