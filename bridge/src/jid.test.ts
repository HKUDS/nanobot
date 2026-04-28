import { describe, it } from 'node:test';
import assert from 'node:assert/strict';

import {
  extractMentionedJids,
  isGroupMessage,
  isSelfMentioned,
  normalizeJid,
} from './jid.js';

describe('normalizeJid', () => {
  it('strips the device segment before an @lid server', () => {
    assert.equal(normalizeJid('123456789012345:1@lid'), '123456789012345@lid');
  });

  it('strips multi-digit device segments', () => {
    assert.equal(normalizeJid('123456789012345:42@lid'), '123456789012345@lid');
  });

  it('leaves a JID without a device segment unchanged', () => {
    assert.equal(normalizeJid('123456789012345@lid'), '123456789012345@lid');
  });

  it('handles phone-number JIDs (@s.whatsapp.net) the same way', () => {
    assert.equal(
      normalizeJid('8937465992:2@s.whatsapp.net'),
      '8937465992@s.whatsapp.net',
    );
    assert.equal(
      normalizeJid('8937465992@s.whatsapp.net'),
      '8937465992@s.whatsapp.net',
    );
  });

  it('returns "" for null, undefined, or empty input', () => {
    assert.equal(normalizeJid(null), '');
    assert.equal(normalizeJid(undefined), '');
    assert.equal(normalizeJid(''), '');
  });

  it('does not strip a colon that is not followed by digits and @', () => {
    // Defensive: only the ":<device>@" pattern should be stripped.
    assert.equal(normalizeJid('weird:value'), 'weird:value');
  });
});

describe('isSelfMentioned', () => {
  it('matches a device-qualified self JID against a deviceless mention', () => {
    // The exact bug: sock.user.lid has :1, the mention does not.
    assert.equal(
      isSelfMentioned(['123456789012345@lid'], ['123456789012345:1@lid']),
      true,
    );
  });

  it('matches when both sides carry different device numbers', () => {
    assert.equal(
      isSelfMentioned(['123456789012345:3@lid'], ['123456789012345:1@lid']),
      true,
    );
  });

  it('returns false when no mention targets the bot', () => {
    assert.equal(
      isSelfMentioned(['999@lid', '111@s.whatsapp.net'], ['123456789012345:1@lid']),
      false,
    );
  });

  it('returns false for an empty mention list', () => {
    assert.equal(isSelfMentioned([], ['123456789012345:1@lid']), false);
  });

  it('returns false when no self JIDs are known', () => {
    assert.equal(isSelfMentioned(['123456789012345@lid'], []), false);
    assert.equal(
      isSelfMentioned(['123456789012345@lid'], [null, undefined, '']),
      false,
    );
  });

  it('does not match across different servers (@lid vs @s.whatsapp.net)', () => {
    assert.equal(
      isSelfMentioned(
        ['123456789012345@s.whatsapp.net'],
        ['123456789012345:1@lid'],
      ),
      false,
    );
  });

  it('ignores null/undefined entries in either list', () => {
    assert.equal(
      isSelfMentioned(
        [null, undefined, '123456789012345@lid'],
        [undefined, '123456789012345:1@lid'],
      ),
      true,
    );
  });
});

describe('isGroupMessage', () => {
  it('is true for remoteJid ending in @g.us', () => {
    assert.equal(isGroupMessage({ key: { remoteJid: '123-456@g.us' } }), true);
  });

  it('is false for 1:1 chats', () => {
    assert.equal(
      isGroupMessage({ key: { remoteJid: '8937465992@s.whatsapp.net' } }),
      false,
    );
  });

  it('is false when key or remoteJid is missing', () => {
    assert.equal(isGroupMessage({}), false);
    assert.equal(isGroupMessage({ key: {} }), false);
    assert.equal(isGroupMessage(null), false);
    assert.equal(isGroupMessage(undefined), false);
  });
});

describe('extractMentionedJids', () => {
  it('returns [] when the message has no contextInfo', () => {
    assert.deepEqual(extractMentionedJids({ message: {} }), []);
    assert.deepEqual(extractMentionedJids({}), []);
    assert.deepEqual(extractMentionedJids(null), []);
  });

  it('extracts mentions from an extended text message', () => {
    const msg = {
      message: {
        extendedTextMessage: {
          contextInfo: { mentionedJid: ['a@lid', 'b@lid'] },
        },
      },
    };
    assert.deepEqual(extractMentionedJids(msg), ['a@lid', 'b@lid']);
  });

  it('concatenates mentions across image/video/document/audio messages', () => {
    const msg = {
      message: {
        imageMessage: { contextInfo: { mentionedJid: ['img@lid'] } },
        videoMessage: { contextInfo: { mentionedJid: ['vid@lid'] } },
        documentMessage: { contextInfo: { mentionedJid: ['doc@lid'] } },
        audioMessage: { contextInfo: { mentionedJid: ['aud@lid'] } },
      },
    };
    assert.deepEqual(extractMentionedJids(msg), [
      'img@lid',
      'vid@lid',
      'doc@lid',
      'aud@lid',
    ]);
  });

  it('ignores non-array mentionedJid values', () => {
    const msg = {
      message: {
        extendedTextMessage: {
          contextInfo: { mentionedJid: 'not-an-array' },
        },
      },
    };
    assert.deepEqual(extractMentionedJids(msg), []);
  });
});
