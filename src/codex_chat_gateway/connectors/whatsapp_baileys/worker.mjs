import fs from "node:fs";
import path from "node:path";
import readline from "node:readline";

import makeWASocket, {
  DisconnectReason,
  fetchLatestBaileysVersion,
  useMultiFileAuthState,
} from "@whiskeysockets/baileys";
import pino from "pino";
import qrcode from "qrcode-terminal";

for (const method of ["log", "info", "warn", "error", "debug"]) {
  console[method] = (...args) => {
    process.stderr.write(args.map((value) => String(value)).join(" ") + "\n");
  };
}

const logger = pino(
  { level: process.env.LOG_LEVEL || "info" },
  pino.destination(2),
);
const allowlist = new Set(
  (process.env.WHATSAPP_ALLOWLIST || "")
    .split(",")
    .map((value) => value.trim())
    .filter(Boolean),
);
const includeFromMe = process.env.WHATSAPP_INCLUDE_FROM_ME === "1";
const authDir = path.resolve(
  process.env.WHATSAPP_AUTH_DIR || path.join(process.cwd(), ".state", "whatsapp"),
);
const groupSubjectCache = new Map();
const sentMessageIds = new Set();

function emit(payload) {
  process.stdout.write(JSON.stringify(payload) + "\n");
}

function log(level, message, extra = {}) {
  logger[level]?.(extra, message);
  emit({ type: "log", level, message, ...extra });
}

function ensureDirectory(dirPath) {
  fs.mkdirSync(dirPath, { recursive: true });
}

function extractText(message) {
  if (!message) {
    return null;
  }
  return (
    message.conversation ||
    message.extendedTextMessage?.text ||
    message.imageMessage?.caption ||
    message.videoMessage?.caption ||
    message.documentWithCaptionMessage?.message?.documentMessage?.caption ||
    null
  );
}

function extractMentions(message) {
  return (
    message?.extendedTextMessage?.contextInfo?.mentionedJid ||
    message?.imageMessage?.contextInfo?.mentionedJid ||
    message?.videoMessage?.contextInfo?.mentionedJid ||
    []
  );
}

function extractAttachments(message) {
  if (!message) {
    return [];
  }
  if (message.imageMessage) {
    return [
      {
        kind: "image",
        mimeType: message.imageMessage.mimetype || null,
        fileName: message.imageMessage.fileName || null,
      },
    ];
  }
  if (message.audioMessage) {
    return [
      {
        kind: "audio",
        mimeType: message.audioMessage.mimetype || null,
      },
    ];
  }
  if (message.documentMessage) {
    return [
      {
        kind: "file",
        mimeType: message.documentMessage.mimetype || null,
        fileName: message.documentMessage.fileName || null,
      },
    ];
  }
  return [];
}

async function resolveGroupSubject(remoteJid) {
  if (!remoteJid || !remoteJid.endsWith("@g.us") || !sock) {
    return null;
  }
  if (groupSubjectCache.has(remoteJid)) {
    return groupSubjectCache.get(remoteJid);
  }
  try {
    const metadata = await sock.groupMetadata(remoteJid);
    const subject = metadata?.subject || null;
    groupSubjectCache.set(remoteJid, subject);
    return subject;
  } catch (error) {
    log("warn", "Failed to resolve group subject.", {
      remoteJid,
      error: error instanceof Error ? error.message : String(error),
    });
    return null;
  }
}

async function normalizeInboundMessage(msg) {
  const remoteJid = msg.key.remoteJid;
  const senderId = msg.key.participant || remoteJid;
  const isGroup = Boolean(remoteJid && remoteJid.endsWith("@g.us"));
  const groupSubject = isGroup ? await resolveGroupSubject(remoteJid) : null;
  return {
    messageId: msg.key.id,
    channel: "whatsapp",
    chatId: remoteJid,
    senderId,
    text: extractText(msg.message),
    isGroup,
    mentions: extractMentions(msg.message),
    attachments: extractAttachments(msg.message),
    metadata: {
      fromMe: Boolean(msg.key.fromMe),
      groupSubject,
      pushName: msg.pushName || null,
      timestamp: msg.messageTimestamp || null,
    },
  };
}

function isAllowed(message) {
  if (allowlist.size === 0) {
    return true;
  }
  return allowlist.has(message.chatId) || allowlist.has(message.senderId);
}

