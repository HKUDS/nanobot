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
"""This module contains a class that describes a single parameter of a request to the Bot API."""

import datetime as dtm
import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import final

from telegram._files._inputstorycontent import InputStoryContent
from telegram._files.inputfile import InputFile
from telegram._files.inputmedia import InputMedia, InputPaidMedia
from telegram._files.inputprofilephoto import InputProfilePhoto, InputProfilePhotoStatic
from telegram._files.inputsticker import InputSticker
from telegram._telegramobject import TelegramObject
from telegram._utils.datetime import to_timestamp
from telegram._utils.enum import StringEnum
from telegram._utils.types import UploadFileDict


@final
@dataclass(repr=True, eq=False, order=False, frozen=True)
class RequestParameter:
    """Instances of this class represent a single parameter to be sent along with a request to
    the Bot API.

    .. versionadded:: 20.0

    Warning:
        This class intended is to be used internally by the library and *not* by the user. Changes
        to this class are not considered breaking changes and may not be documented in the
        changelog.

    Args:
        name (:obj:`str`): The name of the parameter.
        value (:obj:`object` | :obj:`None`): The value of the parameter. Must be JSON-dumpable.
        input_files (list[:class:`telegram.InputFile`], optional): A list of files that should be
            uploaded along with this parameter.

    Attributes:
        name (:obj:`str`): The name of the parameter.
        value (:obj:`object` | :obj:`None`): The value of the parameter.
        input_files (list[:class:`telegram.InputFile` | :obj:`None`): A list of files that should
            be uploaded along with this parameter.
    """

    __slots__ = ("input_files", "name", "value")

    name: str
    value: object
    input_files: list[InputFile] | None

    @property
    def json_value(self) -> str | None:
        """The JSON dumped :attr:`value` or :obj:`None` if :attr:`value` is :obj:`None`.
        The latter can currently only happen if :attr:`input_files` has exactly one element that
        must not be uploaded via an attach:// URI.
        """
        if isinstance(self.value, str):
            return self.value
        if self.value is None:
            return None
        return json.dumps(self.value)

    @property
    def multipart_data(self) -> UploadFileDict | None:
        """A dict with the file data to upload, if any.

        .. versionchanged:: 21.5
            Content may now be a file handle.
        """
        if not self.input_files:
            return None
        return {
            (input_file.attach_name or self.name): input_file.field_tuple
            for input_file in self.input_files
        }

    @staticmethod
    def _value_and_input_files_from_input(  # pylint: disable=too-many-return-statements
        value: object,
    ) -> tuple[object, list[InputFile]]:
        """Converts `value` into something that we can json-dump. Returns two values:
        1. the JSON-dumpable value. May be `None` in case the value is an InputFile which must
           not be uploaded via an attach:// URI
        2. A list of InputFiles that should be uploaded for this value

        Note that we handle files differently depending on whether attaching them via an URI of the
        form attach://<name> is documented to be allowed or not.
        There was some confusion whether this worked for all files, so that we stick to the
        documented ways for now.
        See https://github.com/tdlib/telegram-bot-api/issues/167 and
        https://github.com/tdlib/telegram-bot-api/issues/259

        This method only does some special casing for our own helper class StringEnum, but not
        for general enums. This is because:
        * tg.constants currently only uses IntEnum as second enum type and json dumping that
          is no problem
        * if a user passes a custom enum, it's unlikely that we can actually properly handle it
          even with some special casing.
        """
        if isinstance(value, dtm.datetime):
            return to_timestamp(value), []
        if isinstance(value, dtm.timedelta):
            seconds = value.total_seconds()
            # We convert to int for completeness for whole seconds
            if seconds.is_integer():
                return int(seconds), []
            # The Bot API doesn't document behavior for fractions of seconds so far, but we don't
            # want to silently drop them
            return seconds, []
        if isinstance(value, StringEnum):
            return value.value, []
        if isinstance(value, InputFile):
            if value.attach_uri:
                return value.attach_uri, [value]
            return None, [value]

        if isinstance(value, InputMedia | InputPaidMedia) and isinstance(value.media, InputFile):
            # We call to_dict and change the returned dict instead of overriding
            # value.media in case the same value is reused for another request
            data = value.to_dict()
            if value.media.attach_uri:
                data["media"] = value.media.attach_uri
            else:
                data.pop("media", None)

            thumbnail = data.get("thumbnail", None)
            if isinstance(thumbnail, InputFile):
                if thumbnail.attach_uri:
                    data["thumbnail"] = thumbnail.attach_uri
                else:
                    data.pop("thumbnail", None)
                return data, [value.media, thumbnail]

            return data, [value.media]

        if isinstance(value, InputProfilePhoto):
            attr = "photo" if isinstance(value, InputProfilePhotoStatic) else "animation"
            if not isinstance(media := getattr(value, attr), InputFile):
                # We don't have to upload anything
                return value.to_dict(), []

            # We call to_dict and change the returned dict instead of overriding
            # value.photo in case the same value is reused for another request
            data = value.to_dict()
            data[attr] = media.attach_uri
            return data, [media]

        if isinstance(value, InputStoryContent):
            attr = value.type
            if not isinstance(media := getattr(value, attr), InputFile):
                # We don't have to upload anything
                return value.to_dict(), []

            # We call to_dict and change the returned dict instead of overriding
            # value.photo in case the same value is reused for another request
            data = value.to_dict()
            data[attr] = media.attach_uri
            return data, [media]

        if isinstance(value, InputSticker) and isinstance(value.sticker, InputFile):
            # We call to_dict and change the returned dict instead of overriding
            # value.sticker in case the same value is reused for another request
            data = value.to_dict()
            data["sticker"] = value.sticker.attach_uri
            return data, [value.sticker]

        if isinstance(value, TelegramObject):
            # Needs to be last, because InputMedia is a subclass of TelegramObject
            return value.to_dict(), []
        return value, []

    @classmethod
    def from_input(cls, key: str, value: object) -> "RequestParameter":
        """Builds an instance of this class for a given key-value pair that represents the raw
        input as passed along from a method of :class:`telegram.Bot`.
        """
        if not isinstance(value, str | bytes) and isinstance(value, Sequence):
            param_values = []
            input_files = []
            for obj in value:
                param_value, input_file = cls._value_and_input_files_from_input(obj)
                if param_value is not None:
                    param_values.append(param_value)
                input_files.extend(input_file)
            return RequestParameter(
                name=key, value=param_values, input_files=input_files if input_files else None
            )

        param_value, input_files = cls._value_and_input_files_from_input(value)
        return RequestParameter(
            name=key, value=param_value, input_files=input_files if input_files else None
        )
