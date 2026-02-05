#!/usr/bin/env python
#
# A library that provides a Python interface to the Telegram Bot API
# Copyright (C) 2015-2026
# Leandro Toledo de Souza <devs@python-telegram-bot.org>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Lesser Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Lesser Public License for more details.
#
# You should have received a copy of the GNU Lesser Public License
# along with this program.  If not, see [http://www.gnu.org/licenses/].
# pylint: disable=missing-module-docstring,  redefined-builtin
import json
from base64 import b64decode
from collections.abc import Sequence
from typing import TYPE_CHECKING, no_type_check

try:
    from cryptography.hazmat.backends import default_backend
    from cryptography.hazmat.primitives.asymmetric.padding import MGF1, OAEP
    from cryptography.hazmat.primitives.ciphers import Cipher
    from cryptography.hazmat.primitives.ciphers.algorithms import AES
    from cryptography.hazmat.primitives.ciphers.modes import CBC
    from cryptography.hazmat.primitives.hashes import SHA1, SHA256, SHA512, Hash

    CRYPTO_INSTALLED = True
except ImportError:
    default_backend = None  # type: ignore[assignment]
    MGF1, OAEP, Cipher, AES, CBC = (None, None, None, None, None)  # type: ignore[misc,assignment]
    SHA1, SHA256, SHA512, Hash = (None, None, None, None)  # type: ignore[misc,assignment]

    CRYPTO_INSTALLED = False

from telegram._telegramobject import TelegramObject
from telegram._utils.argumentparsing import de_json_optional, de_list_optional, parse_sequence_arg
from telegram._utils.strings import TextEncoding
from telegram._utils.types import JSONDict
from telegram.error import PassportDecryptionError

if TYPE_CHECKING:
    from telegram import Bot


@no_type_check
def decrypt(secret, hash, data):
    """
    Decrypt per telegram docs at https://core.telegram.org/passport.

    Args:
        secret (:obj:`str` or :obj:`bytes`): The encryption secret, either as bytes or as a
            base64 encoded string.
        hash (:obj:`str` or :obj:`bytes`): The hash, either as bytes or as a
            base64 encoded string.
        data (:obj:`str` or :obj:`bytes`): The data to decrypt, either as bytes or as a
            base64 encoded string.
        file (:obj:`bool`): Force data to be treated as raw data, instead of trying to
            b64decode it.

    Raises:
        :class:`PassportDecryptionError`: Given hash does not match hash of decrypted data.

    Returns:
        :obj:`bytes`: The decrypted data as bytes.

    """
    if not CRYPTO_INSTALLED:
        raise RuntimeError(
            "To use Telegram Passports, PTB must be installed via `pip install "
            '"python-telegram-bot[passport]"`.'
        )
    # Make a SHA512 hash of secret + update
    digest = Hash(SHA512(), backend=default_backend())
    digest.update(secret + hash)
    secret_hash_hash = digest.finalize()
    # First 32 chars is our key, next 16 is the initialisation vector
    key, init_vector = secret_hash_hash[:32], secret_hash_hash[32 : 32 + 16]
    # Init a AES-CBC cipher and decrypt the data
    cipher = Cipher(AES(key), CBC(init_vector), backend=default_backend())
    decryptor = cipher.decryptor()
    data = decryptor.update(data) + decryptor.finalize()
    # Calculate SHA256 hash of the decrypted data
    digest = Hash(SHA256(), backend=default_backend())
    digest.update(data)
    data_hash = digest.finalize()
    # If the newly calculated hash did not match the one telegram gave us
    if data_hash != hash:
        # Raise a error that is caught inside telegram.PassportData and transformed into a warning
        raise PassportDecryptionError(f"Hashes are not equal! {data_hash} != {hash}")
    # Return data without padding
    return data[data[0] :]


@no_type_check
def decrypt_json(secret, hash, data):
    """Decrypts data using secret and hash and then decodes utf-8 string and loads json"""
    return json.loads(decrypt(secret, hash, data).decode(TextEncoding.UTF_8))


