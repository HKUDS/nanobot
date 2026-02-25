import base64
import hashlib
from typing import Union

from Crypto.Cipher import AES

from ..const import UTF_8


class AESCipher(object):
    def __init__(self, key: Union[str, bytes]) -> None:
        if isinstance(key, str):
            key = key.encode(UTF_8)
        self.digest = hashlib.sha256(key).digest()

    def decrypt(self, enc: bytes) -> bytes:
        iv = enc[: AES.block_size]
        cipher = AES.new(self.digest, AES.MODE_CBC, iv)
        s = cipher.decrypt(enc[AES.block_size:])
        return s[: -ord(s[len(s) - 1:])]

    def decrypt_str(self, enc: str) -> str:
        enc = base64.b64decode(enc)
        return self.decrypt(enc).decode(UTF_8)
