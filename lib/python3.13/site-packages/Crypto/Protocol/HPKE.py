import struct
from enum import IntEnum

from types import ModuleType
from typing import Optional

from .KDF import _HKDF_extract, _HKDF_expand
from .DH import key_agreement, import_x25519_public_key, import_x448_public_key
from Crypto.Util.strxor import strxor
from Crypto.PublicKey import ECC
from Crypto.PublicKey.ECC import EccKey
from Crypto.Hash import SHA256, SHA384, SHA512
from Crypto.Cipher import AES, ChaCha20_Poly1305


class MODE(IntEnum):
    """HPKE modes"""
    BASE = 0x00
    PSK = 0x01
    AUTH = 0x02
    AUTH_PSK = 0x03


class AEAD(IntEnum):
    """Authenticated Encryption with Associated Data (AEAD) Functions"""
    AES128_GCM = 0x0001
    AES256_GCM = 0x0002
    CHACHA20_POLY1305 = 0x0003


class DeserializeError(ValueError):
    pass

class MessageLimitReachedError(ValueError):
    pass

# CURVE to (KEM ID, KDF ID, HASH)
_Curve_Config = {
  "NIST P-256": (0x0010, 0x0001, SHA256),
  "NIST P-384": (0x0011, 0x0002, SHA384),
  "NIST P-521": (0x0012, 0x0003, SHA512),
  "Curve25519": (0x0020, 0x0001, SHA256),
  "Curve448":   (0x0021, 0x0003, SHA512),
}


def _labeled_extract(salt: bytes,
                     label: bytes,
                     ikm: bytes,
                     suite_id: bytes,
                     hashmod: ModuleType):
    labeled_ikm = b"HPKE-v1" + suite_id + label + ikm
    return _HKDF_extract(salt, labeled_ikm, hashmod)


def _labeled_expand(prk: bytes,
                    label: bytes,
                    info: bytes,
                    L: int,
                    suite_id: bytes,
                    hashmod: ModuleType):
    labeled_info = struct.pack('>H', L) + b"HPKE-v1" + suite_id + \
                   label + info
    return _HKDF_expand(prk, labeled_info, L, hashmod)


def _extract_and_expand(dh: bytes,
                        kem_context: bytes,
                        suite_id: bytes,
                        hashmod: ModuleType):
    Nsecret = hashmod.digest_size

    eae_prk = _labeled_extract(b"",
                               b"eae_prk",
                               dh,
                               suite_id,
                               hashmod)

    shared_secret = _labeled_expand(eae_prk,
                                    b"shared_secret",
                                    kem_context,
                                    Nsecret,
                                    suite_id,
                                    hashmod)
    return shared_secret


