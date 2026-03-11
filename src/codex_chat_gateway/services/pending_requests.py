from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from typing import Literal

from ..session_store import PendingBridgeRequest

PendingCommandAction = Literal["approve", "reject", "answer", "pending"]
APPROVE_ALIASES = ("approve", "approved", "allow", "accept", "yes", "true", "continue")
REJECT_ALIASES = ("reject", "rejected", "deny", "decline", "no", "false", "cancel")
MCP_TOOL_APPROVAL_PREFIX = "mcp_tool_call_approval_"


@dataclass(slots=True)
class PendingCommand:
    action: PendingCommandAction
    argument: str | None = None


def parse_pending_command(text: str) -> PendingCommand | None:
    stripped = text.strip()
    if not stripped.startswith("/"):
        return None
    command, _, argument = stripped.partition(" ")
    normalized = command.lower()
    if normalized == "/approve":
        return PendingCommand("approve")
    if normalized in {"/reject", "/deny"}:
        return PendingCommand("reject")
    if normalized == "/pending":
        return PendingCommand("pending")
    if normalized == "/answer":
        return PendingCommand("answer", argument=argument.strip() or None)
    return None


def format_pending_request_message(pending: PendingBridgeRequest) -> str:
    if pending.kind == "approval_request":
        if pending.approval_type == "command_execution":
            command = pending.details.get("command") or "<comando desconhecido>"
            return (
                f"aprovação necessária para comando: {command}\n"
                "use /approve ou /reject"
            )
        if pending.approval_type == "file_change":
            return "aprovação necessária para alterações de arquivos\nuse /approve ou /reject"
        return "aprovação necessária para continuar\nuse /approve ou /reject"

    question = _extract_single_question(pending.details)
    if _is_mcp_tool_approval_question(question):
        tool_label = _question_display_label(question)
        if tool_label:
            return (
                f"o Codex quer usar a ferramenta MCP \"{tool_label}\" para continuar\n"
                "use /approve ou /reject"
            )
        return "o Codex quer usar uma ferramenta MCP para continuar\nuse /approve ou /reject"

    question_labels = _extract_question_labels(pending.details)
    if len(question_labels) == 1:
        return (
            "o Codex precisa de uma resposta para continuar\n"
            f"pergunta: {question_labels[0]}\n"
            'use /answer <texto> ou /answer {"campo":"valor"}'
        )

    question_ids = _extract_question_ids(pending.details)
    if question_ids:
        joined = ", ".join(question_ids)
        return (
            "o Codex precisa de algumas respostas para continuar\n"
            f"campos: {joined}\n"
            'use /answer <texto> ou /answer {"campo":"valor"}'
        )
    return (
        "o Codex precisa de uma resposta para continuar\n"
        'use /answer <texto> ou /answer {"campo":"valor"}'
    )


def build_input_answers(pending: PendingBridgeRequest, raw_argument: str) -> dict[str, Any]:
    stripped = raw_argument.strip()
    if not stripped:
        raise ValueError("use /answer <texto> ou /answer {\"campo\":\"valor\"}")

    if stripped.startswith("{"):
        payload = json.loads(stripped)
        if not isinstance(payload, dict):
            raise ValueError("o JSON enviado em /answer precisa ser um objeto")
        return payload

    question = _extract_single_question(pending.details)
    if question is not None:
        question_id = question.get("id")
        if isinstance(question_id, str) and question_id:
            if _is_mcp_tool_approval_question(question):
                return {question_id: _normalize_question_decision(question, stripped)}
            return {question_id: stripped}

    question_ids = _extract_question_ids(pending.details)
    if len(question_ids) == 1:
        return {question_ids[0]: stripped}
    return {"response": stripped}


def pending_accepts_approval_commands(pending: PendingBridgeRequest) -> bool:
    if pending.kind == "approval_request":
        return True
    return _is_mcp_tool_approval_question(_extract_single_question(pending.details))