async function createSocket() {
  ensureDirectory(authDir);
  const { state, saveCreds } = await useMultiFileAuthState(authDir);
  const { version } = await fetchLatestBaileysVersion();

  const socket = makeWASocket({
    auth: state,
    version,
    printQRInTerminal: false,
    logger,
    browser: ["codex-chat-gateway", "chrome", "1.0.0"],
  });

  socket.ev.on("creds.update", saveCreds);
  return socket;
}

let sock = null;
let readyEmitted = false;
let reconnectTimer = null;
let reconnectDelayMs = 500;
let socketGeneration = 0;

function scheduleReconnect(reason) {
  if (reconnectTimer) {
    return;
  }
  const delayMs = reconnectDelayMs;
  reconnectDelayMs = Math.min(reconnectDelayMs * 2, 5000);
  log("info", "Scheduling WhatsApp reconnect.", { reason, delayMs });
  reconnectTimer = setTimeout(async () => {
    reconnectTimer = null;
    try {
      await connect();
    } catch (error) {
      log("error", "WhatsApp reconnect attempt failed.", {
        reason,
        error: error instanceof Error ? error.message : String(error),
      });
      scheduleReconnect("retry_after_failed_reconnect");
    }
  }, delayMs);
}

async function connect() {
  const generation = ++socketGeneration;
  const socket = await createSocket();
  sock = socket;
  groupSubjectCache.clear();

  socket.ev.on("connection.update", async (update) => {
    if (sock !== socket || generation !== socketGeneration) {
      return;
    }
    const { connection, lastDisconnect, qr } = update;
    if (qr) {
      qrcode.generate(qr, { small: true }, (qrText) => {
        process.stderr.write(qrText + "\n");
      });
      log("info", "Scan the QR code above with WhatsApp.");
    }
    if (connection === "open") {
      reconnectDelayMs = 500;
      if (!readyEmitted) {
        readyEmitted = true;
        emit({ type: "ready", channel: "whatsapp" });
      }
      log("info", "WhatsApp connection opened.");
      return;
    }
    if (connection === "close") {
      const statusCode = lastDisconnect?.error?.output?.statusCode;
      const shouldReconnect = statusCode !== DisconnectReason.loggedOut;
      sock = null;
      log("warn", "WhatsApp connection closed.", {
        statusCode: statusCode || null,
        reconnect: shouldReconnect,
      });
      if (shouldReconnect) {
        scheduleReconnect(statusCode || "unknown_close");
        return;
      }
    }
  });

  socket.ev.on("messages.upsert", async (event) => {
    if (sock !== socket || generation !== socketGeneration) {
      return;
    }
    for (const msg of event.messages || []) {
      if (!msg.message) {
        continue;
      }
      if (sentMessageIds.has(msg.key.id)) {
        sentMessageIds.delete(msg.key.id);
        continue;
      }
      if (msg.key.fromMe && !includeFromMe) {
        continue;
      }
      const normalized = await normalizeInboundMessage(msg);
      if (!isAllowed(normalized)) {
        log("info", "Ignored inbound message outside allowlist.", {
          chatId: normalized.chatId,
          senderId: normalized.senderId,
        });
        continue;
      }
      emit({ type: "message", message: normalized });
    }
  });
}

async function sendMessage(payload) {
  if (!sock) {
    throw new Error("WhatsApp socket not connected");
  }
  if (!payload.chatId) {
    throw new Error("Outbound message is missing chatId");
  }
  if (!payload.text) {
    throw new Error("Only outbound text is supported in the first WhatsApp MVP");
  }
  const result = await sock.sendMessage(payload.chatId, {
    text: payload.text,
    linkPreview: null,
  });
  if (result?.key?.id) {
    sentMessageIds.add(result.key.id);
  }
}

const input = readline.createInterface({
  input: process.stdin,
  crlfDelay: Infinity,
});

input.on("line", async (line) => {
  if (!line.trim()) {
    return;
  }
  try {
    const payload = JSON.parse(line);
    if (payload.type === "send_message") {
      await sendMessage(payload.message);
      return;
    }
    emit({ type: "error", message: `Unknown command: ${payload.type}` });
  } catch (error) {
    emit({
      type: "error",
      message: error instanceof Error ? error.message : String(error),
    });
  }
});

try {
  await connect();
} catch (error) {
  log("error", "Initial WhatsApp connection failed.", {
    error: error instanceof Error ? error.message : String(error),
  });
  scheduleReconnect("initial_connect_failed");
}