class HPKE_Cipher:

    def __init__(self,
                 receiver_key: EccKey,
                 enc: Optional[bytes],
                 sender_key: Optional[EccKey],
                 psk_pair: tuple[bytes, bytes],
                 info: bytes,
                 aead_id: AEAD,
                 mode: MODE):

        self.enc: bytes = b'' if enc is None else enc
        """The encapsulated session key."""

        self._verify_psk_inputs(mode, psk_pair)

        self._curve = receiver_key.curve
        self._aead_id = aead_id
        self._mode = mode

        try:
            self._kem_id, \
             self._kdf_id, \
             self._hashmod = _Curve_Config[self._curve]
        except KeyError as ke:
            raise ValueError("Curve {} is not supported by HPKE".format(self._curve)) from ke

        self._Nk = 16 if self._aead_id == AEAD.AES128_GCM else 32
        self._Nn = 12
        self._Nt = 16
        self._Nh = self._hashmod.digest_size

        self._encrypt = not receiver_key.has_private()

        if self._encrypt:
            # SetupBaseS (encryption)
            if enc is not None:
                raise ValueError("Parameter 'enc' cannot be an input  when sealing")
            shared_secret, self.enc = self._encap(receiver_key,
                                                  self._kem_id,
                                                  self._hashmod,
                                                  sender_key)
        else:
            # SetupBaseR (decryption)
            if enc is None:
                raise ValueError("Parameter 'enc' required when unsealing")
            shared_secret = self._decap(enc,
                                        receiver_key,
                                        self._kem_id,
                                        self._hashmod,
                                        sender_key)

        self._sequence = 0
        self._max_sequence = (1 << (8 * self._Nn)) - 1

        self._key, \
            self._base_nonce, \
            self._export_secret = self._key_schedule(shared_secret,
                                                     info,
                                                     *psk_pair)

    @staticmethod
    def _encap(receiver_key: EccKey,
               kem_id: int,
               hashmod: ModuleType,
               sender_key: Optional[EccKey] = None,
               eph_key: Optional[EccKey] = None):

        assert (sender_key is None) or sender_key.has_private()
        assert (eph_key is None) or eph_key.has_private()

        if eph_key is None:
            eph_key = ECC.generate(curve=receiver_key.curve)
        enc = eph_key.public_key().export_key(format='raw')

        pkRm = receiver_key.public_key().export_key(format='raw')
        kem_context = enc + pkRm
        extra_param = {}
        if sender_key:
            kem_context += sender_key.public_key().export_key(format='raw')
            extra_param = {'static_priv': sender_key}

        suite_id = b"KEM" + struct.pack('>H', kem_id)

        def kdf(dh,
                kem_context=kem_context,
                suite_id=suite_id,
                hashmod=hashmod):
            return _extract_and_expand(dh, kem_context, suite_id, hashmod)

        shared_secret = key_agreement(eph_priv=eph_key,
                                      static_pub=receiver_key,
                                      kdf=kdf,
                                      **extra_param)
        return shared_secret, enc

    @staticmethod
    def _decap(enc: bytes,
               receiver_key: EccKey,
               kem_id: int,
               hashmod: ModuleType,
               sender_key: Optional[EccKey] = None):

        assert receiver_key.has_private()

        try:
            if receiver_key.curve == 'Curve25519':
                pkE = import_x25519_public_key(enc)
            elif receiver_key.curve == 'Curve448':
                pkE = import_x448_public_key(enc)
            else:
                pkE = ECC.import_key(enc, curve_name=receiver_key.curve)
        except ValueError as ve:
            raise DeserializeError("'enc' is not a valid encapsulated HPKE key") from ve

        pkRm = receiver_key.public_key().export_key(format='raw')
        kem_context = enc + pkRm
        extra_param = {}
        if sender_key:
            kem_context += sender_key.public_key().export_key(format='raw')
            extra_param = {'static_pub': sender_key}

        suite_id = b"KEM" + struct.pack('>H', kem_id)

        def kdf(dh,
                kem_context=kem_context,
                suite_id=suite_id,
                hashmod=hashmod):
            return _extract_and_expand(dh, kem_context, suite_id, hashmod)

        shared_secret = key_agreement(eph_pub=pkE,
                                      static_priv=receiver_key,
                                      kdf=kdf,
                                      **extra_param)
        return shared_secret

    @staticmethod
    def _verify_psk_inputs(mode: MODE, psk_pair: tuple[bytes, bytes]):
        psk_id, psk = psk_pair

        if (psk == b'') ^ (psk_id == b''):
            raise ValueError("Inconsistent PSK inputs")

        if (psk == b''):
            if mode in (MODE.PSK, MODE.AUTH_PSK):
                raise ValueError(f"PSK is required with mode {mode.name}")
        else:
            if len(psk) < 32:
                raise ValueError("PSK must be at least 32 byte long")
            if mode in (MODE.BASE, MODE.AUTH):
                raise ValueError("PSK is not compatible with this mode")

    def _key_schedule(self,
                      shared_secret: bytes,
                      info: bytes,
                      psk_id: bytes,
                      psk: bytes):

        suite_id = b"HPKE" + struct.pack('>HHH',
                                         self._kem_id,
                                         self._kdf_id,
                                         self._aead_id)

        psk_id_hash = _labeled_extract(b'',
                                       b'psk_id_hash',
                                       psk_id,
                                       suite_id,
                                       self._hashmod)

        info_hash = _labeled_extract(b'',
                                     b'info_hash',
                                     info,
                                     suite_id,
                                     self._hashmod)

        key_schedule_context = self._mode.to_bytes(1, 'big') + psk_id_hash + info_hash

        secret = _labeled_extract(shared_secret,
                                  b'secret',
                                  psk,
                                  suite_id,
                                  self._hashmod)

        key = _labeled_expand(secret,
                              b'key',
                              key_schedule_context,
                              self._Nk,
                              suite_id,
                              self._hashmod)

        base_nonce = _labeled_expand(secret,
                                     b'base_nonce',
                                     key_schedule_context,
                                     self._Nn,
                                     suite_id,
                                     self._hashmod)

        exporter_secret = _labeled_expand(secret,
                                          b'exp',
                                          key_schedule_context,
                                          self._Nh,
                                          suite_id,
                                          self._hashmod)

        return key, base_nonce, exporter_secret

    def _new_cipher(self):
        nonce = strxor(self._base_nonce, self._sequence.to_bytes(self._Nn, 'big'))
        if self._aead_id in (AEAD.AES128_GCM, AEAD.AES256_GCM):
            cipher = AES.new(self._key, AES.MODE_GCM, nonce=nonce, mac_len=self._Nt)
        elif self._aead_id == AEAD.CHACHA20_POLY1305:
            cipher = ChaCha20_Poly1305.new(key=self._key, nonce=nonce)
        else:
            raise ValueError(f"Unknown AEAD cipher ID {self._aead_id:#x}")
        if self._sequence >= self._max_sequence:
            raise MessageLimitReachedError()
        self._sequence += 1
        return cipher

    def seal(self, plaintext: bytes, auth_data: Optional[bytes] = None):
        """Encrypt and authenticate a message.

        This method can be invoked multiple times
        to seal an ordered sequence of messages.

        Arguments:
          plaintext: bytes
            The message to seal.
          auth_data: bytes
            Optional. Additional Authenticated data (AAD) that is not encrypted
            but that will be also covered by the authentication tag.

        Returns:
           The ciphertext concatenated with the authentication tag.
        """

        if not self._encrypt:
            raise ValueError("This cipher can only be used to seal")
        cipher = self._new_cipher()
        if auth_data:
            cipher.update(auth_data)
        ct, tag = cipher.encrypt_and_digest(plaintext)
        return ct + tag

    def unseal(self, ciphertext: bytes, auth_data: Optional[bytes] = None):
        """Decrypt a message and validate its authenticity.

        This method can be invoked multiple times
        to unseal an ordered sequence of messages.

        Arguments:
          cipertext: bytes
            The message to unseal.
          auth_data: bytes
            Optional. Additional Authenticated data (AAD) that
            was also covered by the authentication tag.

        Returns:
           The original plaintext.

        Raises: ValueError
           If the ciphertext (in combination with the AAD) is not valid.

           But if it is the first time you call ``unseal()`` this
           exception may also mean that any of the parameters or keys
           used to establish the session is wrong or that one is missing.
        """

        if self._encrypt:
            raise ValueError("This cipher can only be used to unseal")
        if len(ciphertext) < self._Nt:
            raise ValueError("Ciphertext is too small")
        cipher = self._new_cipher()
        if auth_data:
            cipher.update(auth_data)

        try:
            pt = cipher.decrypt_and_verify(ciphertext[:-self._Nt],
                                           ciphertext[-self._Nt:])
        except ValueError:
            if self._sequence == 1:
                raise ValueError("Incorrect HPKE keys/parameters or invalid message (wrong MAC tag)")
            raise ValueError("Invalid message (wrong MAC tag)")
        return pt