def build_pending_approval_result(
    pending: PendingBridgeRequest,
    action: Literal["approve", "reject"],
) -> dict[str, Any]:
    if pending.kind == "approval_request":
        return {"decision": "approve" if action == "approve" else "decline"}

    question = _extract_single_question(pending.details)
    if not _is_mcp_tool_approval_question(question):
        raise ValueError("a solicitação pendente não aceita /approve ou /reject")

    question_id = question.get("id")
    if not isinstance(question_id, str) or not question_id:
        raise ValueError("a solicitação pendente não define um campo de resposta válido")
    return {
        "answers": {
            question_id: _normalize_question_decision(question, action),
        }
    }


def format_pending_resolution_message(action: PendingCommandAction) -> str:
    if action == "approve":
        return "aprovação enviada"
    if action == "reject":
        return "rejeição enviada"
    if action == "answer":
        return "resposta enviada"
    return "nenhuma solicitação pendente"


def format_busy_message(has_pending_request: bool) -> str:
    if has_pending_request:
        return "existe uma solicitação pendente; use /pending para ver e responder"
    return "já existe um turno em andamento; aguarde a resposta atual terminar"


def _extract_questions(details: dict[str, Any]) -> list[dict[str, Any]]:
    questions = details.get("questions")
    if not isinstance(questions, list):
        return []
    return [question for question in questions if isinstance(question, dict)]


def _extract_question_ids(details: dict[str, Any]) -> list[str]:
    result: list[str] = []
    for question in _extract_questions(details):
        question_id = question.get("id")
        if isinstance(question_id, str) and question_id:
            result.append(question_id)
    return result


def _extract_question_labels(details: dict[str, Any]) -> list[str]:
    result: list[str] = []
    for question in _extract_questions(details):
        label = _question_display_label(question)
        if label:
            result.append(label)
    return result


def _extract_single_question(details: dict[str, Any]) -> dict[str, Any] | None:
    questions = _extract_questions(details)
    if len(questions) != 1:
        return None
    return questions[0]


def _question_display_label(question: dict[str, Any] | None) -> str | None:
    if not isinstance(question, dict):
        return None
    for key in ("label", "title", "prompt", "name"):
        value = question.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _is_mcp_tool_approval_question(question: dict[str, Any] | None) -> bool:
    if not isinstance(question, dict):
        return False
    question_id = question.get("id")
    if isinstance(question_id, str) and question_id.startswith(MCP_TOOL_APPROVAL_PREFIX):
        return True
    normalized_options = {_normalize_option_value(option) for option in _extract_question_options(question)}
    return "approve" in normalized_options and ("reject" in normalized_options or "decline" in normalized_options)


def _extract_question_options(question: dict[str, Any]) -> list[str]:
    for key in ("options", "choices", "enum"):
        raw_options = question.get(key)
        if not isinstance(raw_options, list):
            continue
        result: list[str] = []
        for option in raw_options:
            if isinstance(option, str):
                result.append(option)
                continue
            if not isinstance(option, dict):
                continue
            for candidate_key in ("value", "id", "key", "name", "label", "title"):
                candidate = option.get(candidate_key)
                if isinstance(candidate, str) and candidate:
                    result.append(candidate)
                    break
        if result:
            return result
    return []


def _normalize_question_decision(question: dict[str, Any] | None, decision: str) -> str:
    normalized = decision.strip().lower()
    options = _extract_question_options(question or {})
    normalized_options = {option: _normalize_option_value(option) for option in options}
    if normalized in APPROVE_ALIASES:
        for option, option_normalized in normalized_options.items():
            if option_normalized in {"approve", "approved", "allow", "accept", "yes", "true", "continue"}:
                return option
        return "approve"
    if normalized in REJECT_ALIASES:
        for option, option_normalized in normalized_options.items():
            if option_normalized in {"reject", "rejected", "decline", "deny", "no", "false", "cancel"}:
                return option
        return "reject"
    return decision


def _normalize_option_value(option: str) -> str:
    return option.strip().lower().replace(" ", "_")
