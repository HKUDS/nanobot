"""WeChat Work (企业微信) message encryption/decryption.

Uses AES-CBC with PKCS7 padding, ported from sillymd-openclaw-wechat-plugin.
"""

import base64
import hashlib
import struct

from Crypto.Cipher import AES


class WeChatCrypto:
    """Encrypt / decrypt WeChat Work callback messages."""

    def __init__(self, token: str, encoding_aes_key: str, corp_id: str):
        self.token = token
        self.corp_id = corp_id
        self.aes_key = base64.b64decode(encoding_aes_key + "=")

    # ── public API ───────────────────────────────────────────────────────

    def decrypt_msg(self, signature: str, timestamp: str, nonce: str, msg_encrypt: str) -> str:
        """Verify signature and decrypt an incoming message."""
        if not self._verify_signature(signature, timestamp, nonce, msg_encrypt):
            raise ValueError("Invalid signature")
        return self._decrypt(msg_encrypt)

    # ── internal helpers ─────────────────────────────────────────────────

    def _verify_signature(self, signature: str, timestamp: str, nonce: str, msg_encrypt: str) -> bool:
        parts = sorted([self.token, timestamp, nonce, msg_encrypt])
        digest = hashlib.sha1("".join(parts).encode()).hexdigest()
        return signature == digest

    def _decrypt(self, msg_encrypt: str) -> str:
        encrypted = base64.b64decode(msg_encrypt)
        cipher = AES.new(self.aes_key, AES.MODE_CBC, self.aes_key[:16])
        decrypted = cipher.decrypt(encrypted)
        # Remove PKCS7 padding
        decrypted = decrypted[: -decrypted[-1]]
        # Layout: random(16B) + msg_len(4B big-endian) + msg + corp_id
        msg_len = struct.unpack(">I", decrypted[16:20])[0]
        return decrypted[20 : 20 + msg_len].decode("utf-8")
