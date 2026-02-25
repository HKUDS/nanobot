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
"""This module contains an object that represents a Telegram InputFile."""

import mimetypes
from typing import IO
from uuid import uuid4

from telegram._utils.files import guess_file_name, load_file
from telegram._utils.strings import TextEncoding
from telegram._utils.types import FieldTuple

_DEFAULT_MIME_TYPE = "application/octet-stream"


class InputFile:
    """This object represents a Telegram InputFile.

    .. versionchanged:: 20.0

        * The former attribute ``attach`` was renamed to :attr:`attach_name`.
        * Method ``is_image`` was removed. If you pass :obj:`bytes` to :paramref:`obj` and would
          like to have the mime type automatically guessed, please pass :paramref:`filename`
          in addition.

    Args:
        obj (:term:`file object` | :obj:`bytes` | :obj:`str`): An open file descriptor or the files
            content as bytes or string.

            Note:
                If :paramref:`obj` is a string, it will be encoded as bytes via
                :external:obj:`obj.encode('utf-8') <str.encode>`.

            .. versionchanged:: 20.0
                Accept string input.
        filename (:obj:`str`, optional): Filename for this InputFile.
        attach (:obj:`bool`, optional): Pass :obj:`True` if the parameter this file belongs to in
            the request to Telegram should point to the multipart data via an ``attach://`` URI.
            Defaults to `False`.
        read_file_handle (:obj:`bool`, optional): If :obj:`True` and :paramref:`obj` is a file
            handle, the data will be read from the file handle on initialization of this object.
            If :obj:`False`, the file handle will be passed on to the
            :attr:`networking backend <telegram.request.BaseRequest.do_request>` which will have
            to handle the reading. Defaults to :obj:`True`.

            Tip:
                If you upload extremely large files, you may want to set this to :obj:`False` to
                avoid reading the complete file into memory. Additionally, this may be supported
                better by the networking backend (in particular it is handled better by
                the default :class:`~telegram.request.HTTPXRequest`).

            Important:
                If you set this to :obj:`False`, you have to ensure that the file handle is still
                open when the request is made. In particular, the following snippet can *not* work
                as expected.

                .. code-block:: python

                    with open('file.txt', 'rb') as file:
                        input_file = InputFile(file, read_file_handle=False)

                    # here the file handle is already closed and the upload will fail
                    await bot.send_document(chat_id, input_file)

            .. versionadded:: 21.5


    Attributes:
        input_file_content (:obj:`bytes` | :class:`IO`): The binary content of the file to send.
        attach_name (:obj:`str`): Optional. If present, the parameter this file belongs to in
            the request to Telegram should point to the multipart data via a an URI of the form
            ``attach://<attach_name>`` URI.
        filename (:obj:`str`): Filename for the file to be sent.
        mimetype (:obj:`str`): The mimetype inferred from the file to be sent.

    """

    __slots__ = ("attach_name", "filename", "input_file_content", "mimetype")

    def __init__(
        self,
        obj: IO[bytes] | bytes | str,
        filename: str | None = None,
        attach: bool = False,
        read_file_handle: bool = True,
    ):
        if isinstance(obj, bytes):
            self.input_file_content: bytes | IO[bytes] = obj
        elif isinstance(obj, str):
            self.input_file_content = obj.encode(TextEncoding.UTF_8)
        elif read_file_handle:
            reported_filename, self.input_file_content = load_file(obj)
            filename = filename or reported_filename
        else:
            self.input_file_content = obj
            filename = filename or guess_file_name(obj)

        self.attach_name: str | None = "attached" + uuid4().hex if attach else None

        if filename:
            self.mimetype: str = (
                mimetypes.guess_type(filename, strict=False)[0] or _DEFAULT_MIME_TYPE
            )
        else:
            self.mimetype = _DEFAULT_MIME_TYPE

        self.filename: str = filename or self.mimetype.replace("/", ".")

    @property
    def field_tuple(self) -> FieldTuple:
        """Field tuple representing the contents of the file for upload to the Telegram servers.

        .. versionchanged:: 21.5
            Content may now be a file handle.

        Returns:
            tuple[:obj:`str`, :obj:`bytes` | :class:`IO`, :obj:`str`]:
        """
        return self.filename, self.input_file_content, self.mimetype

    @property
    def attach_uri(self) -> str | None:
        """URI to insert into the JSON data for uploading the file. Returns :obj:`None`, if
        :attr:`attach_name` is :obj:`None`.
        """
        return f"attach://{self.attach_name}" if self.attach_name else None