class EncryptedCredentials(TelegramObject):
    """Contains data required for decrypting and authenticating EncryptedPassportElement. See the
    Telegram Passport Documentation for a complete description of the data decryption and
    authentication processes.

    Objects of this class are comparable in terms of equality. Two objects of this class are
    considered equal, if their :attr:`data`, :attr:`hash` and :attr:`secret` are equal.

    Note:
        This object is decrypted only when originating from
        :attr:`telegram.PassportData.decrypted_credentials`.

    Args:
        data (:class:`telegram.Credentials` | :obj:`str`): Decrypted data with unique user's
            nonce, data hashes and secrets used for EncryptedPassportElement decryption and
            authentication or base64 encrypted data.
        hash (:obj:`str`): Base64-encoded data hash for data authentication.
        secret (:obj:`str`): Decrypted or encrypted secret used for decryption.

    Attributes:
        data (:class:`telegram.Credentials` | :obj:`str`): Decrypted data with unique user's
            nonce, data hashes and secrets used for EncryptedPassportElement decryption and
            authentication or base64 encrypted data.
        hash (:obj:`str`): Base64-encoded data hash for data authentication.
        secret (:obj:`str`): Decrypted or encrypted secret used for decryption.

    """

    __slots__ = (
        "_decrypted_data",
        "_decrypted_secret",
        "data",
        "hash",
        "secret",
    )

    def __init__(
        self,
        data: str,
        hash: str,
        secret: str,
        *,
        api_kwargs: JSONDict | None = None,
    ):
        super().__init__(api_kwargs=api_kwargs)
        # Required
        self.data: str = data
        self.hash: str = hash
        self.secret: str = secret

        self._id_attrs = (self.data, self.hash, self.secret)

        self._decrypted_secret: bytes | None = None
        self._decrypted_data: Credentials | None = None

        self._freeze()

    @property
    def decrypted_secret(self) -> bytes:
        """
        :obj:`bytes`: Lazily decrypt and return secret.

        Raises:
            telegram.error.PassportDecryptionError: Decryption failed. Usually due to bad
                private/public key but can also suggest malformed/tampered data.
        """
        if self._decrypted_secret is None:
            if not CRYPTO_INSTALLED:
                raise RuntimeError(
                    "To use Telegram Passports, PTB must be installed via `pip install "
                    '"python-telegram-bot[passport]"`.'
                )
            # Try decrypting according to step 1 at
            # https://core.telegram.org/passport#decrypting-data
            # We make sure to base64 decode the secret first.
            # Telegram says to use OAEP padding so we do that. The Mask Generation Function
            # is the default for OAEP, the algorithm is the default for PHP which is what
            # Telegram's backend servers run.
            try:
                self._decrypted_secret = self.get_bot().private_key.decrypt(  # type: ignore
                    b64decode(self.secret),
                    OAEP(mgf=MGF1(algorithm=SHA1()), algorithm=SHA1(), label=None),  # skipcq
                )
            except ValueError as exception:
                # If decryption fails raise exception
                raise PassportDecryptionError(exception) from exception
        return self._decrypted_secret

    @property
    def decrypted_data(self) -> "Credentials":
        """
        :class:`telegram.Credentials`: Lazily decrypt and return credentials data. This object
            also contains the user specified nonce as
            `decrypted_data.nonce`.

        Raises:
            telegram.error.PassportDecryptionError: Decryption failed. Usually due to bad
                private/public key but can also suggest malformed/tampered data.
        """
        if self._decrypted_data is None:
            self._decrypted_data = Credentials.de_json(
                decrypt_json(self.decrypted_secret, b64decode(self.hash), b64decode(self.data)),
                self.get_bot(),
            )
        return self._decrypted_data


class Credentials(TelegramObject):
    """
    Attributes:
        secure_data (:class:`telegram.SecureData`): Credentials for encrypted data
        nonce (:obj:`str`): Bot-specified nonce
    """

    __slots__ = ("nonce", "secure_data")

    def __init__(
        self,
        secure_data: "SecureData",
        nonce: str,
        *,
        api_kwargs: JSONDict | None = None,
    ):
        super().__init__(api_kwargs=api_kwargs)
        # Required
        self.secure_data: SecureData = secure_data
        self.nonce: str = nonce

        self._freeze()

    @classmethod
    def de_json(cls, data: JSONDict, bot: "Bot | None" = None) -> "Credentials":
        """See :meth:`telegram.TelegramObject.de_json`."""
        data = cls._parse_data(data)

        data["secure_data"] = de_json_optional(data.get("secure_data"), SecureData, bot)

        return super().de_json(data=data, bot=bot)


