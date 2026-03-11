# Architecture

## Problem

`codex-runtime-bridge` makes the local Codex runtime reachable.

It does not solve:

- WhatsApp session lifecycle
- external user identity
- channel webhooks or socket connectors
- external approval UX
- media adaptation for chat platforms

This repository exists to solve those channel-facing concerns without contaminating the runtime bridge.

## Core Principle

`codex-chat-gateway` is a consumer of the runtime bridge, not a second runtime.

It should translate:

- inbound channel events into bridge requests
- streamed bridge responses into outbound channel messages
- bridge approvals into channel-native follow-up interactions

In the first WhatsApp phase, it also needs to validate raw transport behavior before the bridge is involved.

## Layers

```text
channel worker
  |
  +-- WhatsApp
  +-- Telegram
  +-- Slack
  |
  v
gateway core
  |
  +-- worker protocol
  +-- runtime bridge client
  +-- session mapping
  +-- channel-neutral message model
  +-- approval orchestration
  +-- delivery and retry policy
  |
  v
codex-runtime-bridge
  |
  v
codex app-server
  |
  v
Codex runtime
```

## Planned Internal Responsibilities

- `runtime client`
  - owns communication with `codex-runtime-bridge`
  - handles normal chat, streaming, slash commands, and approvals

- `worker protocol`
  - lets channel-specific SDKs live behind a process boundary when needed
  - keeps the gateway core channel-neutral even if a channel requires another language or runtime

- `session store`
  - maps a channel identity or conversation to a `threadId`
  - tracks policy-scoped metadata such as workspace, allowed commands, and display preferences
  - the first live use case is one runtime thread per WhatsApp group
  - the current implementation persists sessions to a local JSON file so restart does not lose `threadId` or pending requests

- `channel adapter`
  - owns adapter lifecycle inside the Python core
  - receives normalized inbound messages from a worker or in-process driver
  - sends normalized outbound messages back to the channel implementation

- `approval coordinator`
  - turns bridge server requests into chat-friendly confirmations
  - correlates user responses back to the right runtime request id
  - the current WhatsApp flow exposes `/pending`, `/approve`, `/reject`, and `/answer ...`

- `media adapter`
  - handles channel file, image, and audio payloads
  - prepares inputs for bridge/runtime consumption

## Message Flow

1. A user sends a message from a chat platform.
2. A channel worker receives the raw event from the external SDK.
3. The worker normalizes the event and emits it to the gateway core.
4. In echo mode, the gateway replies directly through the worker.
5. In bridge mode, the gateway resolves the session and calls `codex-runtime-bridge`.
6. Streamed events are converted into outbound channel updates.
7. If the runtime asks for approval or input, the approval coordinator stores state and asks the user through the channel.
8. The user's reply is mapped back into a bridge response.

## Current Approval Flow

For the first WhatsApp bridge mode:

- pending requests are tracked per group session
- normal prompts are blocked while a pending request exists
- approval requests are answered with:
  - `/approve`
  - `/reject`
- input requests are answered with:
  - `/answer <text>`
  - `/answer {"field":"value"}`

This keeps the approval loop in the chat channel without reimplementing runtime semantics locally.

## Current Session Persistence

For the current single-user WhatsApp flow:

- the default persisted session store lives next to the auth directory as `sessions.json`
- `threadId` is reused after restart
- pending approval and input requests are reused after restart
- `active_turn` is intentionally reset on load so a previous crash does not leave the chat blocked forever
- once a persisted pending request is resolved, the gateway uses bridge-side `thread/resume` to recover the final answer for that same turn

This is intentionally a local single-process store, not a distributed state layer.

## Current WhatsApp Direction

The first built-in adapter uses:

- Python gateway core
- Node worker for WhatsApp
- `Baileys` as the WhatsApp SDK
- NDJSON over stdio between Python and the worker

This is an intentional architectural choice:

- WhatsApp gets an actual transport implementation early
- the core stays reusable for future channels
- channel-specific SDK choices do not dictate the gateway language

## First Bridge-Backed Use Case

The first real runtime integration target is intentionally narrow:

- one WhatsApp group
- messages inside that group
- text-only forwarding
- runtime response logged locally
- automatic reply back to the same group by default

This keeps the product direction aligned with a personal remote-control workflow while avoiding early complexity around:

- replying to other people
- DM policy
- group mention rules
- approval UX in chat

## Initial Contract Assumptions

The first implementation should assume the bridge supports:

- one-shot chat
- streamed chat
- slash command execution
- server-request responses
- thread creation

Anything beyond that should be added explicitly to the bridge instead of guessed here.
