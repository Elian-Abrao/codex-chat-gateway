# codex-chat-gateway

`codex-chat-gateway` is a separate consumer repository that connects chat platforms such as WhatsApp to a running `codex-runtime-bridge`.

This repository exists to keep two concerns separate:

- `codex-runtime-bridge` exposes the real Codex runtime
- `codex-chat-gateway` adapts external chat channels to that bridge

The goal is not to reimplement Codex here.

The goal is to translate:

- inbound messages from chat platforms
- outbound runtime responses
- approvals and follow-up prompts
- channel-specific media and identity models

into a stable gateway layer on top of the runtime bridge.

## Why This Is Separate

This repository should own:

- WhatsApp and future channel integrations
- webhook and connector processes
- contact or conversation to `threadId` mapping
- message normalization
- delivery and retry policy
- channel-facing approval UX
- media adaptation
- gateway observability

This repository should not own:

- `codex app-server`
- runtime process management
- Codex auth and session internals
- tool execution semantics
- model/runtime approvals logic itself

Those remain in `codex-runtime-bridge`.

## Relationship To The Bridge

```text
WhatsApp / Telegram / Slack / future channels
                  |
                  v
          codex-chat-gateway
                  |
                  v
         codex-runtime-bridge
                  |
                  v
            codex app-server
                  |
                  v
         real Codex runtime
```

The gateway should consume the bridge, not bypass it.

## Planned Consumer Contract

The initial gateway design assumes the bridge provides:

- `POST /v1/chat`
- `POST /v1/chat/stream`
- `POST /v1/slash-commands/execute`
- `POST /v1/server-requests/respond`
- `POST /v1/threads/start`

Likely next additions for multi-device chat products:

- thread lookup and resume
- thread metadata reads
- structured health and diagnostics
- richer event and approval surfaces

## Initial Status

This repository is intentionally bootstrapped but not feature-complete yet.

Current contents:

- installable Python package skeleton
- minimal CLI
- architecture and boundary documentation
- roadmap for channel implementation

## Layout

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

## Install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
python -m unittest discover -s tests -p 'test_*.py'
codex-chat-gateway version
```

## Design Rules

- Keep the gateway separate from the runtime bridge.
- Treat `codex-runtime-bridge` as the source of truth for runtime behavior.
- Normalize channel events, but do not recreate Codex semantics locally.
- Prefer thin adapters per channel and a shared internal session model.
- Keep deployment guidance private-first and authenticated.

## Next Steps

1. Define the runtime bridge client contract this repository will consume.
2. Add a session store abstraction for contact to `threadId` mapping.
3. Add a channel abstraction for WhatsApp-first delivery.
4. Add inbound and outbound message normalization.
5. Design approval flows that work in external chat UIs.