class SecureData(TelegramObject):
    """
    This object represents the credentials that were used to decrypt the encrypted data.
    All fields are optional and depend on fields that were requested.

    Args:
        personal_details (:class:`telegram.SecureValue`, optional): Credentials for encrypted
            personal details.
        passport (:class:`telegram.SecureValue`, optional): Credentials for encrypted passport.
        internal_passport (:class:`telegram.SecureValue`, optional): Credentials for encrypted
            internal passport.
        driver_license (:class:`telegram.SecureValue`, optional): Credentials for encrypted
            driver license.
        identity_card (:class:`telegram.SecureValue`, optional): Credentials for encrypted ID card
        address (:class:`telegram.SecureValue`, optional): Credentials for encrypted
            residential address.
        utility_bill (:class:`telegram.SecureValue`, optional): Credentials for encrypted
            utility bill.
        bank_statement (:class:`telegram.SecureValue`, optional): Credentials for encrypted
            bank statement.
        rental_agreement (:class:`telegram.SecureValue`, optional): Credentials for encrypted
            rental agreement.
        passport_registration (:class:`telegram.SecureValue`, optional): Credentials for encrypted
            registration from internal passport.
        temporary_registration (:class:`telegram.SecureValue`, optional): Credentials for encrypted
            temporary registration.

    Attributes:
        personal_details (:class:`telegram.SecureValue`): Optional. Credentials for encrypted
            personal details.
        passport (:class:`telegram.SecureValue`): Optional. Credentials for encrypted passport.
        internal_passport (:class:`telegram.SecureValue`): Optional. Credentials for encrypted
            internal passport.
        driver_license (:class:`telegram.SecureValue`): Optional. Credentials for encrypted
            driver license.
        identity_card (:class:`telegram.SecureValue`): Optional. Credentials for encrypted ID card
        address (:class:`telegram.SecureValue`): Optional. Credentials for encrypted
            residential address.
        utility_bill (:class:`telegram.SecureValue`): Optional. Credentials for encrypted
            utility bill.
        bank_statement (:class:`telegram.SecureValue`): Optional. Credentials for encrypted
            bank statement.
        rental_agreement (:class:`telegram.SecureValue`): Optional. Credentials for encrypted
            rental agreement.
        passport_registration (:class:`telegram.SecureValue`): Optional. Credentials for encrypted
            registration from internal passport.
        temporary_registration (:class:`telegram.SecureValue`): Optional. Credentials for encrypted
            temporary registration.
    """

    __slots__ = (
        "address",
        "bank_statement",
        "driver_license",
        "identity_card",
        "internal_passport",
        "passport",
        "passport_registration",
        "personal_details",
        "rental_agreement",
        "temporary_registration",
        "utility_bill",
    )

    def __init__(
        self,
        personal_details: "SecureValue | None" = None,
        passport: "SecureValue | None" = None,
        internal_passport: "SecureValue | None" = None,
        driver_license: "SecureValue | None" = None,
        identity_card: "SecureValue | None" = None,
        address: "SecureValue | None" = None,
        utility_bill: "SecureValue | None" = None,
        bank_statement: "SecureValue | None" = None,
        rental_agreement: "SecureValue | None" = None,
        passport_registration: "SecureValue | None" = None,
        temporary_registration: "SecureValue | None" = None,
        *,
        api_kwargs: JSONDict | None = None,
    ):
        super().__init__(api_kwargs=api_kwargs)

        # Optionals
        self.temporary_registration: SecureValue | None = temporary_registration
        self.passport_registration: SecureValue | None = passport_registration
        self.rental_agreement: SecureValue | None = rental_agreement
        self.bank_statement: SecureValue | None = bank_statement
        self.utility_bill: SecureValue | None = utility_bill
        self.address: SecureValue | None = address
        self.identity_card: SecureValue | None = identity_card
        self.driver_license: SecureValue | None = driver_license
        self.internal_passport: SecureValue | None = internal_passport
        self.passport: SecureValue | None = passport
        self.personal_details: SecureValue | None = personal_details

        self._freeze()

    @classmethod
    def de_json(cls, data: JSONDict, bot: "Bot | None" = None) -> "SecureData":
        """See :meth:`telegram.TelegramObject.de_json`."""
        data = cls._parse_data(data)

        data["temporary_registration"] = de_json_optional(
            data.get("temporary_registration"), SecureValue, bot
        )
        data["passport_registration"] = de_json_optional(
            data.get("passport_registration"), SecureValue, bot
        )
        data["rental_agreement"] = de_json_optional(data.get("rental_agreement"), SecureValue, bot)
        data["bank_statement"] = de_json_optional(data.get("bank_statement"), SecureValue, bot)
        data["utility_bill"] = de_json_optional(data.get("utility_bill"), SecureValue, bot)
        data["address"] = de_json_optional(data.get("address"), SecureValue, bot)
        data["identity_card"] = de_json_optional(data.get("identity_card"), SecureValue, bot)
        data["driver_license"] = de_json_optional(data.get("driver_license"), SecureValue, bot)
        data["internal_passport"] = de_json_optional(
            data.get("internal_passport"), SecureValue, bot
        )
        data["passport"] = de_json_optional(data.get("passport"), SecureValue, bot)
        data["personal_details"] = de_json_optional(data.get("personal_details"), SecureValue, bot)

        return super().de_json(data=data, bot=bot)


