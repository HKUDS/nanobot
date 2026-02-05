#!/usr/bin/env python
#
#  A library that provides a Python interface to the Telegram Bot API
#  Copyright (C) 2015-2026
#  Leandro Toledo de Souza <devs@python-telegram-bot.org>
#
#  This program is free software: you can redistribute it and/or modify
#  it under the terms of the GNU Lesser Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU Lesser Public License for more details.
#
#  You should have received a copy of the GNU Lesser Public License
#  along with this program.  If not, see [http://www.gnu.org/licenses/].
"""This module contains a class that holds the parameters of a request to the Bot API."""

import json
from typing import Any, final
from urllib.parse import urlencode

from telegram._utils.strings import TextEncoding
from telegram._utils.types import UploadFileDict
from telegram.request._requestparameter import RequestParameter


@final
class RequestData:
    """Instances of this class collect the data needed for one request to the Bot API, including
    all parameters and files to be sent along with the request.

    .. versionadded:: 20.0

    Warning:
        How exactly instances of this are created should be considered an implementation detail
        and not part of PTBs public API. Users should exclusively rely on the documented
        attributes, properties and methods.

    Attributes:
        contains_files (:obj:`bool`): Whether this object contains files to be uploaded via
            ``multipart/form-data``.
    """

    __slots__ = ("_parameters", "contains_files")

    def __init__(self, parameters: list[RequestParameter] | None = None):
        self._parameters: list[RequestParameter] = parameters or []
        self.contains_files: bool = any(param.input_files for param in self._parameters)

    @property
    def parameters(self) -> dict[str, str | int | list[Any] | dict[Any, Any]]:
        """Gives the parameters as mapping of parameter name to the parameter value, which can be
        a single object of type :obj:`int`, :obj:`float`, :obj:`str` or :obj:`bool` or any
        (possibly nested) composition of lists, tuples and dictionaries, where each entry, key
        and value is of one of the mentioned types.

        Returns:
            dict[:obj:`str`, :obj:`str` | :obj:`int` | list[any] | dict[any, any]]
        """
        return {
            param.name: param.value  # type: ignore[misc]
            for param in self._parameters
            if param.value is not None
        }

    @property
    def json_parameters(self) -> dict[str, str]:
        """Gives the parameters as mapping of parameter name to the respective JSON encoded
        value.

        Tip:
            By default, this property uses the standard library's :func:`json.dumps`.
            To use a custom library for JSON encoding, you can directly encode the keys of
            :attr:`parameters` - note that string valued keys should not be JSON encoded.

        Returns:
            dict[:obj:`str`, :obj:`str`]
        """
        return {
            param.name: param.json_value
            for param in self._parameters
            if param.json_value is not None
        }

    def url_encoded_parameters(self, encode_kwargs: dict[str, Any] | None = None) -> str:
        """Encodes the parameters with :func:`urllib.parse.urlencode`.

        Args:
            encode_kwargs (dict[:obj:`str`, any], optional): Additional keyword arguments to pass
                along to :func:`urllib.parse.urlencode`.

        Returns:
            :obj:`str`
        """
        if encode_kwargs:
            return urlencode(self.json_parameters, **encode_kwargs)
        return urlencode(self.json_parameters)

    def parametrized_url(self, url: str, encode_kwargs: dict[str, Any] | None = None) -> str:
        """Shortcut for attaching the return value of :meth:`url_encoded_parameters` to the
        :paramref:`url`.

        Args:
            url (:obj:`str`): The URL the parameters will be attached to.
            encode_kwargs (dict[:obj:`str`, any], optional): Additional keyword arguments to pass
                along to :func:`urllib.parse.urlencode`.

        Returns:
            :obj:`str`
        """
        url_parameters = self.url_encoded_parameters(encode_kwargs=encode_kwargs)
        return f"{url}?{url_parameters}"

    @property
    def json_payload(self) -> bytes:
        """The :attr:`parameters` as UTF-8 encoded JSON payload.

        Tip:
            By default, this property uses the standard library's :func:`json.dumps`.
            To use a custom library for JSON encoding, you can directly encode the keys of
            :attr:`parameters` - note that string valued keys should not be JSON encoded.

        Returns:
            :obj:`bytes`
        """
        return json.dumps(self.json_parameters).encode(TextEncoding.UTF_8)

    @property
    def multipart_data(self) -> UploadFileDict:
        """Gives the files contained in this object as mapping of part name to encoded content.

        .. versionchanged:: 21.5
            Content may now be a file handle.
        """
        multipart_data: UploadFileDict = {}
        for param in self._parameters:
            m_data = param.multipart_data
            if m_data:
                multipart_data.update(m_data)
        return multipart_data
