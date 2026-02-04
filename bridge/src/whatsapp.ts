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
  downloadMediaMessage,
  proto,
} from '@whiskeysockets/baileys';

import { Boom } from '@hapi/boom';
import qrcode from 'qrcode-terminal';
import pino from 'pino';

const VERSION = '0.1.0';

export interface MediaInfo {
  type: 'image' | 'audio' | 'video' | 'document';
  mimetype: string;
  data: string;  // base64-encoded
  filename?: string;
}

export interface InboundMessage {
  id: string;
  sender: string;
  content: string;
  timestamp: number;
  isGroup: boolean;
  media?: MediaInfo;
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
      syncFullHistory: false,
      markOnlineOnConnect: false,
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
      if (type !== 'notify') return;

      for (const msg of messages) {
        // Skip own messages
        if (msg.key.fromMe) continue;

        // Skip status updates
        if (msg.key.remoteJid === 'status@broadcast') continue;

        const { content, media } = await this.extractMessageContent(msg);
        if (!content) continue;

        const isGroup = msg.key.remoteJid?.endsWith('@g.us') || false;

        this.options.onMessage({
          id: msg.key.id || '',
          sender: msg.key.remoteJid || '',
          content,
          timestamp: msg.messageTimestamp as number,
          isGroup,
          media,
        });
      }
    });
  }

  private async extractMessageContent(msg: any): Promise<{ content: string | null; media?: MediaInfo }> {
    const message = msg.message;
    if (!message) return { content: null };

    // Text message
    if (message.conversation) {
      return { content: message.conversation };
    }

    // Extended text (reply, link preview)
    if (message.extendedTextMessage?.text) {
      return { content: message.extendedTextMessage.text };
    }

    // Image message
    if (message.imageMessage) {
      const caption = message.imageMessage.caption || '';
      const media = await this.downloadMedia(msg, 'image', message.imageMessage.mimetype);
      return {
        content: caption ? `[Image] ${caption}` : '[Image]',
        media
      };
    }

    // Video message
    if (message.videoMessage) {
      const caption = message.videoMessage.caption || '';
      const media = await this.downloadMedia(msg, 'video', message.videoMessage.mimetype);
      return {
        content: caption ? `[Video] ${caption}` : '[Video]',
        media
      };
    }

    // Document message
    if (message.documentMessage) {
      const caption = message.documentMessage.caption || '';
      const filename = message.documentMessage.fileName;
      const media = await this.downloadMedia(msg, 'document', message.documentMessage.mimetype, filename);
      return {
        content: caption ? `[Document: ${filename}] ${caption}` : `[Document: ${filename}]`,
        media
      };
    }

    // Voice/Audio message
    if (message.audioMessage) {
      const media = await this.downloadMedia(msg, 'audio', message.audioMessage.mimetype || 'audio/ogg');
      return {
        content: '[Voice Message]',
        media
      };
    }

    return { content: null };
  }

  private async downloadMedia(
    msg: any,
    type: 'image' | 'audio' | 'video' | 'document',
    mimetype: string,
    filename?: string
  ): Promise<MediaInfo | undefined> {
    try {
      const buffer = await downloadMediaMessage(
        msg,
        'buffer',
        {},
        {
          logger: pino({ level: 'silent' }),
          reuploadRequest: this.sock.updateMediaMessage,
        }
      );

      const data = (buffer as Buffer).toString('base64');
      console.log(`📥 Downloaded ${type} (${Math.round(data.length / 1024)}KB base64)`);

      return {
        type,
        mimetype,
        data,
        filename,
      };
    } catch (error) {
      console.error(`Failed to download ${type}:`, error);
      return undefined;
    }
  }

  async sendMessage(to: string, text: string): Promise<void> {
    if (!this.sock) {
      throw new Error('Not connected');
    }

    await this.sock.sendMessage(to, { text });
  }

  async sendMedia(
    to: string,
    mediaData: string,
    mimetype: string,
    type: 'image' | 'audio' | 'video' | 'document',
    caption?: string,
    filename?: string,
    ptt?: boolean  // Push-to-talk (voice note)
  ): Promise<void> {
    if (!this.sock) {
      throw new Error('Not connected');
    }

    const buffer = Buffer.from(mediaData, 'base64');

    switch (type) {
      case 'image':
        await this.sock.sendMessage(to, {
          image: buffer,
          mimetype,
          caption,
        });
        break;
      case 'audio':
        await this.sock.sendMessage(to, {
          audio: buffer,
          mimetype: mimetype || 'audio/ogg; codecs=opus',
          ptt: ptt ?? true,  // Send as voice note by default
        });
        break;
      case 'video':
        await this.sock.sendMessage(to, {
          video: buffer,
          mimetype,
          caption,
        });
        break;
      case 'document':
        await this.sock.sendMessage(to, {
          document: buffer,
          mimetype,
          fileName: filename || 'document',
          caption,
        });
        break;
    }

    console.log(`📤 Sent ${type} to ${to}`);
  }

  async disconnect(): Promise<void> {
    if (this.sock) {
      this.sock.end(undefined);
      this.sock = null;
    }
  }
}
