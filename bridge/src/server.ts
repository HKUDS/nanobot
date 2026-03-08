/**
 * WebSocket server for Python-Node.js bridge communication.
 * Security: binds to loopback only; mandatory BRIDGE_TOKEN auth with timing-safe validation.
 */

import { timingSafeEqual } from 'crypto';
import { WebSocketServer, WebSocket, type RawData } from 'ws';
import { WhatsAppClient, InboundMessage } from './whatsapp.js';

const MAX_PAYLOAD_BYTES = 256 * 1024;

function getDataByteLength(data: RawData): number {
  if (typeof data === 'string') return Buffer.byteLength(data);
  if (Array.isArray(data)) {
    return data.reduce((total, chunk) => total + chunk.byteLength, 0);
  }
  if (Buffer.isBuffer(data)) return data.length;
  return data.byteLength;
}

function constantTimeEqual(a: string, b: string): boolean {
  const aBuf = Buffer.from(a);
  const bBuf = Buffer.from(b);
  if (aBuf.length !== bBuf.length) return false;
  return timingSafeEqual(aBuf, bBuf);
}

function isLoopbackAddress(addr: string | undefined): boolean {
  if (!addr) return false;
  return (
    addr === '127.0.0.1' ||
    addr === '::1' ||
    addr === '::ffff:127.0.0.1' ||
    addr.startsWith('::ffff:127.')
  );
}

function redactToken(error: unknown, token: string): string {
  const msg = String(error);
  return msg.replace(new RegExp(token.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'g'), '***');
}

interface SendCommand {
  type: 'send';
  to: string;
  text: string;
}

interface BridgeMessage {
  type: 'message' | 'status' | 'qr' | 'error';
  [key: string]: unknown;
}

export class BridgeServer {
  private wss: WebSocketServer | null = null;
  private wa: WhatsAppClient | null = null;
  private clients: Set<WebSocket> = new Set();

  constructor(
    private port: number,
    private authDir: string,
    private token: string,
    private host: string = '127.0.0.1'
  ) {}

  async start(): Promise<void> {
    this.wss = new WebSocketServer({ host: this.host, port: this.port });

    this.wa = new WhatsAppClient({
      authDir: this.authDir,
      onMessage: (msg) => this.broadcast({ type: 'message', ...msg }),
      onQR: (qr) => this.broadcast({ type: 'qr', qr }),
      onStatus: (status) => this.broadcast({ type: 'status', status }),
    });

    this.wss.on('connection', (ws, req) => {
      const remote = req.socket.remoteAddress;
      if (!isLoopbackAddress(remote)) {
        ws.close(1008, 'loopback only');
        return;
      }

      const timeout = setTimeout(() => ws.close(4001, 'Auth timeout'), 5000);
      ws.once('message', (data) => {
        clearTimeout(timeout);
        try {
          if (getDataByteLength(data) > MAX_PAYLOAD_BYTES) {
            ws.close(4004, 'Payload too large');
            return;
          }
          const msg = JSON.parse(data.toString());
          if (msg.type === 'auth' && constantTimeEqual(msg.token || '', this.token)) {
            console.log('🔗 Python client authenticated');
            this.setupClient(ws);
          } else {
            ws.close(4003, 'Invalid token');
          }
        } catch {
          ws.close(4003, 'Invalid auth message');
        }
      });
    });

    await this.wa.connect();
  }

  private setupClient(ws: WebSocket): void {
    this.clients.add(ws);

    ws.on('message', async (data) => {
      try {
        if (getDataByteLength(data) > MAX_PAYLOAD_BYTES) {
          ws.close(4004, 'Payload too large');
          return;
        }
        const cmd = JSON.parse(data.toString()) as SendCommand;
        await this.handleCommand(cmd);
        ws.send(JSON.stringify({ type: 'sent', to: cmd.to }));
      } catch (error) {
        const safeError = redactToken(error, this.token);
        console.error('Error handling command:', safeError);
        ws.send(JSON.stringify({ type: 'error', error: safeError }));
      }
    });

    ws.on('close', () => {
      console.log('🔌 Python client disconnected');
      this.clients.delete(ws);
    });

    ws.on('error', (error) => {
      console.error('WebSocket error:', error);
      this.clients.delete(ws);
    });
  }

  private async handleCommand(cmd: SendCommand): Promise<void> {
    if (cmd.type === 'send' && this.wa) {
      await this.wa.sendMessage(cmd.to, cmd.text);
    }
  }

  private broadcast(msg: BridgeMessage): void {
    const data = JSON.stringify(msg);
    for (const client of this.clients) {
      if (client.readyState === WebSocket.OPEN) {
        client.send(data);
      }
    }
  }

  async stop(): Promise<void> {
    // Close all client connections
    for (const client of this.clients) {
      client.close();
    }
    this.clients.clear();

    // Close WebSocket server
    if (this.wss) {
      this.wss.close();
      this.wss = null;
    }

    // Disconnect WhatsApp
    if (this.wa) {
      await this.wa.disconnect();
      this.wa = null;
    }
  }
}
