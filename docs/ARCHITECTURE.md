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

## Layers

```text
channel connector
  |
  +-- WhatsApp
  +-- Telegram
  +-- Slack
  |
  v
gateway core
  |
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

- `session store`
  - maps a channel identity or conversation to a `threadId`
  - tracks policy-scoped metadata such as workspace, allowed commands, and display preferences

- `channel adapter`
  - understands transport-specific delivery and inbound event shapes
  - converts them into the internal gateway model

- `approval coordinator`
  - turns bridge server requests into chat-friendly confirmations
  - correlates user responses back to the right runtime request id

- `media adapter`
  - handles channel file, image, and audio payloads
  - prepares inputs for bridge/runtime consumption

## Message Flow

1. A user sends a message from a chat platform.
2. The channel adapter authenticates and normalizes the inbound event.
3. The gateway resolves the session and associated `threadId`.
4. The runtime client calls `codex-runtime-bridge`.
5. Streamed events are converted into outbound channel updates.
6. If the runtime asks for approval or input, the approval coordinator stores state and asks the user through the channel.
7. The user's reply is mapped back into a bridge response.

## Initial Contract Assumptions

The first implementation should assume the bridge supports:

- one-shot chat
- streamed chat
- slash command execution
- server-request responses
- thread creation

Anything beyond that should be added explicitly to the bridge instead of guessed here.

