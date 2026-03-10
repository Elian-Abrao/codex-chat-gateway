from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path

from .channel_adapters import available_builtin_adapters
from .channel_adapters import create_builtin_adapter
from .runtime_client import BridgeClient
from .services import BridgeChatGateway
from .services import ConsoleGateway
from .services import EchoGateway
from .session_store import InMemorySessionStore
from .version import __version__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="codex-chat-gateway")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("version")
    subparsers.add_parser("about")
    echo_parser = subparsers.add_parser("echo")
    echo_parser.add_argument(
        "--channel",
        choices=available_builtin_adapters(),
        default="whatsapp-baileys",
    )
    echo_parser.add_argument("--auth-dir", default=".state/whatsapp")
    echo_parser.add_argument("--allow-from", action="append", default=[])
    echo_parser.add_argument("--reply-prefix", default="echo: ")
    echo_parser.add_argument("--cwd", default=".")

    console_parser = subparsers.add_parser("console")
    console_parser.add_argument(
        "--channel",
        choices=available_builtin_adapters(),
        default="whatsapp-baileys",
    )
    console_parser.add_argument("--bridge-url")
    console_parser.add_argument("--auth-dir", default=".state/whatsapp")
    console_parser.add_argument("--allow-from", action="append", default=[])
    console_parser.add_argument("--group-subject", action="append", default=[])
    console_parser.add_argument("--group-chat-id", action="append", default=[])
    console_parser.add_argument(
        "--show-reasoning",
        action="store_true",
        help="Send reasoning summary progress messages back to WhatsApp and print them in the terminal.",
    )
    console_parser.add_argument(
        "--show-actions",
        action="store_true",
        help="Send tool and command activity messages back to WhatsApp and print them in the terminal.",
    )
    console_parser.add_argument(
        "--log-only",
        action="store_true",
        help="Do not send Codex responses back to WhatsApp; only print them in the terminal.",
    )
    console_parser.add_argument("--cwd", default=".")

    bridge_parser = subparsers.add_parser("bridge-chat")
    bridge_parser.add_argument(
        "--channel",
        choices=available_builtin_adapters(),
        default="whatsapp-baileys",
    )
    bridge_parser.add_argument("--bridge-url", default="http://127.0.0.1:8787")
    bridge_parser.add_argument("--auth-dir", default=".state/whatsapp")
    bridge_parser.add_argument("--allow-from", action="append", default=[])
    bridge_parser.add_argument("--group-subject", action="append", default=[])
    bridge_parser.add_argument("--group-chat-id", action="append", default=[])
    bridge_parser.add_argument(
        "--show-reasoning",
        action="store_true",
        help="Send reasoning summary progress messages back to WhatsApp.",
    )
    bridge_parser.add_argument(
        "--show-actions",
        action="store_true",
        help="Send tool and command activity messages back to WhatsApp.",
    )
    bridge_parser.add_argument(
        "--log-only",
        action="store_true",
        help="Do not send the assistant response back to WhatsApp; only log it locally.",
    )
    bridge_parser.add_argument("--cwd", default=".")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.command == "version":
        print(__version__)
        return
    if args.command == "about":
        print("codex-chat-gateway consumes codex-runtime-bridge to expose Codex through chat platforms.")
        return
    if args.command == "echo":
        logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
        adapter = create_builtin_adapter(
            args.channel,
            allow_from=args.allow_from,
            auth_dir=Path(args.auth_dir),
            cwd=Path(args.cwd),
        )
        asyncio.run(EchoGateway(adapter=adapter, reply_prefix=args.reply_prefix).run())
        return
    if args.command == "console":
        logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
        if not args.group_subject and not args.group_chat_id:
            raise SystemExit("console requires --group-subject or --group-chat-id")
        adapter = create_builtin_adapter(
            args.channel,
            allow_from=args.allow_from,
            auth_dir=Path(args.auth_dir),
            cwd=Path(args.cwd),
            include_from_me=True,
        )
        asyncio.run(
            ConsoleGateway(
                adapter=adapter,
                bridge_client=BridgeClient(args.bridge_url) if args.bridge_url else None,
                allowed_group_subjects=set(args.group_subject),
                allowed_group_chat_ids=set(args.group_chat_id),
                show_reasoning=args.show_reasoning,
                show_actions=args.show_actions,
                send_bridge_replies=not args.log_only,
            ).run()
        )
        return
    if args.command == "bridge-chat":
        logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
        if not args.group_subject and not args.group_chat_id:
            raise SystemExit("bridge-chat requires --group-subject or --group-chat-id")
        adapter = create_builtin_adapter(
            args.channel,
            allow_from=args.allow_from,
            auth_dir=Path(args.auth_dir),
            cwd=Path(args.cwd),
            include_from_me=True,
        )
        gateway = BridgeChatGateway(
            adapter=adapter,
            bridge_client=BridgeClient(args.bridge_url),
            session_store=InMemorySessionStore(),
            allowed_group_subjects=set(args.group_subject),
            allowed_group_chat_ids=set(args.group_chat_id),
            send_replies=not args.log_only,
            show_reasoning=args.show_reasoning,
            show_actions=args.show_actions,
        )
        asyncio.run(gateway.run())
        return
    raise SystemExit(f"unknown command: {args.command}")
