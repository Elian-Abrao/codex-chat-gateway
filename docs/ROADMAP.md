# Roadmap

## Phase 1: Bootstrap

- define repository boundaries
- define bridge contract assumptions
- add package skeleton and docs

## Phase 2: Runtime Contract

- add a typed bridge client
- define request and event models consumed from `codex-runtime-bridge`
- add error translation and diagnostics

## Phase 3: Session Layer

- add contact/chat to `threadId` mapping
- support per-user and per-channel policy metadata
- define persistence requirements

## Phase 4: WhatsApp MVP

- choose connector strategy
- support inbound text messages
- support outbound text delivery
- support streaming fan-out
- support approvals and follow-up prompts

## Phase 5: Media

- add image/file input handling
- design audio handling path
- normalize channel attachments into runtime-consumable inputs

## Phase 6: Multi-Channel

- extract a channel-neutral adapter contract
- add a second channel after WhatsApp
- validate that abstractions hold under a different transport

## Phase 7: Hardening

- retries and idempotency
- allowlists and policy controls
- observability
- operator diagnostics
- deploy guidance

