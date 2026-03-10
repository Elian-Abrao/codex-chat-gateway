# AGENTS.md

## Purpose

This repository is a chat-facing gateway that sits on top of `codex-runtime-bridge`.

The primary user problem is:

- "I already have a Codex runtime exposed through a bridge"
- "I want to talk to that runtime from WhatsApp and other chat apps"
- "I do not want channel-specific logic inside the runtime bridge repository"

The core rule for this codebase is:

- do not reimplement the Codex runtime here

This project should prefer:

- consuming `codex-runtime-bridge` through stable interfaces
- translating channel semantics into bridge calls
- keeping channel connectors isolated from runtime internals

This project should avoid:

- bypassing the bridge and talking directly to `codex app-server`
- cloning runtime, tool, or approval semantics locally
- turning one channel integration into the architecture for every product forever

## Product Boundaries

This repository should own:

- channel connectors such as WhatsApp
- channel webhook or socket lifecycle
- external identity mapping
- session mapping from contact/chat to `threadId`
- media normalization
- channel-friendly approval and follow-up UX
- delivery retries and gateway observability

This repository should not own:

- the Codex runtime itself
- local runtime process management
- runtime auth/session/tool internals
- direct `codex app-server` protocol ownership

Those belong in `codex-runtime-bridge`.

## Engineering Rules

- Keep the gateway as a consumer of the bridge, not a replacement for it.
- Prefer one internal message model shared across channels.
- Keep clear separation between:
  - channel adapters
  - session mapping
  - runtime bridge client
  - policy and access control
- If a runtime behavior is missing, extend the bridge contract instead of silently reimplementing it here.
- Document any bridge assumptions explicitly.
- Deployment guidance must assume private networking, strong auth, and controlled access.

## Current Layout

```text
src/codex_chat_gateway/
  __init__.py
  __main__.py
  cli.py
  version.py
docs/
  ARCHITECTURE.md
  ROADMAP.md
tests/
```

## Deployment Stance

This repository is intended to expose a privileged agent experience through external chat channels.

That means deployment guidance must assume:

- authenticated access
- explicit allowlists
- private-first networking
- careful handling of approvals and destructive actions

Avoid presenting direct unauthenticated public exposure as an acceptable default.

## Validation

When changing this project:

1. install the package in a local venv
2. run unit tests
3. validate the CLI entrypoint
4. validate the bridge contract assumptions against a real `codex-runtime-bridge` when integration code lands

Typical commands:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
python -m unittest discover -s tests -p 'test_*.py'
codex-chat-gateway version
```

## Notes

- this repo is the channel gateway
- `codex-runtime-bridge` is the runtime adapter
- if you find yourself implementing runtime semantics here, stop and reassess
- WhatsApp should be the first connector, not the only abstraction

