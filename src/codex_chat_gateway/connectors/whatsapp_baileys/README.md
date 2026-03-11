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

Outbound messages may now include:

- plain `text`
- `attachments` with `localPath` for existing local files the worker should send to WhatsApp
- mixed text + attachment replies, where the worker uses the text as a caption when the WhatsApp media type supports it

## Environment Variables

- `WHATSAPP_AUTH_DIR`
- `WHATSAPP_ALLOWLIST`
