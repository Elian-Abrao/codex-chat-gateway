from __future__ import annotations

import argparse

from .version import __version__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="codex-chat-gateway")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("version")
    subparsers.add_parser("about")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.command == "version":
        print(__version__)
        return
    if args.command == "about":
        print("codex-chat-gateway consumes codex-runtime-bridge to expose Codex through chat platforms.")
        return
    raise SystemExit(f"unknown command: {args.command}")

