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
"""This module contains an object that represents a Telegram File."""

import shutil
import urllib.parse as urllib_parse
from base64 import b64decode
from pathlib import Path
from typing import TYPE_CHECKING, BinaryIO

from telegram._passport.credentials import decrypt
from telegram._telegramobject import TelegramObject
from telegram._utils.defaultvalue import DEFAULT_NONE
from telegram._utils.files import is_local_file
from telegram._utils.types import FilePathInput, JSONDict, ODVInput

if TYPE_CHECKING:
    from telegram import FileCredentials


class File(TelegramObject):
    """
    This object represents a file ready to be downloaded. The file can be e.g. downloaded with
    :attr:`download_to_drive`. It is guaranteed that the link will be valid for at least 1 hour.
    When the link expires, a new one can be requested by calling :meth:`telegram.Bot.get_file`.

    Objects of this class are comparable in terms of equality. Two objects of this class are
    considered equal, if their :attr:`file_unique_id` is equal.

    .. versionchanged:: 20.0
        ``download`` was split into :meth:`download_to_drive` and :meth:`download_to_memory`.

    Note:
        * Maximum file size to download is
          :tg-const:`telegram.constants.FileSizeLimit.FILESIZE_DOWNLOAD`.
        * If you obtain an instance of this class from :attr:`telegram.PassportFile.get_file`,
          then it will automatically be decrypted as it downloads when you call e.g.
          :meth:`download_to_drive`.

    Args:
        file_id (:obj:`str`): Identifier for this file, which can be used to download
            or reuse the file.
        file_unique_id (:obj:`str`): Unique identifier for this file, which
            is supposed to be the same over time and for different bots.
            Can't be used to download or reuse the file.
        file_size (:obj:`int`, optional): File size in bytes, if known.
        file_path (:obj:`str`, optional): File path. Use e.g. :meth:`download_to_drive` to get the
            file.

    Attributes:
        file_id (:obj:`str`): Identifier for this file, which can be used to download
            or reuse the file.
        file_unique_id (:obj:`str`): Unique identifier for this file, which
            is supposed to be the same over time and for different bots.
            Can't be used to download or reuse the file.
        file_size (:obj:`int`): Optional. File size in bytes, if known.
        file_path (:obj:`str`): Optional. File path. Use e.g. :meth:`download_to_drive` to get the
            file.
    """

    __slots__ = (
        "_credentials",
        "file_id",
        "file_path",
        "file_size",
        "file_unique_id",
    )

    def __init__(
        self,
        file_id: str,
        file_unique_id: str,
        file_size: int | None = None,
        file_path: str | None = None,
        *,
        api_kwargs: JSONDict | None = None,
    ):
        super().__init__(api_kwargs=api_kwargs)

        # Required
        self.file_id: str = str(file_id)
        self.file_unique_id: str = str(file_unique_id)
        # Optionals
        self.file_size: int | None = file_size
        self.file_path: str | None = file_path

        self._credentials: FileCredentials | None = None

        self._id_attrs = (self.file_unique_id,)

        self._freeze()

    def _get_encoded_url(self) -> str:
        """Convert any UTF-8 char in :obj:`File.file_path` into a url encoded ASCII string."""
        sres = urllib_parse.urlsplit(str(self.file_path))
        return urllib_parse.urlunsplit(
            urllib_parse.SplitResult(
                sres.scheme, sres.netloc, urllib_parse.quote(sres.path), sres.query, sres.fragment
            )
        )

    def _prepare_decrypt(self, buf: bytes) -> bytes:
        return decrypt(b64decode(self._credentials.secret), b64decode(self._credentials.hash), buf)

    async def download_to_drive(
        self,
        custom_path: FilePathInput | None = None,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
    ) -> Path:
        """
        Download this file. By default, the file is saved in the current working directory with
        :attr:`file_path` as file name. If :paramref:`custom_path` is supplied as a :obj:`str` or
        :obj:`pathlib.Path`, it will be saved to that path.

        Note:
            If :paramref:`custom_path` isn't provided and :attr:`file_path` is the path of a
            local file (which is the case when a Bot API Server is running in local mode), this
            method will just return the path.

            The only exception to this are encrypted files (e.g. a passport file). For these, a
            file with the prefix `decrypted_` will be created in the same directory as the
            original file in order to decrypt the file without changing the existing one
            in-place.

        .. seealso:: :wiki:`Working with Files and Media <Working-with-Files-and-Media>`

        .. versionchanged:: 20.0

            * :paramref:`custom_path` parameter now also accepts :class:`pathlib.Path` as argument.
            * Returns :class:`pathlib.Path` object in cases where previously a :obj:`str` was
              returned.
            * This method was previously called ``download``. It was split into
              :meth:`download_to_drive` and :meth:`download_to_memory`.

        .. versionchanged:: 21.7
            Raises :exc:`RuntimeError` if :attr:`file_path` is not set. Note that files without
            a :attr:`file_path` could never be downloaded, as this attribute is mandatory for that
            operation.

        Args:
            custom_path (:class:`pathlib.Path` | :obj:`str` , optional): The path where the file
                will be saved to. If not specified, will be saved in the current working directory
                with :attr:`file_path` as file name or the :attr:`file_id` if :attr:`file_path`
                is not set.

        Keyword Args:
            read_timeout (:obj:`float` | :obj:`None`, optional): Value to pass to
                :paramref:`telegram.request.BaseRequest.post.read_timeout`. Defaults to
                :attr:`~telegram.request.BaseRequest.DEFAULT_NONE`.
            write_timeout (:obj:`float` | :obj:`None`, optional): Value to pass to
                :paramref:`telegram.request.BaseRequest.post.write_timeout`. Defaults to
                :attr:`~telegram.request.BaseRequest.DEFAULT_NONE`.
            connect_timeout (:obj:`float` | :obj:`None`, optional): Value to pass to
                :paramref:`telegram.request.BaseRequest.post.connect_timeout`. Defaults to
                :attr:`~telegram.request.BaseRequest.DEFAULT_NONE`.
            pool_timeout (:obj:`float` | :obj:`None`, optional): Value to pass to
                :paramref:`telegram.request.BaseRequest.post.pool_timeout`. Defaults to
                :attr:`~telegram.request.BaseRequest.DEFAULT_NONE`.

        Returns:
            :class:`pathlib.Path`: Returns the Path object the file was downloaded to.

        Raises:
            RuntimeError: If :attr:`file_path` is not set.

        """
        if not self.file_path:
            raise RuntimeError("No `file_path` available for this file. Can not download.")

        local_file = is_local_file(self.file_path)
        url = None if local_file else self._get_encoded_url()

        # if _credentials exists we want to decrypt the file
        if local_file and self._credentials:
            file_to_decrypt = Path(self.file_path)
            buf = self._prepare_decrypt(file_to_decrypt.read_bytes())
            if custom_path is not None:
                path = Path(custom_path)
            else:
                path = Path(str(file_to_decrypt.parent) + "/decrypted_" + file_to_decrypt.name)
            path.write_bytes(buf)
            return path

        if custom_path is not None and local_file:
            shutil.copyfile(self.file_path, str(custom_path))
            return Path(custom_path)

        if custom_path:
            filename = Path(custom_path)
        elif local_file:
            return Path(self.file_path)
        else:
            filename = Path(Path(self.file_path).name)

        buf = await self.get_bot().request.retrieve(
            url,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
        )
        if self._credentials:
            buf = self._prepare_decrypt(buf)
        filename.write_bytes(buf)
        return filename

    async def download_to_memory(
        self,
        out: BinaryIO,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
    ) -> None:
        """
        Download this file into memory. :paramref:`out` needs to be supplied with a
        :obj:`io.BufferedIOBase`, the file contents will be saved to that object using the
        :obj:`out.write<io.BufferedIOBase.write>` method.

        .. seealso:: :wiki:`Working with Files and Media <Working-with-Files-and-Media>`

        Hint:
            If you want to immediately read the data from ``out`` after calling this method, you
            should call ``out.seek(0)`` first. See also :meth:`io.IOBase.seek`.

        .. versionadded:: 20.0

        .. versionchanged:: 21.7
            Raises :exc:`RuntimeError` if :attr:`file_path` is not set. Note that files without
            a :attr:`file_path` could never be downloaded, as this attribute is mandatory for that
            operation.

        Args:
            out (:obj:`io.BufferedIOBase`): A file-like object. Must be opened for writing in
                binary mode.

        Keyword Args:
            read_timeout (:obj:`float` | :obj:`None`, optional): Value to pass to
                :paramref:`telegram.request.BaseRequest.post.read_timeout`. Defaults to
                :attr:`~telegram.request.BaseRequest.DEFAULT_NONE`.
            write_timeout (:obj:`float` | :obj:`None`, optional): Value to pass to
                :paramref:`telegram.request.BaseRequest.post.write_timeout`. Defaults to
                :attr:`~telegram.request.BaseRequest.DEFAULT_NONE`.
            connect_timeout (:obj:`float` | :obj:`None`, optional): Value to pass to
                :paramref:`telegram.request.BaseRequest.post.connect_timeout`. Defaults to
                :attr:`~telegram.request.BaseRequest.DEFAULT_NONE`.
            pool_timeout (:obj:`float` | :obj:`None`, optional): Value to pass to
                :paramref:`telegram.request.BaseRequest.post.pool_timeout`. Defaults to
                :attr:`~telegram.request.BaseRequest.DEFAULT_NONE`.

        Raises:
            RuntimeError: If :attr:`file_path` is not set.
        """
        if not self.file_path:
            raise RuntimeError("No `file_path` available for this file. Can not download.")

        local_file = is_local_file(self.file_path)
        url = None if local_file else self._get_encoded_url()
        path = Path(self.file_path) if local_file else None
        if local_file:
            buf = path.read_bytes()
        else:
            buf = await self.get_bot().request.retrieve(
                url,
                read_timeout=read_timeout,
                write_timeout=write_timeout,
                connect_timeout=connect_timeout,
                pool_timeout=pool_timeout,
            )
        if self._credentials:
            buf = self._prepare_decrypt(buf)
        out.write(buf)

    async def download_as_bytearray(
        self,
        buf: bytearray | None = None,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
    ) -> bytearray:
        """Download this file and return it as a bytearray.

        .. versionchanged:: 21.7
            Raises :exc:`RuntimeError` if :attr:`file_path` is not set. Note that files without
            a :attr:`file_path` could never be downloaded, as this attribute is mandatory for that
            operation.

        Args:
            buf (:obj:`bytearray`, optional): Extend the given bytearray with the downloaded data.

        Keyword Args:
            read_timeout (:obj:`float` | :obj:`None`, optional): Value to pass to
                :paramref:`telegram.request.BaseRequest.post.read_timeout`. Defaults to
                :attr:`~telegram.request.BaseRequest.DEFAULT_NONE`.

                .. versionadded:: 20.0
            write_timeout (:obj:`float` | :obj:`None`, optional): Value to pass to
                :paramref:`telegram.request.BaseRequest.post.write_timeout`. Defaults to
                :attr:`~telegram.request.BaseRequest.DEFAULT_NONE`.

                .. versionadded:: 20.0
            connect_timeout (:obj:`float` | :obj:`None`, optional): Value to pass to
                :paramref:`telegram.request.BaseRequest.post.connect_timeout`. Defaults to
                :attr:`~telegram.request.BaseRequest.DEFAULT_NONE`.

                .. versionadded:: 20.0
            pool_timeout (:obj:`float` | :obj:`None`, optional): Value to pass to
                :paramref:`telegram.request.BaseRequest.post.pool_timeout`. Defaults to
                :attr:`~telegram.request.BaseRequest.DEFAULT_NONE`.

                .. versionadded:: 20.0

        Returns:
            :obj:`bytearray`: The same object as :paramref:`buf` if it was specified. Otherwise a
            newly allocated :obj:`bytearray`.

        Raises:
            RuntimeError: If :attr:`file_path` is not set.

        """
        if not self.file_path:
            raise RuntimeError("No `file_path` available for this file. Can not download.")

        if buf is None:
            buf = bytearray()

        if is_local_file(self.file_path):
            bytes_data = Path(self.file_path).read_bytes()
        else:
            bytes_data = await self.get_bot().request.retrieve(
                self._get_encoded_url(),
                read_timeout=read_timeout,
                write_timeout=write_timeout,
                connect_timeout=connect_timeout,
                pool_timeout=pool_timeout,
            )
        if self._credentials:
            buf.extend(self._prepare_decrypt(bytes_data))
        else:
            buf.extend(bytes_data)
        return buf

    def set_credentials(self, credentials: "FileCredentials") -> None:
        """Sets the passport credentials for the file.

        Args:
            credentials (:class:`telegram.FileCredentials`): The credentials.
        """
        self._credentials = credentials
