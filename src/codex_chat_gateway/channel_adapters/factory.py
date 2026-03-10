from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from importlib.resources import files

from .process import JsonlSubprocessChannelAdapter


def available_builtin_adapters() -> list[str]:
    return ["whatsapp-baileys"]


def create_builtin_adapter(
    name: str,
    *,
    allow_from: list[str] | None = None,
    auth_dir: str | Path | None = None,
    cwd: str | Path | None = None,
    include_from_me: bool = False,
) -> JsonlSubprocessChannelAdapter:
    if name != "whatsapp-baileys":
        raise ValueError(f"unknown built-in adapter: {name}")

    worker_path = files("codex_chat_gateway.connectors.whatsapp_baileys").joinpath("worker.mjs")
    env = dict(os.environ)
    env.setdefault("LOG_LEVEL", "warn")
    if allow_from:
        env["WHATSAPP_ALLOWLIST"] = ",".join(allow_from)
    if auth_dir is not None:
        env["WHATSAPP_AUTH_DIR"] = str(auth_dir)
    if include_from_me:
        env["WHATSAPP_INCLUDE_FROM_ME"] = "1"

    return JsonlSubprocessChannelAdapter(
        channel_name="whatsapp",
        command=["node", str(worker_path)],
        cwd=cwd,
        env=env,
    )
