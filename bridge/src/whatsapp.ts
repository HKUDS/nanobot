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
  extractMessageContent as baileysExtractMessageContent,
} from '@whiskeysockets/baileys';

import { Boom } from '@hapi/boom';
import qrcode from 'qrcode-terminal';
import pino from 'pino';
import { readFile, writeFile, mkdir } from 'fs/promises';
import { join, basename } from 'path';
import { randomBytes } from 'crypto';

const VERSION = '0.1.0';

export interface InboundMessage {
  id: string;
  sender: string;      // Chat JID (group JID for groups, user JID for DMs)
  pn: string;
  participant?: string; // For group messages: the individual sender's JID
  content: string;
  timestamp: number;
  isGroup: boolean;
  wasMentioned?: boolean;
  isReplyToBot?: boolean;
  media?: string[];
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

  private normalizeJid(jid: string | undefined | null): string {
    return (jid || '').split(':')[0];
  }

  /**
   * LID-aware bot-mention and reply-to-bot detection.
   *
   * Checks @mentions AND swipe-to-reply against both the bot's phone-based
   * JID and its LID (Linked ID). In LID-migrated groups, the bot's JID in
   * contextInfo uses the LID form, so checking only the phone JID misses
   * mentions and reply-to-bot in those groups.
   *
   * Device suffixes (e.g. ":5" in "1234:5@s.whatsapp.net") are stripped
   * before comparison, and mentionedJid is collected from all message types
   * (text, image, video, document, audio).
   */
  private detectBotMention(msg: any): { wasMentioned: boolean; isReplyToBot: boolean } {
    const botJid = this.sock?.user?.id || '';
    const botJidBase = botJid.replace(/:\d+@/, '@');
    const botLid = (this.sock?.user as any)?.lid || '';
    const botLidBase = botLid ? botLid.replace(/:\d+@/, '@') : '';

    const unwrapped = baileysExtractMessageContent(msg.message);

    // Collect mentionedJid from all message types that can carry mentions
    const candidates = [
      unwrapped?.extendedTextMessage?.contextInfo?.mentionedJid,
      unwrapped?.imageMessage?.contextInfo?.mentionedJid,
      unwrapped?.videoMessage?.contextInfo?.mentionedJid,
      unwrapped?.documentMessage?.contextInfo?.mentionedJid,
      unwrapped?.audioMessage?.contextInfo?.mentionedJid,
    ];
    const mentionedJids = candidates.flatMap((items) => (Array.isArray(items) ? items : []));

    const wasMentioned = mentionedJids.some(
      (jid) => jid === botJid || jid === botJidBase ||
               (botLid && jid === botLid) || (botLidBase && jid === botLidBase)
    );

    // Check swipe-to-reply: contextInfo.participant is the quoted message's
    // author. In LID-migrated groups this uses the bot's LID, not phone JID.
    const contextInfo = unwrapped?.extendedTextMessage?.contextInfo;
    const quotedParticipant = contextInfo?.participant ?? '';
    const isReplyToBot = !!(
      contextInfo?.stanzaId &&
      (
        quotedParticipant === botJid ||
        quotedParticipant === botJidBase ||
        (botLid && quotedParticipant === botLid) ||
        (botLidBase && quotedParticipant === botLidBase)
      )
    );

    return { wasMentioned, isReplyToBot };
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
        if (msg.key.fromMe) continue;
        if (msg.key.remoteJid === 'status@broadcast') continue;

        const unwrapped = baileysExtractMessageContent(msg.message);
        if (!unwrapped) continue;

        const content = this.getTextContent(unwrapped);
        let fallbackContent: string | null = null;
        const mediaPaths: string[] = [];

        if (unwrapped.imageMessage) {
          fallbackContent = '[Image]';
          const path = await this.downloadMedia(msg, unwrapped.imageMessage.mimetype ?? undefined);
          if (path) mediaPaths.push(path);
        } else if (unwrapped.documentMessage) {
          fallbackContent = '[Document]';
          const path = await this.downloadMedia(msg, unwrapped.documentMessage.mimetype ?? undefined,
            unwrapped.documentMessage.fileName ?? undefined);
          if (path) mediaPaths.push(path);
        } else if (unwrapped.videoMessage) {
          fallbackContent = '[Video]';
          const path = await this.downloadMedia(msg, unwrapped.videoMessage.mimetype ?? undefined);
          if (path) mediaPaths.push(path);
        }

        const finalContent = content || (mediaPaths.length === 0 ? fallbackContent : '') || '';
        if (!finalContent && mediaPaths.length === 0) continue;

        const isGroup = msg.key.remoteJid?.endsWith('@g.us') || false;
        const { wasMentioned, isReplyToBot } = this.detectBotMention(msg);
        const effectivelyMentioned = wasMentioned || isReplyToBot;

        this.options.onMessage({
          id: msg.key.id || '',
          sender: msg.key.remoteJid || '',
          pn: msg.key.remoteJidAlt || '',
          ...(isGroup && msg.key.participant ? { participant: msg.key.participant } : {}),
          content: finalContent,
          timestamp: msg.messageTimestamp as number,
          isGroup,
          ...(isGroup ? { wasMentioned: effectivelyMentioned, isReplyToBot } : {}),
          ...(mediaPaths.length > 0 ? { media: mediaPaths } : {}),
        });
      }
    });
  }

  private async downloadMedia(msg: any, mimetype?: string, fileName?: string): Promise<string | null> {
    try {
      const mediaDir = join(this.options.authDir, '..', 'media');
      await mkdir(mediaDir, { recursive: true });

      const buffer = await downloadMediaMessage(msg, 'buffer', {}) as Buffer;

      let outFilename: string;
      if (fileName) {
        // Documents have a filename — use it with a unique prefix to avoid collisions
        const prefix = `wa_${Date.now()}_${randomBytes(4).toString('hex')}_`;
        outFilename = prefix + fileName;
      } else {
        const mime = mimetype || 'application/octet-stream';
        // Derive extension from mimetype subtype (e.g. "image/png" → ".png", "application/pdf" → ".pdf")
        const ext = '.' + (mime.split('/').pop()?.split(';')[0] || 'bin');
        outFilename = `wa_${Date.now()}_${randomBytes(4).toString('hex')}${ext}`;
      }

      const filepath = join(mediaDir, outFilename);
      await writeFile(filepath, buffer);

      return filepath;
    } catch (err) {
      console.error('Failed to download media:', err);
      return null;
    }
  }

  private getTextContent(message: any): string | null {
    // Text message
    if (message.conversation) {
      return message.conversation;
    }

    // Extended text (reply, link preview)
    if (message.extendedTextMessage?.text) {
      return message.extendedTextMessage.text;
    }

    // Image with optional caption
    if (message.imageMessage) {
      return message.imageMessage.caption || '';
    }

    // Video with optional caption
    if (message.videoMessage) {
      return message.videoMessage.caption || '';
    }

    // Document with optional caption
    if (message.documentMessage) {
      return message.documentMessage.caption || '';
    }

    // Voice/Audio message
    if (message.audioMessage) {
      return `[Voice Message]`;
    }

    return null;
  }

  /**
   * Extract mention JIDs from text containing @<digits> patterns.
   *
   * WhatsApp requires an explicit `mentions` array in the message payload
   * for @mentions to be tappable. This method parses @-prefixed digit
   * sequences and constructs the appropriate JID:
   * - 14+ digits → LID domain (@lid)
   * - Fewer digits → phone domain (@s.whatsapp.net)
   *
   * WhatsApp LIDs are typically 14-digit identifiers, whereas phone-number
   * JIDs are typically 10–13 digits (country code + number).
   */
  static extractMentionJids(text: string): string[] {
    const jids: string[] = [];
    const pattern = /@(\d+)/g;
    let match: RegExpExecArray | null;
    while ((match = pattern.exec(text)) !== null) {
      const digits = match[1];
      const domain = digits.length >= 14 ? 'lid' : 's.whatsapp.net';
      jids.push(`${digits}@${domain}`);
    }
    return jids;
  }

  async sendMessage(to: string, text: string, mentions?: string[]): Promise<void> {
    if (!this.sock) {
      throw new Error('Not connected');
    }

    const effectiveMentions = mentions ?? WhatsAppClient.extractMentionJids(text);
    await this.sock.sendMessage(to, {
      text,
      ...(effectiveMentions.length ? { mentions: effectiveMentions } : {}),
    });
  }

  async sendMedia(
    to: string,
    filePath: string,
    mimetype: string,
    caption?: string,
    fileName?: string,
  ): Promise<void> {
    if (!this.sock) {
      throw new Error('Not connected');
    }

    const buffer = await readFile(filePath);
    const category = mimetype.split('/')[0];

    if (category === 'image') {
      await this.sock.sendMessage(to, { image: buffer, caption: caption || undefined, mimetype });
    } else if (category === 'video') {
      await this.sock.sendMessage(to, { video: buffer, caption: caption || undefined, mimetype });
    } else if (category === 'audio') {
      await this.sock.sendMessage(to, { audio: buffer, mimetype });
    } else {
      const name = fileName || basename(filePath);
      await this.sock.sendMessage(to, { document: buffer, mimetype, fileName: name });
    }
  }

  async disconnect(): Promise<void> {
    if (this.sock) {
      this.sock.end(undefined);
      this.sock = null;
    }
  }
}
