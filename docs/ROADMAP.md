# Roadmap

## Phase 1: Bootstrap

- define repository boundaries
- define bridge contract assumptions
- add package skeleton and docs

## Phase 2: Transport Validation

- add a shared channel-neutral message model
- add a channel adapter abstraction
- add a worker protocol for connectors that need another runtime
- add a WhatsApp/Baileys echo spike

## Phase 3: Runtime Contract

- add a typed bridge client
- define request and event models consumed from `codex-runtime-bridge`
- add error translation and diagnostics

## Phase 4: Session Layer

- add contact/chat to `threadId` mapping
- support per-user and per-channel policy metadata
- define persistence requirements

## Phase 5: WhatsApp Bridge MVP

- replace echo mode with bridge-backed replies
- support streaming fan-out
- support approvals and follow-up prompts

## Phase 6: Media

- add image/file input handling
- design audio handling path
- normalize channel attachments into runtime-consumable inputs

## Phase 7: Multi-Channel

- extract a channel-neutral adapter contract
- add a second channel after WhatsApp
- validate that abstractions hold under a different transport

## Phase 8: Hardening

- retries and idempotency
- allowlists and policy controls
- observability
- operator diagnostics
- deploy guidance
