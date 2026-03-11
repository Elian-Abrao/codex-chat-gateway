from __future__ import annotations

import asyncio
import unittest

from codex_chat_gateway.channel_adapters.base import ChannelAdapter
from codex_chat_gateway.models import InboundMessage
from codex_chat_gateway.models import OutboundMessage
from codex_chat_gateway.runtime_client import BridgeClient
from codex_chat_gateway.services import BridgeChatGateway
from codex_chat_gateway.session_store import InMemorySessionStore
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


class FakeBridgeClient(BridgeClient):
    def __init__(self) -> None:
        self.calls: list[dict[str, str | None]] = []
        self.stream_calls: list[dict[str, str | None]] = []
        self.respond_calls: list[dict[str, object]] = []
        self.resume_calls: list[str] = []

    async def chat(self, prompt: str, *, thread_id: str | None = None, **kwargs) -> dict[str, str]:
        self.calls.append({"prompt": prompt, "thread_id": thread_id})
        return {
            "threadId": "thr_1",
            "assistantText": "ok",
        }

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
        if prompt == "send attachment":
            yield {"event": "status", "phase": "thread_started", "threadId": "thr_1", "message": "Thread started."}
            yield {"event": "status", "phase": "turn_started", "threadId": "thr_1", "turnId": "turn_1", "message": "Turn started."}
            yield {
                "event": "final",
                "threadId": "thr_1",
                "turnId": "turn_1",
                "text": "Segue o print.",
                "attachments": [
                    {
                        "kind": "image",
                        "localPath": "/tmp/demo.png",
                        "fileName": "demo.png",
                        "mimeType": "image/png",
                    }
                ],
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
            "event": "reasoning_summary",
            "threadId": "thr_1",
            "turnId": "turn_1",
            "text": "Analisando o pedido.",
        }
        yield {
            "event": "action",
            "threadId": "thr_1",
            "turnId": "turn_1",
            "text": "Executing command: pwd",
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

    async def resume_thread(self, thread_id: str) -> dict[str, object]:
        self.resume_calls.append(thread_id)
        return {
            "thread": {
                "id": thread_id,
                "status": {"type": "idle"},
                "turns": [
                    {
                        "id": "turn_1",
                        "status": "completed",
                        "items": [
                            {
                                "type": "agentMessage",
                                "id": "item_1",
                                "text": "ok",
                                "phase": "final_answer",
                            }
                        ],
                    }
                ],
            }
        }


class BridgeChatGatewayTests(unittest.IsolatedAsyncioTestCase):
    async def _drain_gateway(self, gateway: BridgeChatGateway) -> None:
        if gateway._turn_tasks:
            await asyncio.gather(*tuple(gateway._turn_tasks))

    async def test_gateway_ignores_messages_outside_target_group(self) -> None:
        adapter = FakeAdapter()
        bridge = FakeBridgeClient()
        gateway = BridgeChatGateway(
            adapter=adapter,
            bridge_client=bridge,
            session_store=InMemorySessionStore(),
            allowed_group_subjects={"Codex"},
            allowed_group_chat_ids=set(),
            send_replies=False,
        )

        await gateway.handle_message(
            InboundMessage(
                message_id="msg_1",
                channel="whatsapp",
                chat_id="123@g.us",
                sender_id="other@s.whatsapp.net",
                text="hello",
                is_group=True,
                metadata={"fromMe": False, "groupSubject": "Other"},
            )
        )
        await self._drain_gateway(gateway)

        self.assertEqual(bridge.stream_calls, [])

    async def test_gateway_forwards_messages_in_matching_group(self) -> None:
        adapter = FakeAdapter()
        bridge = FakeBridgeClient()
        store = InMemorySessionStore()
        gateway = BridgeChatGateway(
            adapter=adapter,
            bridge_client=bridge,
            session_store=store,
            allowed_group_subjects={"Codex"},
            allowed_group_chat_ids=set(),
        )

        await gateway.handle_message(
            InboundMessage(
                message_id="msg_1",
                channel="whatsapp",
                chat_id="123@g.us",
                sender_id="other@s.whatsapp.net",
                text="Oi",
                is_group=True,
                metadata={"fromMe": False, "groupSubject": "Codex"},
            )
        )
        await self._drain_gateway(gateway)

        self.assertEqual(
            bridge.stream_calls,
            [{"prompt": "Oi", "thread_id": None, "summary": "none", "approvalPolicy": None, "sandbox": None}],
        )
        self.assertEqual(store.get("whatsapp:123@g.us").thread_id, "thr_1")
        self.assertEqual([message.text for message in adapter.sent_messages], ["[Codex]\nok"])

    async def test_gateway_can_emit_progress_updates_when_enabled(self) -> None:
        adapter = FakeAdapter()
        bridge = FakeBridgeClient()
        gateway = BridgeChatGateway(
            adapter=adapter,
            bridge_client=bridge,
            session_store=InMemorySessionStore(),
            allowed_group_subjects={"Codex"},
            allowed_group_chat_ids=set(),
            show_commentary=True,
            show_reasoning=True,
            show_actions=True,
        )

        await gateway.handle_message(
            InboundMessage(
                message_id="msg_1",
                channel="whatsapp",
                chat_id="123@g.us",
                sender_id="other@s.whatsapp.net",
                text="Oi",
                is_group=True,
                metadata={"fromMe": False, "groupSubject": "Codex"},
            )
        )
        await self._drain_gateway(gateway)

        self.assertEqual(
            bridge.stream_calls,
            [
                {
                    "prompt": "Oi",
                    "thread_id": None,
                    "summary": "detailed",
                    "approvalPolicy": None,
                    "sandbox": None,
                }
            ],
        )
        self.assertEqual(len(adapter.sent_messages), 4)
        self.assertEqual(
            [message.text for message in adapter.sent_messages],
            [
                "[Codex • andamento]\nVou verificar agora.",
                "[Codex • raciocínio]\nAnalisando o pedido.",
                "[Codex • ações]\n> executando comando: pwd",
                "[Codex]\nok",
            ],
        )

    async def test_gateway_sends_final_attachments_back_to_whatsapp(self) -> None:
        adapter = FakeAdapter()
        bridge = FakeBridgeClient()
        gateway = BridgeChatGateway(
            adapter=adapter,
            bridge_client=bridge,
            session_store=InMemorySessionStore(),
            allowed_group_subjects={"Codex"},
            allowed_group_chat_ids=set(),
        )

        await gateway.handle_message(
            InboundMessage(
                message_id="msg_1",
                channel="whatsapp",
                chat_id="123@g.us",
                sender_id="other@s.whatsapp.net",
                text="send attachment",
                is_group=True,
                metadata={"fromMe": False, "groupSubject": "Codex"},
            )
        )
        await self._drain_gateway(gateway)

        self.assertEqual(len(adapter.sent_messages), 1)
        outbound = adapter.sent_messages[0]
        self.assertEqual(outbound.text, "[Codex]\nSegue o print.")
        self.assertEqual(len(outbound.attachments), 1)
        self.assertEqual(outbound.attachments[0].local_path, "/tmp/demo.png")
        self.assertEqual(outbound.attachments[0].mime_type, "image/png")

    async def test_gateway_can_run_in_log_only_mode(self) -> None:
        adapter = FakeAdapter()
        bridge = FakeBridgeClient()
        gateway = BridgeChatGateway(
            adapter=adapter,
            bridge_client=bridge,
            session_store=InMemorySessionStore(),
            allowed_group_subjects={"Codex"},
            allowed_group_chat_ids=set(),
            send_replies=False,
        )

        await gateway.handle_message(
            InboundMessage(
                message_id="msg_1",
                channel="whatsapp",
                chat_id="123@g.us",
                sender_id="other@s.whatsapp.net",
                text="Oi",
                is_group=True,
                metadata={"fromMe": False, "groupSubject": "Codex"},
            )
        )
        await self._drain_gateway(gateway)

        self.assertEqual(adapter.sent_messages, [])

    async def test_gateway_passes_runtime_execution_profile(self) -> None:
        adapter = FakeAdapter()
        bridge = FakeBridgeClient()
        gateway = BridgeChatGateway(
            adapter=adapter,
            bridge_client=bridge,
            session_store=InMemorySessionStore(),
            allowed_group_subjects={"Codex"},
            allowed_group_chat_ids=set(),
            send_replies=False,
            approval_policy="never",
            sandbox="danger-full-access",
        )

        await gateway.handle_message(
            InboundMessage(
                message_id="msg_profile",
                channel="whatsapp",
                chat_id="123@g.us",
                sender_id="other@s.whatsapp.net",
                text="Oi",
                is_group=True,
                metadata={"fromMe": False, "groupSubject": "Codex"},
            )
        )
        await self._drain_gateway(gateway)

        self.assertEqual(
            bridge.stream_calls,
            [
                {
                    "prompt": "Oi",
                    "thread_id": None,
                    "summary": "none",
                    "approvalPolicy": "never",
                    "sandbox": "danger-full-access",
                }
            ],
        )

    async def test_gateway_surfaces_pending_approval_requests(self) -> None:
        adapter = FakeAdapter()
        bridge = FakeBridgeClient()
        store = InMemorySessionStore()
        gateway = BridgeChatGateway(
            adapter=adapter,
            bridge_client=bridge,
            session_store=store,
            allowed_group_subjects={"Codex"},
            allowed_group_chat_ids=set(),
        )

        await gateway.handle_message(
            InboundMessage(
                message_id="msg_approval",
                channel="whatsapp",
                chat_id="123@g.us",
                sender_id="other@s.whatsapp.net",
                text="needs approval",
                is_group=True,
                metadata={"fromMe": False, "groupSubject": "Codex"},
            )
        )
        await self._drain_gateway(gateway)

        session = store.get("whatsapp:123@g.us")
        self.assertIsNotNone(session.pending_request)
        self.assertEqual(session.pending_request.request_id, "req_1")
        self.assertEqual(
            [message.text for message in adapter.sent_messages],
            [
                "[Codex • ações]\n> aprovação necessária para comando: rm -rf /tmp/demo\n> use /approve ou /reject",
            ],
        )

    async def test_gateway_can_resolve_pending_approval_requests(self) -> None:
        adapter = FakeAdapter()
        bridge = FakeBridgeClient()
        store = InMemorySessionStore()
        store.set_pending_request(
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
        gateway = BridgeChatGateway(
            adapter=adapter,
            bridge_client=bridge,
            session_store=store,
            allowed_group_subjects={"Codex"},
            allowed_group_chat_ids=set(),
        )

        await gateway.handle_message(
            InboundMessage(
                message_id="msg_approve",
                channel="whatsapp",
                chat_id="123@g.us",
                sender_id="other@s.whatsapp.net",
                text="/approve",
                is_group=True,
                metadata={"fromMe": False, "groupSubject": "Codex"},
            )
        )

        self.assertEqual(
            bridge.respond_calls,
            [{"request_id": "req_1", "result": {"decision": "accept"}, "error": None}],
        )
        self.assertIsNone(store.get("whatsapp:123@g.us").pending_request)
        self.assertEqual(
            [message.text for message in adapter.sent_messages],
            ["[Codex • ações]\n> aprovação enviada"],
        )

    async def test_gateway_recovers_final_reply_after_restart_resolves_pending_approval(self) -> None:
        adapter = FakeAdapter()
        bridge = FakeBridgeClient()
        store = InMemorySessionStore()
        store.set_pending_request(
            "whatsapp:123@g.us",
            PendingBridgeRequest(
                request_id="req_1",
                kind="approval_request",
                text="Approval required for command execution.",
                thread_id="thr_1",
                turn_id="turn_1",
                approval_type="command_execution",
                details={"command": "rm -rf /tmp/demo"},
            ),
        )
        gateway = BridgeChatGateway(
            adapter=adapter,
            bridge_client=bridge,
            session_store=store,
            allowed_group_subjects={"Codex"},
            allowed_group_chat_ids=set(),
        )

        await gateway.handle_message(
            InboundMessage(
                message_id="msg_approve_recover",
                channel="whatsapp",
                chat_id="123@g.us",
                sender_id="other@s.whatsapp.net",
                text="/approve",
                is_group=True,
                metadata={"fromMe": False, "groupSubject": "Codex"},
            )
        )

        self.assertEqual(
            bridge.respond_calls,
            [{"request_id": "req_1", "result": {"decision": "approve"}, "error": None}],
        )
        self.assertEqual(bridge.resume_calls, ["thr_1"])
        self.assertEqual(
            [message.text for message in adapter.sent_messages],
            [
                "[Codex • ações]\n> aprovação enviada",
                "[Codex]\nok",
            ],
        )
        self.assertIsNone(store.get("whatsapp:123@g.us").pending_request)

    async def test_gateway_can_resolve_pending_input_requests(self) -> None:
        adapter = FakeAdapter()
        bridge = FakeBridgeClient()
        store = InMemorySessionStore()
        store.set_pending_request(
            "whatsapp:123@g.us",
            PendingBridgeRequest(
                request_id="req_2",
                kind="input_request",
                text="User input is required to continue.",
                details={"questions": [{"id": "city", "label": "City"}]},
            ),
        )
        gateway = BridgeChatGateway(
            adapter=adapter,
            bridge_client=bridge,
            session_store=store,
            allowed_group_subjects={"Codex"},
            allowed_group_chat_ids=set(),
        )

        await gateway.handle_message(
            InboundMessage(
                message_id="msg_answer",
                channel="whatsapp",
                chat_id="123@g.us",
                sender_id="other@s.whatsapp.net",
                text="/answer Sao Paulo",
                is_group=True,
                metadata={"fromMe": False, "groupSubject": "Codex"},
            )
        )

        self.assertEqual(
            bridge.respond_calls,
            [{"request_id": "req_2", "result": {"answers": {"city": "Sao Paulo"}}, "error": None}],
        )
        self.assertIsNone(store.get("whatsapp:123@g.us").pending_request)
        self.assertEqual(
            [message.text for message in adapter.sent_messages],
            ["[Codex • ações]\n> resposta enviada"],
        )

    async def test_gateway_can_resolve_mcp_input_approvals_with_approve(self) -> None:
        adapter = FakeAdapter()
        bridge = FakeBridgeClient()
        store = InMemorySessionStore()
        store.set_pending_request(
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
        gateway = BridgeChatGateway(
            adapter=adapter,
            bridge_client=bridge,
            session_store=store,
            allowed_group_subjects={"Codex"},
            allowed_group_chat_ids=set(),
        )

        await gateway.handle_message(
            InboundMessage(
                message_id="msg_approve_mcp",
                channel="whatsapp",
                chat_id="123@g.us",
                sender_id="other@s.whatsapp.net",
                text="/approve",
                is_group=True,
                metadata={"fromMe": False, "groupSubject": "Codex"},
            )
        )

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
        self.assertIsNone(store.get("whatsapp:123@g.us").pending_request)
        self.assertEqual(
            [message.text for message in adapter.sent_messages],
            ["[Codex • ações]\n> aprovação enviada"],
        )

    async def test_gateway_blocks_new_prompts_while_pending_request_exists(self) -> None:
        adapter = FakeAdapter()
        bridge = FakeBridgeClient()
        store = InMemorySessionStore()
        store.set_pending_request(
            "whatsapp:123@g.us",
            PendingBridgeRequest(
                request_id="req_1",
                kind="approval_request",
                text="Approval required for command execution.",
                approval_type="command_execution",
                details={"command": "rm -rf /tmp/demo"},
            ),
        )
        gateway = BridgeChatGateway(
            adapter=adapter,
            bridge_client=bridge,
            session_store=store,
            allowed_group_subjects={"Codex"},
            allowed_group_chat_ids=set(),
        )

        await gateway.handle_message(
            InboundMessage(
                message_id="msg_other",
                channel="whatsapp",
                chat_id="123@g.us",
                sender_id="other@s.whatsapp.net",
                text="outra pergunta",
                is_group=True,
                metadata={"fromMe": False, "groupSubject": "Codex"},
            )
        )

        self.assertEqual(bridge.stream_calls, [])
        self.assertEqual(
            [message.text for message in adapter.sent_messages],
            [
                "[Codex • ações]\n> aprovação necessária para comando: rm -rf /tmp/demo\n> use /approve ou /reject",
            ],
        )
