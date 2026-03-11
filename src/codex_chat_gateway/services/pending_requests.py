from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from typing import Literal

from ..session_store import PendingBridgeRequest

PendingCommandAction = Literal["approve", "reject", "answer", "pending"]


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

    question_ids = _extract_question_ids(pending.details)
    if question_ids:
        joined = ", ".join(question_ids)
        return (
            "aguardando entrada do usuário para continuar\n"
            f"campos esperados: {joined}\n"
            'use /answer <texto> ou /answer {"campo":"valor"}'
        )
    return (
        "aguardando entrada do usuário para continuar\n"
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

    question_ids = _extract_question_ids(pending.details)
    if len(question_ids) == 1:
        return {question_ids[0]: stripped}
    return {"response": stripped}


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


def _extract_question_ids(details: dict[str, Any]) -> list[str]:
    questions = details.get("questions")
    if not isinstance(questions, list):
        return []
    result: list[str] = []
    for question in questions:
        if not isinstance(question, dict):
            continue
        question_id = question.get("id")
        if isinstance(question_id, str) and question_id:
            result.append(question_id)
    return result
