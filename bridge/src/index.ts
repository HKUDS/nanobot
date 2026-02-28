#!/usr/bin/env node
/**
 * nanobot WhatsApp Bridge
 * 
 * This bridge connects WhatsApp Web to nanobot's Python backend
 * via WebSocket. It handles authentication, message forwarding,
 * and reconnection logic.
 * 
 * Usage:
 *   npm run build && npm start
 *   
 * Or with custom settings:
 *   BRIDGE_PORT=3001 AUTH_DIR=~/.nanobot/whatsapp npm start
 */

// Polyfill crypto for Baileys in ESM
import { webcrypto } from 'crypto';
if (!globalThis.crypto) {
  (globalThis as any).crypto = webcrypto;
}

import { BridgeServer } from './server.js';
import { homedir } from 'os';
import { join } from 'path';
import { readFileSync, unlinkSync, existsSync } from 'fs';

const PORT = parseInt(process.env.BRIDGE_PORT || '3001', 10);
const AUTH_DIR = process.env.AUTH_DIR || join(homedir(), '.nanobot', 'whatsapp-auth');

// Prefer BRIDGE_TOKEN_FILE (a 0600 temp file written by the Python side) over the
// legacy BRIDGE_TOKEN env var to avoid token exposure in process listings.
function readToken(): string | undefined {
  const tokenFile = process.env.BRIDGE_TOKEN_FILE;
  if (tokenFile && existsSync(tokenFile)) {
    try {
      const token = readFileSync(tokenFile, 'utf-8').trim();
      unlinkSync(tokenFile); // delete immediately after reading
      return token || undefined;
    } catch {
      console.warn('Warning: could not read BRIDGE_TOKEN_FILE, falling back to env var');
    }
  }
  return process.env.BRIDGE_TOKEN || undefined;
}

const TOKEN = readToken();

console.log('🐈 nanobot WhatsApp Bridge');
console.log('========================\n');

const server = new BridgeServer(PORT, AUTH_DIR, TOKEN);

// Handle graceful shutdown
process.on('SIGINT', async () => {
  console.log('\n\nShutting down...');
  await server.stop();
  process.exit(0);
});

process.on('SIGTERM', async () => {
  await server.stop();
  process.exit(0);
});

// Start the server
server.start().catch((error) => {
  console.error('Failed to start bridge:', error);
  process.exit(1);
});
