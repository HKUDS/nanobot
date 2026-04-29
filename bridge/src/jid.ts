/**
 * Helpers for WhatsApp JIDs (Jabber IDs used by Baileys).
 *
 * A JID may include a device segment between the user id and the server
 * (e.g. "12345:1@lid"). For mention matching we compare the user+server
 * pair and ignore the device.
 */

/* eslint-disable @typescript-eslint/no-explicit-any */

/**
 * Strip the device segment (":<n>") from a JID while preserving the
 * "@server" suffix. Returns "" for null/undefined/empty input.
 *
 *   "12345:1@lid"            -> "12345@lid"
 *   "12345@lid"              -> "12345@lid"
 *   "555:2@s.whatsapp.net"   -> "555@s.whatsapp.net"
 */
export function normalizeJid(jid: string | undefined | null): string {
  return (jid || '').replace(/:\d+@/, '@');
}

/**
 * Return true if any JID in `mentioned` identifies one of the `selfJids`
 * (device-agnostic). Used to detect whether the bot was @-mentioned in a
 * group message.
 */
export function isSelfMentioned(
  mentioned: Array<string | undefined | null>,
  selfJids: Array<string | undefined | null>,
): boolean {
  const normalizedSelf = new Set(selfJids.map(normalizeJid).filter(Boolean));
  if (normalizedSelf.size === 0) return false;
  return mentioned.some((jid) => normalizedSelf.has(normalizeJid(jid)));
}

/**
 * Extract the list of mentioned JIDs from a Baileys message across the
 * message types that can carry a contextInfo.mentionedJid array.
 */
export function extractMentionedJids(msg: any): string[] {
  const candidates = [
    msg?.message?.extendedTextMessage?.contextInfo?.mentionedJid,
    msg?.message?.imageMessage?.contextInfo?.mentionedJid,
    msg?.message?.videoMessage?.contextInfo?.mentionedJid,
    msg?.message?.documentMessage?.contextInfo?.mentionedJid,
    msg?.message?.audioMessage?.contextInfo?.mentionedJid,
  ];
  return candidates.flatMap((items) => (Array.isArray(items) ? items : []));
}

/**
 * Whether a Baileys message represents a message in a group chat.
 */
export function isGroupMessage(msg: any): boolean {
  return !!msg?.key?.remoteJid?.endsWith?.('@g.us');
}
