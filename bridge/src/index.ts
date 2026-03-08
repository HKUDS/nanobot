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
 *   BRIDGE_PORT=3001 BRIDGE_TOKEN=secret AUTH_DIR=~/.nanobot/whatsapp npm start
 */

// Polyfill crypto for Baileys in ESM
import { webcrypto } from 'crypto';
if (!globalThis.crypto) {
  (globalThis as any).crypto = webcrypto;
}

import { BridgeServer } from './server.js';
import { homedir } from 'os';
import { join } from 'path';

function resolveLoopbackHost(value: string | undefined): string {
  const raw = (value || '127.0.0.1').trim().toLowerCase();
  if (!raw || raw === 'localhost') return '127.0.0.1';
  if (raw === '::1') return raw;
  if (raw.startsWith('127.')) return raw;
  if (raw.startsWith('::ffff:127.')) return raw;
  throw new Error(`Invalid BRIDGE_HOST="${value}". Only loopback addresses are allowed.`);
}

const PORT = parseInt(process.env.BRIDGE_PORT || '3001', 10);
const HOST = resolveLoopbackHost(process.env.BRIDGE_HOST);
const AUTH_DIR = process.env.AUTH_DIR || join(homedir(), '.nanobot', 'whatsapp-auth');
const TOKEN = process.env.BRIDGE_TOKEN || '';

// Security: require authentication token
if (!TOKEN.trim()) {
  console.error('Error: BRIDGE_TOKEN environment variable is required for security.');
  console.error('Set a strong token and configure the Python client to use it.');
  process.exit(1);
}

console.log('🐈 nanobot WhatsApp Bridge');
console.log('========================\n');
console.log(`🔒 Listening on ws://${HOST}:${PORT} (token auth enabled)`);

const server = new BridgeServer(PORT, AUTH_DIR, TOKEN, HOST);

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
