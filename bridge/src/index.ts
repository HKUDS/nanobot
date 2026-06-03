#!/usr/bin/env node
/**
 * blackcat WhatsApp Bridge
 * 
 * This bridge connects WhatsApp Web to blackcat's Python backend
 * via WebSocket. It handles authentication, message forwarding,
 * and reconnection logic.
 * 
 * Usage:
 *   npm run build && npm start
 *   
 * Or with custom settings:
 *   BRIDGE_PORT=3001 AUTH_DIR=~/.blackcat/whatsapp npm start
 */

// Polyfill crypto for Baileys in ESM
import { webcrypto } from 'crypto';
if (!globalThis.crypto) {
  (globalThis as any).crypto = webcrypto;
}

import { homedir } from 'os';
import { join } from 'path';
import { BridgeServer } from './server.js';

const PORT = parseInt(process.env.BRIDGE_PORT || '3001', 10);
const AUTH_DIR = process.env.AUTH_DIR || join(homedir(), '.blackcat', 'whatsapp-auth');
const TOKEN = process.env.BRIDGE_TOKEN?.trim();

if (!TOKEN) {
  console.error('BRIDGE_TOKEN is required. Start the bridge via blackcat so it can provision a local secret automatically.');
  process.exit(1);
}

console.log('🐈 blackcat WhatsApp Bridge');
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
