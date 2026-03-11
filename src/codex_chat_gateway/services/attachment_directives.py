from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
import mimetypes
from pathlib import Path
import shlex

from ..models import Attachment


ATTACHMENT_DIRECTIVE_PREFIX = "[bridge-attachment"


@dataclass(slots=True)
class ParsedAttachments:
    text: str
    attachments: list[Attachment] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def _infer_kind(path: Path, mime_type: str | None) -> str:
    if mime_type:
        if mime_type.startswith("image/"):
            return "image"
        if mime_type.startswith("audio/"):
            return "audio"
    suffix = path.suffix.lower()
    if suffix in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}:
        return "image"
    if suffix in {".mp3", ".wav", ".ogg", ".m4a"}:
        return "audio"
    return "file"


def _parse_directive(line: str) -> dict[str, str]:
    stripped = line.strip()
    if not stripped.startswith(ATTACHMENT_DIRECTIVE_PREFIX) or not stripped.endswith("]"):
        raise ValueError("not an attachment directive")
    body = stripped[len(ATTACHMENT_DIRECTIVE_PREFIX) : -1].strip()
    if not body:
        raise ValueError("empty attachment directive")
    payload: dict[str, str] = {}
    for token in shlex.split(body):
        if "=" not in token:
            raise ValueError(f"invalid attachment directive token: {token}")
        key, value = token.split("=", 1)
        payload[key] = value
    return payload


def _build_attachment(raw_path: str, *, caption: str | None = None) -> Attachment:
    path = Path(raw_path).expanduser()
    if not path.is_absolute():
        raise ValueError(f"attachment path must be absolute: {raw_path}")
    resolved = path.resolve()
    if not resolved.exists():
        raise ValueError(f"attachment file not found: {resolved}")
    if not resolved.is_file():
        raise ValueError(f"attachment path is not a file: {resolved}")
    mime_type, _ = mimetypes.guess_type(str(resolved))
    return Attachment(
        kind=_infer_kind(resolved, mime_type),
        local_path=str(resolved),
        mime_type=mime_type,
        file_name=resolved.name,
        size_bytes=resolved.stat().st_size,
        caption=caption,
    )


def extract_attachment_directives(text: str) -> ParsedAttachments:
    kept_lines: list[str] = []
    attachments: list[Attachment] = []
    errors: list[str] = []

    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if not stripped.startswith(ATTACHMENT_DIRECTIVE_PREFIX):
            kept_lines.append(raw_line)
            continue
        try:
            directive = _parse_directive(raw_line)
            raw_path = directive.get("path")
            if raw_path is None:
                raise ValueError("attachment directive is missing path=...")
            attachments.append(_build_attachment(raw_path, caption=directive.get("caption")))
        except ValueError as exc:
            errors.append(str(exc))

    return ParsedAttachments(
        text="\n".join(line.rstrip() for line in kept_lines).strip(),
        attachments=attachments,
        errors=errors,
    )