class SecureValue(TelegramObject):
    """
    This object represents the credentials that were used to decrypt the encrypted value.
    All fields are optional and depend on the type of field.

    Args:
        data (:class:`telegram.DataCredentials`, optional): Credentials for encrypted Telegram
            Passport data. Available for "personal_details", "passport", "driver_license",
            "identity_card", "identity_passport" and "address" types.
        front_side (:class:`telegram.FileCredentials`, optional): Credentials for encrypted
            document's front side. Available for "passport", "driver_license", "identity_card"
            and "internal_passport".
        reverse_side (:class:`telegram.FileCredentials`, optional): Credentials for encrypted
            document's reverse side. Available for "driver_license" and "identity_card".
        selfie (:class:`telegram.FileCredentials`, optional): Credentials for encrypted selfie
            of the user with a document. Can be available for "passport", "driver_license",
            "identity_card" and "internal_passport".
        translation (list[:class:`telegram.FileCredentials`], optional): Credentials for an
            encrypted translation of the document. Available for "passport", "driver_license",
            "identity_card", "internal_passport", "utility_bill", "bank_statement",
            "rental_agreement", "passport_registration" and "temporary_registration".
        files (list[:class:`telegram.FileCredentials`], optional): Credentials for encrypted
            files. Available for "utility_bill", "bank_statement", "rental_agreement",
            "passport_registration" and "temporary_registration" types.

    Attributes:
        data (:class:`telegram.DataCredentials`): Optional. Credentials for encrypted Telegram
            Passport data. Available for "personal_details", "passport", "driver_license",
            "identity_card", "identity_passport" and "address" types.
        front_side (:class:`telegram.FileCredentials`): Optional. Credentials for encrypted
            document's front side. Available for "passport", "driver_license", "identity_card"
            and "internal_passport".
        reverse_side (:class:`telegram.FileCredentials`): Optional. Credentials for encrypted
            document's reverse side. Available for "driver_license" and "identity_card".
        selfie (:class:`telegram.FileCredentials`): Optional. Credentials for encrypted selfie
            of the user with a document. Can be available for "passport", "driver_license",
            "identity_card" and "internal_passport".
        translation (tuple[:class:`telegram.FileCredentials`]): Optional. Credentials for an
            encrypted translation of the document. Available for "passport", "driver_license",
            "identity_card", "internal_passport", "utility_bill", "bank_statement",
            "rental_agreement", "passport_registration" and "temporary_registration".

            .. versionchanged:: 20.0
                |tupleclassattrs|

        files (tuple[:class:`telegram.FileCredentials`]): Optional. Credentials for encrypted
            files. Available for "utility_bill", "bank_statement", "rental_agreement",
            "passport_registration" and "temporary_registration" types.

            .. versionchanged:: 20.0

                * |tupleclassattrs|
                * |alwaystuple|

    """

    __slots__ = ("data", "files", "front_side", "reverse_side", "selfie", "translation")

    def __init__(
        self,
        data: "DataCredentials | None" = None,
        front_side: "FileCredentials | None" = None,
        reverse_side: "FileCredentials | None" = None,
        selfie: "FileCredentials | None" = None,
        files: Sequence["FileCredentials"] | None = None,
        translation: Sequence["FileCredentials"] | None = None,
        *,
        api_kwargs: JSONDict | None = None,
    ):
        super().__init__(api_kwargs=api_kwargs)
        self.data: DataCredentials | None = data
        self.front_side: FileCredentials | None = front_side
        self.reverse_side: FileCredentials | None = reverse_side
        self.selfie: FileCredentials | None = selfie
        self.files: tuple[FileCredentials, ...] = parse_sequence_arg(files)
        self.translation: tuple[FileCredentials, ...] = parse_sequence_arg(translation)

        self._freeze()

    @classmethod
    def de_json(cls, data: JSONDict, bot: "Bot | None" = None) -> "SecureValue":
        """See :meth:`telegram.TelegramObject.de_json`."""
        data = cls._parse_data(data)

        data["data"] = de_json_optional(data.get("data"), DataCredentials, bot)
        data["front_side"] = de_json_optional(data.get("front_side"), FileCredentials, bot)
        data["reverse_side"] = de_json_optional(data.get("reverse_side"), FileCredentials, bot)
        data["selfie"] = de_json_optional(data.get("selfie"), FileCredentials, bot)
        data["files"] = de_list_optional(data.get("files"), FileCredentials, bot)
        data["translation"] = de_list_optional(data.get("translation"), FileCredentials, bot)

        return super().de_json(data=data, bot=bot)