def new(*, receiver_key: EccKey,
        aead_id: AEAD,
        enc: Optional[bytes] = None,
        sender_key: Optional[EccKey] = None,
        psk: Optional[tuple[bytes, bytes]] = None,
        info: Optional[bytes] = None) -> HPKE_Cipher:
    """Create an HPKE context which can be used:

    - by the sender to seal (encrypt) a message or
    - by the receiver to unseal (decrypt) it.

    As a minimum, the two parties agree on the receiver's asymmetric key
    (of which the sender will only know the public half).

    Additionally, for authentication purposes, they may also agree on:

    * the sender's asymmetric key (of which the receiver will only know the public half)

    * a shared secret (e.g., a symmetric key derived from a password)

    Args:
      receiver_key:
        The ECC key of the receiver.
        It must be on one of the following curves: ``NIST P-256``,
        ``NIST P-384``, ``NIST P-521``, ``X25519`` or ``X448``.

        If this is a **public** key, the HPKE context can only be used to
        **seal** (**encrypt**).

        If this is a **private** key, the HPKE context can only be used to
        **unseal** (**decrypt**).

      aead_id:
        The HPKE identifier of the symmetric cipher.
        The possible values are:

        * ``HPKE.AEAD.AES128_GCM``
        * ``HPKE.AEAD.AES256_GCM``
        * ``HPKE.AEAD.CHACHA20_POLY1305``

      enc:
        The encapsulated session key (i.e., the KEM shared secret).

        The receiver must always specify this parameter.

        The sender must always omit this parameter.

      sender_key:
        The ECC key of the sender.
        It must be on the same curve as the ``receiver_key``.
        If the ``receiver_key`` is a public key, ``sender_key`` must be a
        private key, and vice versa.

      psk:
        A Pre-Shared Key (PSK) as a 2-tuple of non-empty
        byte strings: the identifier and the actual secret value.
        Sender and receiver must use the same PSK (or none).

        The secret value must be at least 32 bytes long,
        but it  must not be a low-entropy password
        (use a KDF like PBKDF2 or scrypt to derive a secret
        from a password).

      info:
        A non-secret parameter that contributes
        to the generation of all session keys.
        Sender and receive must use the same **info** parameter (or none).

    Returns:
        An object that can be used for
        sealing (if ``receiver_key`` is a public key) or
        unsealing (if ``receiver_key`` is a private key).
        In the latter case,
        correctness of all the keys and parameters will only
        be assessed with the first call to ``unseal()``.
    """

    if aead_id not in AEAD:
        raise ValueError(f"Unknown AEAD cipher ID {aead_id:#x}")

    curve = receiver_key.curve
    if curve not in ('NIST P-256', 'NIST P-384', 'NIST P-521',
                     'Curve25519', 'Curve448'):
        raise ValueError(f"Unsupported curve {curve}")

    if sender_key:
        count_private_keys = int(receiver_key.has_private()) + \
                             int(sender_key.has_private())
        if count_private_keys != 1:
            raise ValueError("Exactly 1 private key required")
        if sender_key.curve != curve:
            raise ValueError("Sender key uses {} but recipient key {}".
                             format(sender_key.curve, curve))
        mode = MODE.AUTH if psk is None else MODE.AUTH_PSK
    else:
        mode = MODE.BASE if psk is None else MODE.PSK

    if psk is None:
        psk = b'', b''

    if info is None:
        info = b''

    return HPKE_Cipher(receiver_key,
                       enc,
                       sender_key,
                       psk,
                       info,
                       aead_id,
                       mode)
