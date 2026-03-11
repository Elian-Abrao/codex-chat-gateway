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

## Current Phase

The first implementation step is deliberately smaller than runtime integration:

- connect to WhatsApp
- receive inbound messages
- send outbound messages
- prove reconnect and local auth persistence
- keep the core channel-neutral for future adapters

That means the current codebase now includes:

- a unified inbound/outbound message model
- a channel adapter interface
- a subprocess-based worker protocol for channel drivers
- a first built-in `whatsapp-baileys` adapter
- a simple echo gateway for transport validation before bridge integration
- a first bridge-backed mode where one WhatsApp group behaves like the agent chat

## Planned Consumer Contract

The initial gateway design assumes the bridge provides:

- `POST /v1/chat`
- `POST /v1/chat/consumer-stream`
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

- installable Python package
- multi-channel gateway core models
- channel adapter abstraction
- subprocess worker protocol
- WhatsApp/Baileys worker scaffold
- echo-mode CLI for transport validation
- architecture and boundary documentation

## Layout

```text
src/codex_chat_gateway/
  __init__.py
  __main__.py
  cli.py
  models.py
  version.py
  channel_adapters/
    base.py
    factory.py
    process.py
  services/
    echo.py
  connectors/
    whatsapp_baileys/
      package.json
      worker.mjs
docs/
  ARCHITECTURE.md
  ROADMAP.md
  WORKER_PROTOCOL.md
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

## WhatsApp Echo Spike

The first operational goal is transport-only validation, without the runtime bridge yet.

Install the Node dependencies for the built-in WhatsApp worker:

```bash
cd src/codex_chat_gateway/connectors/whatsapp_baileys
npm install
```

Then run the echo gateway:

```bash
codex-chat-gateway echo \
  --channel whatsapp-baileys \
  --auth-dir .state/whatsapp \
  --allow-from 5511999999999@s.whatsapp.net
```

What this does:

- starts the Python gateway core
- spawns the Baileys worker as a subprocess
- prints a QR code for WhatsApp pairing on first login
- receives inbound text messages
- replies with `echo: <message>`

This stage exists to validate WhatsApp transport behavior before adding `codex-runtime-bridge` calls.

## WhatsApp Group To Bridge

After the transport works, the next supported mode is:

- receive any message inside a target WhatsApp group
- forward those messages to `codex-runtime-bridge`
- keep one runtime thread per WhatsApp group
- send the runtime response back to the same WhatsApp group by default

Start your local bridge first, for example:

```bash
codex-runtime-bridge serve
```

Then run the chat gateway in bridge-backed mode:

```bash
codex-chat-gateway bridge-chat \
  --channel whatsapp-baileys \
  --auth-dir .state/whatsapp \
  --bridge-url http://127.0.0.1:8787 \
  --group-subject Codex
```

What this mode does right now:

- watches all messages from the WhatsApp group named `Codex`
- forwards the text to `codex-runtime-bridge`
- consumes the stable consumer stream from the bridge
- creates and reuses one `threadId` per WhatsApp group
- replies back to the same WhatsApp group with the final answer formatted as `[Codex]`

Optional visibility flags:

- `--show-commentary` sends Codex andamento messages back to WhatsApp in smaller progress messages
- `--show-reasoning` sends reasoning summaries back to WhatsApp in smaller progress messages
- `--show-actions` sends tool and command activity back to WhatsApp in quoted action blocks

Example with all progress updates enabled:

```bash
codex-chat-gateway bridge-chat \
  --channel whatsapp-baileys \
  --auth-dir .state/whatsapp \
  --bridge-url http://127.0.0.1:8787 \
  --group-subject Codex \
  --show-commentary \
  --show-reasoning \
  --show-actions
```

If you want to observe the bridge response without replying back to WhatsApp:

```bash
codex-chat-gateway bridge-chat \
  --channel whatsapp-baileys \
  --auth-dir .state/whatsapp \
  --bridge-url http://127.0.0.1:8787 \
  --group-subject Codex \
  --log-only
```

## Interactive Console

For debugging and validation, the repository also exposes an interactive terminal console.

It can:

- print target-group WhatsApp messages in the terminal
- send terminal text to WhatsApp
- inject prompts into `codex-runtime-bridge` from the terminal
- print Codex status, commentary, action steps, and final answers in the terminal

Example:

```bash
codex-chat-gateway console \
  --channel whatsapp-baileys \
  --auth-dir .state/whatsapp \
  --bridge-url http://127.0.0.1:8787 \
  --group-chat-id 120363424947858903@g.us \
  --log-only
```

Console commands:

- plain text: send to WhatsApp and, if the bridge is configured, also ask Codex
- `/wa <text>`: send to WhatsApp only
- `/codex <text>`: ask Codex only
- `/quit`: exit

By default, the terminal shows Codex progress, but WhatsApp only receives the final `[Codex]` reply.

If you also want WhatsApp to receive Codex progress messages:

- `--show-commentary` sends `[Codex • andamento]`
- `--show-reasoning` sends `[Codex • raciocínio]`
- `--show-actions` sends `[Codex • ações]`

## Design Rules

- Keep the gateway separate from the runtime bridge.
- Treat `codex-runtime-bridge` as the source of truth for runtime behavior.
- Normalize channel events, but do not recreate Codex semantics locally.
- Prefer thin adapters per channel and a shared internal session model.
- Keep channel SDK specifics inside connector workers when that reduces coupling.
- Keep deployment guidance private-first and authenticated.

## Next Steps

1. Persist the session store beyond process memory.
2. Add approval and pending-action state.
3. Add attachment handling for the WhatsApp worker.
4. Add a second channel adapter to validate the multi-channel shape.
