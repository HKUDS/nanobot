import struct

from types import ModuleType
from typing import Union

from ._mode_kw import W, W_inverse


class KWPMode(object):
    """Key Wrap with Padding (KWP) mode.

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
            raise ValueError("Key Wrap with Padding mode is only available for ciphers"
                             " that operate on 128 bits blocks")

        self._factory = factory
        self._cipher = factory.new(key, factory.MODE_ECB)
        self._done = False

    def seal(self, plaintext: Union[bytes, bytearray]) -> bytes:
        """Encrypt and authenticate (wrap) a cryptographic key.

        Args:
          plaintext:
            The cryptographic key to wrap.

        Returns:
            The wrapped key.
        """

        if self._done:
            raise ValueError("The cipher cannot be used more than once")

        if len(plaintext) == 0:
            raise ValueError("The plaintext must be at least 1 byte")

        if len(plaintext) >= 2 ** 32:
            raise ValueError("The plaintext is too long")

        padlen = (8 - len(plaintext)) % 8
        padded = plaintext + b'\x00' * padlen

        AIV = b'\xA6\x59\x59\xA6' + struct.pack('>I', len(plaintext))

        if len(padded) == 8:
            res = self._cipher.encrypt(AIV + padded)
        else:
            res = W(self._cipher, AIV + padded)

        return res

    def unseal(self, ciphertext: Union[bytes, bytearray]) -> bytes:
        """Decrypt and authenticate (unwrap) a cryptographic key.

        Args:
          ciphertext:
            The cryptographic key to unwrap.
            It must be at least 16 bytes long, and its length
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

        if len(ciphertext) < 16:
            raise ValueError("The ciphertext must be at least 24 bytes long")

        if len(ciphertext) == 16:
            S = self._cipher.decrypt(ciphertext)
        else:
            S = W_inverse(self._cipher, ciphertext)

        if S[:4] != b'\xA6\x59\x59\xA6':
            raise ValueError("Incorrect decryption")

        Plen = struct.unpack('>I', S[4:8])[0]

        padlen = len(S) - 8 - Plen
        if padlen < 0 or padlen > 7:
            raise ValueError("Incorrect decryption")

        if S[len(S) - padlen:] != b'\x00' * padlen:
            raise ValueError("Incorrect decryption")

        return S[8:len(S) - padlen]


def _create_kwp_cipher(factory: ModuleType,
                       **kwargs: Union[bytes, bytearray]) -> KWPMode:
    """Create a new block cipher in Key Wrap with Padding mode.

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

    return KWPMode(factory, key)