class _CredentialsBase(TelegramObject):
    """Base class for DataCredentials and FileCredentials."""

    __slots__ = ("data_hash", "file_hash", "hash", "secret")

    def __init__(
        self,
        hash: str,
        secret: str,
        *,
        api_kwargs: JSONDict | None = None,
    ):
        super().__init__(api_kwargs=api_kwargs)
        with self._unfrozen():
            self.hash: str = hash
            self.secret: str = secret

            # Aliases just to be sure
            self.file_hash: str = self.hash
            self.data_hash: str = self.hash


class DataCredentials(_CredentialsBase):
    """
    These credentials can be used to decrypt encrypted data from the data field in
    EncryptedPassportData.

    Args:
        data_hash (:obj:`str`): Checksum of encrypted data
        secret (:obj:`str`): Secret of encrypted data

    Attributes:
        hash (:obj:`str`): Checksum of encrypted data
        secret (:obj:`str`): Secret of encrypted data
    """

    __slots__ = ()

    def __init__(self, data_hash: str, secret: str, *, api_kwargs: JSONDict | None = None):
        super().__init__(hash=data_hash, secret=secret, api_kwargs=api_kwargs)
        self._freeze()


class FileCredentials(_CredentialsBase):
    """
    These credentials can be used to decrypt encrypted files from the front_side,
    reverse_side, selfie and files fields in EncryptedPassportData.

    Args:
        file_hash (:obj:`str`): Checksum of encrypted file
        secret (:obj:`str`): Secret of encrypted file

    Attributes:
        hash (:obj:`str`): Checksum of encrypted file
        secret (:obj:`str`): Secret of encrypted file
    """

    __slots__ = ()

    def __init__(self, file_hash: str, secret: str, *, api_kwargs: JSONDict | None = None):
        super().__init__(hash=file_hash, secret=secret, api_kwargs=api_kwargs)
        self._freeze()
