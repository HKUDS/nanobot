import struct
from collections import deque

from types import ModuleType
from typing import Union

from Crypto.Util.strxor import strxor


def W(cipher: ModuleType,
      plaintext: Union[bytes, bytearray]) -> bytes:

    S = [plaintext[i:i+8] for i in range(0, len(plaintext), 8)]
    n = len(S)
    s = 6 * (n - 1)
    A = S[0]
    R = deque(S[1:])

    for t in range(1, s + 1):
        t_64 = struct.pack('>Q', t)
        ct = cipher.encrypt(A + R.popleft())
        A = strxor(ct[:8], t_64)
        R.append(ct[8:])

    return A + b''.join(R)


def W_inverse(cipher: ModuleType,
              ciphertext: Union[bytes, bytearray]) -> bytes:

    C = [ciphertext[i:i+8] for i in range(0, len(ciphertext), 8)]
    n = len(C)
    s = 6 * (n - 1)
    A = C[0]
    R = deque(C[1:])

    for t in range(s, 0, -1):
        t_64 = struct.pack('>Q', t)
        pt = cipher.decrypt(strxor(A, t_64) + R.pop())
        A = pt[:8]
        R.appendleft(pt[8:])

    return A + b''.join(R)


class KWMode(object):
    """Key Wrap (KW) mode.

    This is a deterministic Authenticated Encryption (AE) mode
    for protecting cryptographic keys. See `NIST SP800-38F`_.

    It provides both confidentiality and authenticity, and it designed
    so that any bit of the ciphertext depends on all bits of the plaintext.

    This mode is only available for ciphers that operate on 128 bits blocks
    (e.g., AES).

    .. _`NIST SP800-38F`: http://csrc.nist.gov/publications/nistpubs/800-38F/SP-800-38F.pdf

    :undocumented: __init__
    """

    def __init__(self,
                 factory: ModuleType,
                 key: Union[bytes, bytearray]):

        self.block_size = factory.block_size
        if self.block_size != 16:
            raise ValueError("Key Wrap mode is only available for ciphers"
                             " that operate on 128 bits blocks")

        self._factory = factory
        self._cipher = factory.new(key, factory.MODE_ECB)
        self._done = False

    def seal(self, plaintext: Union[bytes, bytearray]) -> bytes:
        """Encrypt and authenticate (wrap) a cryptographic key.

        Args:
          plaintext:
            The cryptographic key to wrap.
            It must be at least 16 bytes long, and its length
            must be a multiple of 8.

        Returns:
            The wrapped key.
        """

        if self._done:
            raise ValueError("The cipher cannot be used more than once")

        if len(plaintext) % 8:
            raise ValueError("The plaintext must have length multiple of 8 bytes")

        if len(plaintext) < 16:
            raise ValueError("The plaintext must be at least 16 bytes long")

        if len(plaintext) >= 2**32:
            raise ValueError("The plaintext is too long")

        res = W(self._cipher, b'\xA6\xA6\xA6\xA6\xA6\xA6\xA6\xA6' + plaintext)
        self._done = True
        return res

    def unseal(self, ciphertext: Union[bytes, bytearray]) -> bytes:
        """Decrypt and authenticate (unwrap) a cryptographic key.

        Args:
          ciphertext:
            The cryptographic key to unwrap.
            It must be at least 24 bytes long, and its length
            must be a multiple of 8.

        Returns:
            The original key.

        Raises: ValueError
           If the ciphertext or the key are not valid.
        """

        if self._done:
            raise ValueError("The cipher cannot be used more than once")

        if len(ciphertext) % 8:
            raise ValueError("The ciphertext must have length multiple of 8 bytes")

        if len(ciphertext) < 24:
            raise ValueError("The ciphertext must be at least 24 bytes long")

        pt = W_inverse(self._cipher, ciphertext)

        if pt[:8] != b'\xA6\xA6\xA6\xA6\xA6\xA6\xA6\xA6':
            raise ValueError("Incorrect integrity check value")
        self._done = True

        return pt[8:]


def _create_kw_cipher(factory: ModuleType,
                      **kwargs: Union[bytes, bytearray]) -> KWMode:
    """Create a new block cipher in Key Wrap mode.

    Args:
      factory:
        A block cipher module, taken from `Crypto.Cipher`.
        The cipher must have block length of 16 bytes, such as AES.

    Keywords:
      key:
        The secret key to use to seal or unseal.
    """

    try:
        key = kwargs["key"]
    except KeyError as e:
        raise TypeError("Missing parameter:" + str(e))

    return KWMode(factory, key)
