from __future__ import annotations

from ..models import InboundMessage


def session_key_for_message(message: InboundMessage) -> str:
    return f"{message.channel}:{message.chat_id}"


def matches_target_group(
    message: InboundMessage,
    *,
    allowed_group_subjects: set[str],
    allowed_group_chat_ids: set[str],
) -> bool:
    if not message.is_group:
        return False
    if allowed_group_chat_ids and message.chat_id in allowed_group_chat_ids:
        return True
    group_subject = (message.metadata.get("groupSubject") or "").strip()
    if allowed_group_subjects and group_subject in allowed_group_subjects:
        return True
    return not allowed_group_chat_ids and not allowed_group_subjects
