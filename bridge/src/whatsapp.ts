/**
 * WhatsApp client wrapper using Baileys.
 * Based on OpenClaw's working implementation.
 */

/* eslint-disable @typescript-eslint/no-explicit-any */
import makeWASocket, {
  DisconnectReason,
  useMultiFileAuthState,
  fetchLatestBaileysVersion,
  makeCacheableSignalKeyStore,
} from '@whiskeysockets/baileys';

import { Boom } from '@hapi/boom';
import qrcode from 'qrcode-terminal';
import pino from 'pino';

const VERSION = '0.1.0';

export interface InboundMessage {
  id: string;
  sender: string;
  pn: string;
  content: string;
  timestamp: number;
  isGroup: boolean;
}

export interface WhatsAppClientOptions {
  authDir: string;
  onMessage: (msg: InboundMessage) => void;
  onQR: (qr: string) => void;
  onStatus: (status: string) => void;
}

export class WhatsAppClient {
  private sock: any = null;
  private options: WhatsAppClientOptions;
  private reconnecting = false;
  private sentMessageIds = new Set<string>();

  constructor(options: WhatsAppClientOptions) {
    this.options = options;
  }

  async connect(): Promise<void> {
    const logger = pino({ level: 'silent' });
    const { state, saveCreds } = await useMultiFileAuthState(this.options.authDir);
    const { version } = await fetchLatestBaileysVersion();

    console.log(`Using Baileys version: ${version.join('.')}`);

    // Create socket following OpenClaw's pattern
    this.sock = makeWASocket({
      auth: {
        creds: state.creds,
        keys: makeCacheableSignalKeyStore(state.keys, logger),
      },
      version,
      logger,
      printQRInTerminal: false,
      browser: ['nanobot', 'cli', VERSION],
      syncFullHistory: true,
      markOnlineOnConnect: false,
      emitOwnEvents: true,
    });

    // Handle WebSocket errors
    if (this.sock.ws && typeof this.sock.ws.on === 'function') {
      this.sock.ws.on('error', (err: Error) => {
        console.error('WebSocket error:', err.message);
      });
    }

    // Handle connection updates
    this.sock.ev.on('connection.update', async (update: any) => {
      const { connection, lastDisconnect, qr } = update;

      if (qr) {
        // Display QR code in terminal
        console.log('\n📱 Scan this QR code with WhatsApp (Linked Devices):\n');
        qrcode.generate(qr, { small: true });
        this.options.onQR(qr);
      }

      if (connection === 'close') {
        const statusCode = (lastDisconnect?.error as Boom)?.output?.statusCode;
        const shouldReconnect = statusCode !== DisconnectReason.loggedOut;

        console.log(`Connection closed. Status: ${statusCode}, Will reconnect: ${shouldReconnect}`);
        this.options.onStatus('disconnected');

        if (shouldReconnect && !this.reconnecting) {
          this.reconnecting = true;
          console.log('Reconnecting in 5 seconds...');
          setTimeout(() => {
            this.reconnecting = false;
            this.connect();
          }, 5000);
        }
      } else if (connection === 'open') {
        console.log('✅ Connected to WhatsApp');
        this.options.onStatus('connected');
      }
    });

    // Save credentials on update
    this.sock.ev.on('creds.update', saveCreds);

    // Handle incoming messages
    this.sock.ev.on('messages.upsert', async ({ messages, type }: { messages: any[]; type: string }) => {
      if (type !== 'notify' && type !== 'append') return;

      for (const msg of messages) {
        const msgId = msg.key.id || '';
        
        // Skip bot's own replies (tracked by sendMessage to prevent infinite loops)
        if (this.sentMessageIds.has(msgId)) {
          this.sentMessageIds.delete(msgId);
          continue;
        }

        // Skip status updates
        if (msg.key.remoteJid === 'status@broadcast') continue;

        const content = this.extractMessageContent(msg);
        if (!content) continue;

        const isGroup = msg.key.remoteJid?.endsWith('@g.us') || false;

        this.options.onMessage({
          id: msg.key.id || '',
          sender: msg.key.remoteJid || '',
          pn: msg.key.remoteJidAlt || '',
          content,
          timestamp: msg.messageTimestamp as number,
          isGroup,
        });
      }
    });

    this.sock.ev.on('messages.update', async (updates: any[]) => {
      for (const update of updates) {
        const msg = { key: update.key, message: update.update?.message, messageTimestamp: Date.now() / 1000 };
        const msgId = msg.key.id || '';
        
        if (this.sentMessageIds.has(msgId)) {
          this.sentMessageIds.delete(msgId);
          continue;
        }
        
        if (msg.key.remoteJid === 'status@broadcast') continue;
        
        const content = this.extractMessageContent(msg);
        if (!content) continue;
        
        const isGroup = msg.key.remoteJid?.endsWith('@g.us') || false;
        
        this.options.onMessage({
          id: msg.key.id || '',
          sender: msg.key.remoteJid || '',
          pn: msg.key.remoteJidAlt || '',
          content,
          timestamp: msg.messageTimestamp as number,
          isGroup,
        });
      }
    });
  }

  private extractMessageContent(msg: any): string | null {
    const message = msg.message;
    if (!message) return null;

    // Text message
    if (message.conversation) {
      return message.conversation;
    }

    // Extended text (reply, link preview)
    if (message.extendedTextMessage?.text) {
      return message.extendedTextMessage.text;
    }

    // Image with caption
    if (message.imageMessage?.caption) {
      return `[Image] ${message.imageMessage.caption}`;
    }

    // Video with caption
    if (message.videoMessage?.caption) {
      return `[Video] ${message.videoMessage.caption}`;
    }

    // Document with caption
    if (message.documentMessage?.caption) {
      return `[Document] ${message.documentMessage.caption}`;
    }

    // Voice/Audio message
    if (message.audioMessage) {
      return `[Voice Message]`;
    }

    return null;
  }

  async sendMessage(to: string, text: string): Promise<void> {
    if (!this.sock) {
      throw new Error('Not connected');
    }

    const sent = await this.sock.sendMessage(to, { text });
    if (sent?.key?.id) {
      this.sentMessageIds.add(sent.key.id);
      setTimeout(() => this.sentMessageIds.delete(sent.key.id), 30000);
    }
  }

  async disconnect(): Promise<void> {
    if (this.sock) {
      this.sock.end(undefined);
      this.sock = null;
    }
  }
}
