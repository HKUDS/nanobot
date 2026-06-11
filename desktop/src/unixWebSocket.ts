import net from "node:net";
import { randomBytes } from "node:crypto";

type UnixWebSocketHandlers = {
  onClose: (code?: number, reason?: string) => void;
  onError: (message: string) => void;
  onMessage: (data: string) => void;
  onOpen: () => void;
};

const OPCODE_CONTINUATION = 0x0;
const OPCODE_TEXT = 0x1;
const OPCODE_CLOSE = 0x8;
const OPCODE_PING = 0x9;
const OPCODE_PONG = 0xa;

export class UnixWebSocketClient {
  private frameBuffer = Buffer.alloc(0);
  private handshakeBuffer = Buffer.alloc(0);
  private open = false;
  private socket: net.Socket | null = null;
  private fragmentedText: Buffer[] = [];

  constructor(
    private readonly socketPath: string,
    private readonly url: string,
    private readonly handlers: UnixWebSocketHandlers,
  ) {}

  connect(): void {
    const socket = net.createConnection(this.socketPath);
    this.socket = socket;
    socket.once("connect", () => this.writeHandshake());
    socket.on("data", (chunk) => this.handleData(chunk));
    socket.on("error", (error) => this.fail(error.message));
    socket.on("close", () => {
      if (this.open) {
        this.open = false;
        this.handlers.onClose();
      }
    });
  }

  send(data: string): void {
    if (!this.open || !this.socket || this.socket.destroyed) {
      throw new Error("host socket is not open");
    }
    this.socket.write(encodeFrame(OPCODE_TEXT, Buffer.from(data, "utf8")));
  }

  close(code = 1000, reason = ""): void {
    const socket = this.socket;
    if (!socket || socket.destroyed) return;
    const reasonBuffer = Buffer.from(reason, "utf8");
    const payload = Buffer.alloc(2 + reasonBuffer.length);
    payload.writeUInt16BE(code, 0);
    reasonBuffer.copy(payload, 2);
    socket.write(encodeFrame(OPCODE_CLOSE, payload));
    socket.end();
  }

  private writeHandshake(): void {
    const socket = this.socket;
    if (!socket) return;
    const requestUrl = new URL(this.url);
    const path = `${requestUrl.pathname || "/"}${requestUrl.search}`;
    const key = randomBytes(16).toString("base64");
    socket.write(
      [
        `GET ${path} HTTP/1.1`,
        "Host: nanobot.host",
        "Upgrade: websocket",
        "Connection: Upgrade",
        `Sec-WebSocket-Key: ${key}`,
        "Sec-WebSocket-Version: 13",
        "\r\n",
      ].join("\r\n"),
    );
  }

  private handleData(chunk: Buffer): void {
    if (!this.open) {
      this.handshakeBuffer = Buffer.concat([this.handshakeBuffer, chunk]);
      const headerEnd = this.handshakeBuffer.indexOf("\r\n\r\n");
      if (headerEnd === -1) return;
      const header = this.handshakeBuffer.subarray(0, headerEnd).toString("utf8");
      const remainder = this.handshakeBuffer.subarray(headerEnd + 4);
      this.handshakeBuffer = Buffer.alloc(0);
      if (!header.startsWith("HTTP/1.1 101")) {
        this.fail(`host socket upgrade failed: ${header.split("\r\n")[0]}`);
        return;
      }
      this.open = true;
      this.handlers.onOpen();
      if (remainder.length > 0) this.handleFrames(remainder);
      return;
    }
    this.handleFrames(chunk);
  }

  private handleFrames(chunk: Buffer): void {
    this.frameBuffer = Buffer.concat([this.frameBuffer, chunk]);
    while (this.frameBuffer.length >= 2) {
      const first = this.frameBuffer[0];
      const second = this.frameBuffer[1];
      const fin = (first & 0x80) !== 0;
      const opcode = first & 0x0f;
      const masked = (second & 0x80) !== 0;
      let length = second & 0x7f;
      let offset = 2;

      if (length === 126) {
        if (this.frameBuffer.length < offset + 2) return;
        length = this.frameBuffer.readUInt16BE(offset);
        offset += 2;
      } else if (length === 127) {
        if (this.frameBuffer.length < offset + 8) return;
        const bigLength = this.frameBuffer.readBigUInt64BE(offset);
        if (bigLength > BigInt(Number.MAX_SAFE_INTEGER)) {
          this.fail("host socket frame is too large");
          return;
        }
        length = Number(bigLength);
        offset += 8;
      }

      let mask: Buffer | null = null;
      if (masked) {
        if (this.frameBuffer.length < offset + 4) return;
        mask = this.frameBuffer.subarray(offset, offset + 4);
        offset += 4;
      }
      if (this.frameBuffer.length < offset + length) return;

      const rawPayload = Buffer.from(this.frameBuffer.subarray(offset, offset + length));
      this.frameBuffer = this.frameBuffer.subarray(offset + length);
      const payload = mask ? unmask(rawPayload, mask) : rawPayload;

      if (opcode === OPCODE_TEXT || opcode === OPCODE_CONTINUATION) {
        this.handleTextFrame(opcode, payload, fin);
      } else if (opcode === OPCODE_PING) {
        this.socket?.write(encodeFrame(OPCODE_PONG, payload));
      } else if (opcode === OPCODE_CLOSE) {
        const code = payload.length >= 2 ? payload.readUInt16BE(0) : undefined;
        const reason = payload.length > 2 ? payload.subarray(2).toString("utf8") : undefined;
        this.open = false;
        this.socket?.end();
        this.handlers.onClose(code, reason);
        return;
      }
    }
  }

  private handleTextFrame(opcode: number, payload: Buffer, fin: boolean): void {
    if (opcode === OPCODE_TEXT && fin) {
      this.handlers.onMessage(payload.toString("utf8"));
      return;
    }
    if (opcode === OPCODE_TEXT) {
      this.fragmentedText = [payload];
      return;
    }
    if (this.fragmentedText.length === 0) return;
    this.fragmentedText.push(payload);
    if (fin) {
      const data = Buffer.concat(this.fragmentedText).toString("utf8");
      this.fragmentedText = [];
      this.handlers.onMessage(data);
    }
  }

  private fail(message: string): void {
    this.handlers.onError(message);
    this.socket?.destroy();
  }
}

function encodeFrame(opcode: number, payload: Buffer): Buffer {
  const length = payload.length;
  const headerLength = length < 126 ? 2 : length <= 0xffff ? 4 : 10;
  const header = Buffer.alloc(headerLength + 4);
  header[0] = 0x80 | opcode;
  if (length < 126) {
    header[1] = 0x80 | length;
  } else if (length <= 0xffff) {
    header[1] = 0x80 | 126;
    header.writeUInt16BE(length, 2);
  } else {
    header[1] = 0x80 | 127;
    header.writeBigUInt64BE(BigInt(length), 2);
  }
  const maskOffset = headerLength;
  const mask = randomBytes(4);
  mask.copy(header, maskOffset);
  const masked = Buffer.alloc(payload.length);
  for (let i = 0; i < payload.length; i += 1) {
    masked[i] = payload[i] ^ mask[i % 4];
  }
  return Buffer.concat([header, masked]);
}

function unmask(payload: Buffer, mask: Buffer): Buffer {
  const out = Buffer.alloc(payload.length);
  for (let i = 0; i < payload.length; i += 1) {
    out[i] = payload[i] ^ mask[i % 4];
  }
  return out;
}
