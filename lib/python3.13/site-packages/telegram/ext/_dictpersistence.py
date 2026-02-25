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
"""This module contains the DictPersistence class."""

import json
from copy import deepcopy
from typing import TYPE_CHECKING, Any, cast

from telegram.ext import BasePersistence, PersistenceInput
from telegram.ext._utils.types import CDCData, ConversationDict, ConversationKey

if TYPE_CHECKING:
    from telegram._utils.types import JSONDict


class DictPersistence(BasePersistence[dict[Any, Any], dict[Any, Any], dict[Any, Any]]):
    """Using Python's :obj:`dict` and :mod:`json` for making your bot persistent.

    Attention:
        The interface provided by this class is intended to be accessed exclusively by
        :class:`~telegram.ext.Application`. Calling any of the methods below manually might
        interfere with the integration of persistence into :class:`~telegram.ext.Application`.

    Note:
        * Data managed by :class:`DictPersistence` is in-memory only and will be lost when the bot
          shuts down. This is, because :class:`DictPersistence` is mainly intended as starting
          point for custom persistence classes that need to JSON-serialize the stored data before
          writing them to file/database.

        * This implementation of :class:`BasePersistence` does not handle data that cannot be
          serialized by :func:`json.dumps`.

    .. seealso:: :wiki:`Making Your Bot Persistent <Making-your-bot-persistent>`

    .. versionchanged:: 20.0
        The parameters and attributes ``store_*_data`` were replaced by :attr:`store_data`.

    Args:
        store_data (:class:`~telegram.ext.PersistenceInput`, optional): Specifies which kinds of
            data will be saved by this persistence instance. By default, all available kinds of
            data will be saved.
        user_data_json (:obj:`str`, optional): JSON string that will be used to reconstruct
            user_data on creating this persistence. Default is ``""``.
        chat_data_json (:obj:`str`, optional): JSON string that will be used to reconstruct
            chat_data on creating this persistence. Default is ``""``.
        bot_data_json (:obj:`str`, optional): JSON string that will be used to reconstruct
            bot_data on creating this persistence. Default is ``""``.
        conversations_json (:obj:`str`, optional): JSON string that will be used to reconstruct
            conversation on creating this persistence. Default is ``""``.
        callback_data_json (:obj:`str`, optional): JSON string that will be used to reconstruct
            callback_data on creating this persistence. Default is ``""``.

            .. versionadded:: 13.6
        update_interval (:obj:`int` | :obj:`float`, optional): The
            :class:`~telegram.ext.Application` will update
            the persistence in regular intervals. This parameter specifies the time (in seconds) to
            wait between two consecutive runs of updating the persistence. Defaults to 60 seconds.

            .. versionadded:: 20.0
    Attributes:
        store_data (:class:`~telegram.ext.PersistenceInput`): Specifies which kinds of data will
            be saved by this persistence instance.
    """

    __slots__ = (
        "_bot_data",
        "_bot_data_json",
        "_callback_data",
        "_callback_data_json",
        "_chat_data",
        "_chat_data_json",
        "_conversations",
        "_conversations_json",
        "_user_data",
        "_user_data_json",
    )

    def __init__(
        self,
        store_data: PersistenceInput | None = None,
        user_data_json: str = "",
        chat_data_json: str = "",
        bot_data_json: str = "",
        conversations_json: str = "",
        callback_data_json: str = "",
        update_interval: float = 60,
    ):
        super().__init__(store_data=store_data, update_interval=update_interval)
        self._user_data = None
        self._chat_data = None
        self._bot_data = None
        self._callback_data = None
        self._conversations = None
        self._user_data_json: str | None = None
        self._chat_data_json: str | None = None
        self._bot_data_json: str | None = None
        self._callback_data_json: str | None = None
        self._conversations_json: str | None = None
        if user_data_json:
            try:
                self._user_data = self._decode_user_chat_data_from_json(user_data_json)
                self._user_data_json = user_data_json
            except (ValueError, AttributeError) as exc:
                raise TypeError("Unable to deserialize user_data_json. Not valid JSON") from exc
        if chat_data_json:
            try:
                self._chat_data = self._decode_user_chat_data_from_json(chat_data_json)
                self._chat_data_json = chat_data_json
            except (ValueError, AttributeError) as exc:
                raise TypeError("Unable to deserialize chat_data_json. Not valid JSON") from exc
        if bot_data_json:
            try:
                self._bot_data = json.loads(bot_data_json)
                self._bot_data_json = bot_data_json
            except (ValueError, AttributeError) as exc:
                raise TypeError("Unable to deserialize bot_data_json. Not valid JSON") from exc
            if not isinstance(self._bot_data, dict):
                raise TypeError("bot_data_json must be serialized dict")
        if callback_data_json:
            try:
                data = json.loads(callback_data_json)
            except (ValueError, AttributeError) as exc:
                raise TypeError(
                    "Unable to deserialize callback_data_json. Not valid JSON"
                ) from exc
            # We are a bit more thorough with the checking of the format here, because it's
            # more complicated than for the other things
            try:
                if data is None:
                    self._callback_data = None
                else:
                    self._callback_data = cast(
                        "CDCData",
                        ([(one, float(two), three) for one, two, three in data[0]], data[1]),
                    )
                self._callback_data_json = callback_data_json
            except (ValueError, IndexError) as exc:
                raise TypeError("callback_data_json is not in the required format") from exc
            if self._callback_data is not None and (
                not all(
                    isinstance(entry[2], dict) and isinstance(entry[0], str)
                    for entry in self._callback_data[0]
                )
                or not isinstance(self._callback_data[1], dict)
            ):
                raise TypeError("callback_data_json is not in the required format")

        if conversations_json:
            try:
                self._conversations = self._decode_conversations_from_json(conversations_json)
                self._conversations_json = conversations_json
            except (ValueError, AttributeError) as exc:
                raise TypeError(
                    "Unable to deserialize conversations_json. Not valid JSON"
                ) from exc

    @property
    def user_data(self) -> dict[int, dict[Any, Any]] | None:
        """:obj:`dict`: The user_data as a dict."""
        return self._user_data

    @property
    def user_data_json(self) -> str:
        """:obj:`str`: The user_data serialized as a JSON-string."""
        if self._user_data_json:
            return self._user_data_json
        return json.dumps(self.user_data)

    @property
    def chat_data(self) -> dict[int, dict[Any, Any]] | None:
        """:obj:`dict`: The chat_data as a dict."""
        return self._chat_data

    @property
    def chat_data_json(self) -> str:
        """:obj:`str`: The chat_data serialized as a JSON-string."""
        if self._chat_data_json:
            return self._chat_data_json
        return json.dumps(self.chat_data)

    @property
    def bot_data(self) -> dict[Any, Any] | None:
        """:obj:`dict`: The bot_data as a dict."""
        return self._bot_data

    @property
    def bot_data_json(self) -> str:
        """:obj:`str`: The bot_data serialized as a JSON-string."""
        if self._bot_data_json:
            return self._bot_data_json
        return json.dumps(self.bot_data)

    @property
    def callback_data(self) -> CDCData | None:
        """tuple[list[tuple[:obj:`str`, :obj:`float`, dict[:obj:`str`, :class:`object`]]], \
        dict[:obj:`str`, :obj:`str`]]: The metadata on the stored callback data.

        .. versionadded:: 13.6
        """
        return self._callback_data

    @property
    def callback_data_json(self) -> str:
        """:obj:`str`: The metadata on the stored callback data as a JSON-string.

        .. versionadded:: 13.6
        """
        if self._callback_data_json:
            return self._callback_data_json
        return json.dumps(self.callback_data)

    @property
    def conversations(self) -> dict[str, ConversationDict] | None:
        """:obj:`dict`: The conversations as a dict."""
        return self._conversations

    @property
    def conversations_json(self) -> str:
        """:obj:`str`: The conversations serialized as a JSON-string."""
        if self._conversations_json:
            return self._conversations_json
        if self.conversations:
            return self._encode_conversations_to_json(self.conversations)
        return json.dumps(self.conversations)

    async def get_user_data(self) -> dict[int, dict[object, object]]:
        """Returns the user_data created from the ``user_data_json`` or an empty :obj:`dict`.

        Returns:
            :obj:`dict`: The restored user data.
        """
        if self.user_data is None:
            self._user_data = {}
        return deepcopy(self.user_data)  # type: ignore[arg-type]

    async def get_chat_data(self) -> dict[int, dict[object, object]]:
        """Returns the chat_data created from the ``chat_data_json`` or an empty :obj:`dict`.

        Returns:
            :obj:`dict`: The restored chat data.
        """
        if self.chat_data is None:
            self._chat_data = {}
        return deepcopy(self.chat_data)  # type: ignore[arg-type]

    async def get_bot_data(self) -> dict[object, object]:
        """Returns the bot_data created from the ``bot_data_json`` or an empty :obj:`dict`.

        Returns:
            :obj:`dict`: The restored bot data.
        """
        if self.bot_data is None:
            self._bot_data = {}
        return deepcopy(self.bot_data)  # type: ignore[arg-type]

    async def get_callback_data(self) -> CDCData | None:
        """Returns the callback_data created from the ``callback_data_json`` or :obj:`None`.

        .. versionadded:: 13.6

        Returns:
            tuple[list[tuple[:obj:`str`, :obj:`float`, dict[:obj:`str`, :class:`object`]]], \
                dict[:obj:`str`, :obj:`str`]]: The restored metadata or :obj:`None`, \
                if no data was stored.
        """
        if self.callback_data is None:
            self._callback_data = None
            return None
        return deepcopy(self.callback_data)

    async def get_conversations(self, name: str) -> ConversationDict:
        """Returns the conversations created from the ``conversations_json`` or an empty
        :obj:`dict`.

        Returns:
            :obj:`dict`: The restored conversations data.
        """
        if self.conversations is None:
            self._conversations = {}
        return self.conversations.get(name, {}).copy()  # type: ignore[union-attr]

    async def update_conversation(
        self, name: str, key: ConversationKey, new_state: object | None
    ) -> None:
        """Will update the conversations for the given handler.

        Args:
            name (:obj:`str`): The handler's name.
            key (:obj:`tuple`): The key the state is changed for.
            new_state (:obj:`tuple` | :class:`object`): The new state for the given key.
        """
        if not self._conversations:
            self._conversations = {}
        if self._conversations.setdefault(name, {}).get(key) == new_state:
            return
        self._conversations[name][key] = new_state
        self._conversations_json = None

    async def update_user_data(self, user_id: int, data: dict[Any, Any]) -> None:
        """Will update the user_data (if changed).

        Args:
            user_id (:obj:`int`): The user the data might have been changed for.
            data (:obj:`dict`): The :attr:`telegram.ext.Application.user_data` ``[user_id]``.
        """
        if self._user_data is None:
            self._user_data = {}
        if self._user_data.get(user_id) == data:
            return
        self._user_data[user_id] = data
        self._user_data_json = None

    async def update_chat_data(self, chat_id: int, data: dict[Any, Any]) -> None:
        """Will update the chat_data (if changed).

        Args:
            chat_id (:obj:`int`): The chat the data might have been changed for.
            data (:obj:`dict`): The :attr:`telegram.ext.Application.chat_data` ``[chat_id]``.
        """
        if self._chat_data is None:
            self._chat_data = {}
        if self._chat_data.get(chat_id) == data:
            return
        self._chat_data[chat_id] = data
        self._chat_data_json = None

    async def update_bot_data(self, data: dict[Any, Any]) -> None:
        """Will update the bot_data (if changed).

        Args:
            data (:obj:`dict`): The :attr:`telegram.ext.Application.bot_data`.
        """
        if self._bot_data == data:
            return
        self._bot_data = data
        self._bot_data_json = None

    async def update_callback_data(self, data: CDCData) -> None:
        """Will update the callback_data (if changed).

        .. versionadded:: 13.6

        Args:
            data (tuple[list[tuple[:obj:`str`, :obj:`float`, dict[:obj:`str`, :class:`object`]]], \
                dict[:obj:`str`, :obj:`str`]]): The relevant data to restore
                :class:`telegram.ext.CallbackDataCache`.
        """
        if self._callback_data == data:
            return
        self._callback_data = data
        self._callback_data_json = None

    async def drop_chat_data(self, chat_id: int) -> None:
        """Will delete the specified key from the :attr:`chat_data`.

        .. versionadded:: 20.0

        Args:
            chat_id (:obj:`int`): The chat id to delete from the persistence.
        """
        if self._chat_data is None:
            return
        self._chat_data.pop(chat_id, None)
        self._chat_data_json = None

    async def drop_user_data(self, user_id: int) -> None:
        """Will delete the specified key from the :attr:`user_data`.

        .. versionadded:: 20.0

        Args:
            user_id (:obj:`int`): The user id to delete from the persistence.
        """
        if self._user_data is None:
            return
        self._user_data.pop(user_id, None)
        self._user_data_json = None

    async def refresh_user_data(self, user_id: int, user_data: dict[Any, Any]) -> None:
        """Does nothing.

        .. versionadded:: 13.6
        .. seealso:: :meth:`telegram.ext.BasePersistence.refresh_user_data`
        """

    async def refresh_chat_data(self, chat_id: int, chat_data: dict[Any, Any]) -> None:
        """Does nothing.

        .. versionadded:: 13.6
        .. seealso:: :meth:`telegram.ext.BasePersistence.refresh_chat_data`
        """

    async def refresh_bot_data(self, bot_data: dict[Any, Any]) -> None:
        """Does nothing.

        .. versionadded:: 13.6
        .. seealso:: :meth:`telegram.ext.BasePersistence.refresh_bot_data`
        """

    async def flush(self) -> None:
        """Does nothing.

        .. versionadded:: 20.0
        .. seealso:: :meth:`telegram.ext.BasePersistence.flush`
        """

    @staticmethod
    def _encode_conversations_to_json(conversations: dict[str, ConversationDict]) -> str:
        """Helper method to encode a conversations dict (that uses tuples as keys) to a
        JSON-serializable way. Use :meth:`self._decode_conversations_from_json` to decode.

        Args:
            conversations (:obj:`dict`): The conversations dict to transform to JSON.

        Returns:
            :obj:`str`: The JSON-serialized conversations dict
        """
        tmp: dict[str, JSONDict] = {}
        for handler, states in conversations.items():
            tmp[handler] = {}
            for key, state in states.items():
                tmp[handler][json.dumps(key)] = state
        return json.dumps(tmp)

    @staticmethod
    def _decode_conversations_from_json(json_string: str) -> dict[str, ConversationDict]:
        """Helper method to decode a conversations dict (that uses tuples as keys) from a
        JSON-string created with :meth:`self._encode_conversations_to_json`.

        Args:
            json_string (:obj:`str`): The conversations dict as JSON string.

        Returns:
            :obj:`dict`: The conversations dict after decoding
        """
        tmp = json.loads(json_string)
        conversations: dict[str, ConversationDict] = {}
        for handler, states in tmp.items():
            conversations[handler] = {}
            for key, state in states.items():
                conversations[handler][tuple(json.loads(key))] = state
        return conversations

    @staticmethod
    def _decode_user_chat_data_from_json(data: str) -> dict[int, dict[object, object]]:
        """Helper method to decode chat or user data (that uses ints as keys) from a
        JSON-string.

        Args:
            data (:obj:`str`): The user/chat_data dict as JSON string.

        Returns:
            :obj:`dict`: The user/chat_data defaultdict after decoding
        """
        tmp: dict[int, dict[object, object]] = {}
        decoded_data = json.loads(data)
        for user, user_data in decoded_data.items():
            int_user_id = int(user)
            tmp[int_user_id] = {}
            for key, value in user_data.items():
                try:
                    _id = int(key)
                except ValueError:
                    _id = key
                tmp[int_user_id][_id] = value
        return tmp
