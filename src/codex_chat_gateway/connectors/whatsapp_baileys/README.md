# WhatsApp Baileys Worker

This connector is the first built-in channel worker for `codex-chat-gateway`.

It intentionally owns only the WhatsApp socket and message translation.

It does not know about:

- runtime bridge calls
- sessions to `threadId`
- approvals
- slash commands
- cross-channel policy

Those remain in the Python gateway core.

## Worker Protocol

The worker communicates with the Python gateway over NDJSON on stdio.

Worker -> gateway:

- `{"type":"ready","channel":"whatsapp"}`
- `{"type":"log","level":"info","message":"..."}`
- `{"type":"message","message":{...}}`
- `{"type":"error","message":"..."}`

Gateway -> worker:

- `{"type":"send_message","message":{...}}`

## Environment Variables

- `WHATSAPP_AUTH_DIR`
- `WHATSAPP_ALLOWLIST`

