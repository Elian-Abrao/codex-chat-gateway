# Worker Protocol

`codex-chat-gateway` uses a simple NDJSON protocol between the Python gateway core and channel-specific workers.

The purpose is to keep the gateway core stable even when a channel SDK is better served by another runtime, such as Node for `Baileys`.

## Transport

- one JSON object per line
- worker stdin receives commands from the gateway
- worker stdout emits events to the gateway
- worker stderr is treated as diagnostic logging only

## Worker -> Gateway

### Ready

```json
{"type":"ready","channel":"whatsapp"}
```

### Log

```json
{"type":"log","level":"info","message":"WhatsApp connection opened."}
```

### Message

```json
{
  "type":"message",
  "message":{
    "messageId":"msg_1",
    "channel":"whatsapp",
    "chatId":"5511999999999@s.whatsapp.net",
    "senderId":"5511999999999@s.whatsapp.net",
    "text":"hello",
    "isGroup":false,
    "mentions":[],
    "attachments":[],
    "metadata":{}
  }
}
```

### Error

```json
{"type":"error","message":"WhatsApp socket not connected"}
```

## Gateway -> Worker

### Send Message

```json
{
  "type":"send_message",
  "message":{
    "channel":"whatsapp",
    "chatId":"5511999999999@s.whatsapp.net",
    "text":"echo: hello",
    "replyToMessageId":"msg_1",
    "attachments":[],
    "metadata":{"mode":"echo"}
  }
}
```

## Design Notes

- the worker owns channel SDK details and transport auth
- the gateway owns policy, sessions, runtime integration, and cross-channel rules
- the protocol is intentionally narrow so future channels can reuse it
