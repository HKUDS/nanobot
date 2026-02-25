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
"""This module contains the BasePersistence class."""

from abc import ABC, abstractmethod
from typing import Generic, NamedTuple, NoReturn

from telegram._bot import Bot
from telegram.ext._extbot import ExtBot
from telegram.ext._utils.types import BD, CD, UD, CDCData, ConversationDict, ConversationKey


class PersistenceInput(NamedTuple):
    """Convenience wrapper to group boolean input for the :paramref:`~BasePersistence.store_data`
    parameter for :class:`BasePersistence`.

    Args:
        bot_data (:obj:`bool`, optional): Whether the setting should be applied for ``bot_data``.
            Defaults to :obj:`True`.
        chat_data (:obj:`bool`, optional): Whether the setting should be applied for ``chat_data``.
            Defaults to :obj:`True`.
        user_data (:obj:`bool`, optional): Whether the setting should be applied for ``user_data``.
            Defaults to :obj:`True`.
        callback_data (:obj:`bool`, optional): Whether the setting should be applied for
            ``callback_data``. Defaults to :obj:`True`.

    Attributes:
        bot_data (:obj:`bool`): Whether the setting should be applied for ``bot_data``.
        chat_data (:obj:`bool`): Whether the setting should be applied for ``chat_data``.
        user_data (:obj:`bool`): Whether the setting should be applied for ``user_data``.
        callback_data (:obj:`bool`): Whether the setting should be applied for ``callback_data``.

    """

    bot_data: bool = True
    chat_data: bool = True
    user_data: bool = True
    callback_data: bool = True


class BasePersistence(ABC, Generic[UD, CD, BD]):
    """Interface class for adding persistence to your bot.
    Subclass this object for different implementations of a persistent bot.

    Attention:
        The interface provided by this class is intended to be accessed exclusively by
        :class:`~telegram.ext.Application`. Calling any of the methods below manually might
        interfere with the integration of persistence into :class:`~telegram.ext.Application`.

    All relevant methods must be overwritten. This includes:

    * :meth:`get_bot_data`
    * :meth:`update_bot_data`
    * :meth:`refresh_bot_data`
    * :meth:`get_chat_data`
    * :meth:`update_chat_data`
    * :meth:`refresh_chat_data`
    * :meth:`drop_chat_data`
    * :meth:`get_user_data`
    * :meth:`update_user_data`
    * :meth:`refresh_user_data`
    * :meth:`drop_user_data`
    * :meth:`get_callback_data`
    * :meth:`update_callback_data`
    * :meth:`get_conversations`
    * :meth:`update_conversation`
    * :meth:`flush`

    If you don't actually need one of those methods, a simple :keyword:`pass` is enough.
    For example, if you don't store ``bot_data``, you don't need :meth:`get_bot_data`,
    :meth:`update_bot_data` or :meth:`refresh_bot_data`.

    Note:
       You should avoid saving :class:`telegram.Bot` instances. This is because if you change e.g.
       the bots token, this won't propagate to the serialized instances and may lead to exceptions.

       To prevent this, the implementation may use :attr:`bot` to replace bot instances with a
       placeholder before serialization and insert :attr:`bot` back when loading the data.
       Since :attr:`bot` will be set when the process starts, this will be the up-to-date bot
       instance.

       If the persistence implementation does not take care of this, you should make sure not to
       store any bot instances in the data that will be persisted. E.g. in case of
       :class:`telegram.TelegramObject`, one may call :meth:`set_bot` to ensure that shortcuts like
       :meth:`telegram.Message.reply_text` are available.

    This class is a :class:`~typing.Generic` class and accepts three type variables:

    1. The type of the second argument of :meth:`update_user_data`, which must coincide with the
       type of the second argument of :meth:`refresh_user_data` and the values in the dictionary
       returned by :meth:`get_user_data`.
    2. The type of the second argument of :meth:`update_chat_data`, which must coincide with the
       type of the second argument of :meth:`refresh_chat_data` and the values in the dictionary
       returned by :meth:`get_chat_data`.
    3. The type of the argument of :meth:`update_bot_data`, which must coincide with the
       type of the argument of :meth:`refresh_bot_data` and the return value of
       :meth:`get_bot_data`.

    .. seealso:: :wiki:`Architecture Overview <Architecture>`,
        :wiki:`Making Your Bot Persistent <Making-your-bot-persistent>`

    .. versionchanged:: 20.0

        * The parameters and attributes ``store_*_data`` were replaced by :attr:`store_data`.
        * ``insert/replace_bot`` was dropped. Serialization of bot instances now needs to be
          handled by the specific implementation - see above note.

    Args:
        store_data (:class:`~telegram.ext.PersistenceInput`, optional): Specifies which kinds of
            data will be saved by this persistence instance. By default, all available kinds of
            data will be saved.
        update_interval (:obj:`int` | :obj:`float`, optional): The
            :class:`~telegram.ext.Application` will update
            the persistence in regular intervals. This parameter specifies the time (in seconds) to
            wait between two consecutive runs of updating the persistence. Defaults to ``60``
            seconds.

            .. versionadded:: 20.0
    Attributes:
        store_data (:class:`~telegram.ext.PersistenceInput`): Specifies which kinds of data will
            be saved by this persistence instance.
        bot (:class:`telegram.Bot`): The bot associated with the persistence.
    """

    __slots__ = (
        "_update_interval",
        "bot",
        "store_data",
    )

    def __init__(
        self,
        store_data: PersistenceInput | None = None,
        update_interval: float = 60,
    ):
        self.store_data: PersistenceInput = store_data or PersistenceInput()
        self._update_interval: float = update_interval

        self.bot: Bot = None  # type: ignore[assignment]

    @property
    def update_interval(self) -> float:
        """:obj:`float`: Time (in seconds) that the :class:`~telegram.ext.Application`
        will wait between two consecutive runs of updating the persistence.

        .. versionadded:: 20.0
        """
        return self._update_interval

    @update_interval.setter
    def update_interval(self, _: object) -> NoReturn:
        raise AttributeError(
            "You can not assign a new value to update_interval after initialization."
        )

    def set_bot(self, bot: Bot) -> None:
        """Set the Bot to be used by this persistence instance.

        Args:
            bot (:class:`telegram.Bot`): The bot.

        Raises:
            :exc:`TypeError`: If :attr:`PersistenceInput.callback_data` is :obj:`True` and the
                :paramref:`bot` is not an instance of :class:`telegram.ext.ExtBot`.
        """
        if self.store_data.callback_data and (not isinstance(bot, ExtBot)):
            raise TypeError("callback_data can only be stored when using telegram.ext.ExtBot.")

        self.bot = bot

    @abstractmethod
    async def get_user_data(self) -> dict[int, UD]:
        """Will be called by :class:`telegram.ext.Application` upon creation with a
        persistence object. It should return the ``user_data`` if stored, or an empty
        :obj:`dict`. In the latter case, the dictionary should produce values
        corresponding to one of the following:

        - :obj:`dict`
        - The type from :attr:`telegram.ext.ContextTypes.user_data`
          if :class:`telegram.ext.ContextTypes` is used.

        .. versionchanged:: 20.0
            This method may now return a :obj:`dict` instead of a :obj:`collections.defaultdict`

        Returns:
            dict[:obj:`int`, :obj:`dict` | :attr:`telegram.ext.ContextTypes.user_data`]:
                The restored user data.
        """

    @abstractmethod
    async def get_chat_data(self) -> dict[int, CD]:
        """Will be called by :class:`telegram.ext.Application` upon creation with a
        persistence object. It should return the ``chat_data`` if stored, or an empty
        :obj:`dict`. In the latter case, the dictionary should produce values
        corresponding to one of the following:

        - :obj:`dict`
        - The type from :attr:`telegram.ext.ContextTypes.chat_data`
          if :class:`telegram.ext.ContextTypes` is used.

        .. versionchanged:: 20.0
            This method may now return a :obj:`dict` instead of a :obj:`collections.defaultdict`

        Returns:
            dict[:obj:`int`, :obj:`dict` | :attr:`telegram.ext.ContextTypes.chat_data`]:
                The restored chat data.
        """

    @abstractmethod
    async def get_bot_data(self) -> BD:
        """Will be called by :class:`telegram.ext.Application` upon creation with a
        persistence object. It should return the ``bot_data`` if stored, or an empty
        :obj:`dict`. In the latter case, the :obj:`dict` should produce values
        corresponding to one of the following:

        - :obj:`dict`
        - The type from :attr:`telegram.ext.ContextTypes.bot_data`
          if :class:`telegram.ext.ContextTypes` are used.

        Returns:
            dict[:obj:`int`, :obj:`dict` | :attr:`telegram.ext.ContextTypes.bot_data`]:
                The restored bot data.
        """

    @abstractmethod
    async def get_callback_data(self) -> CDCData | None:
        """Will be called by :class:`telegram.ext.Application` upon creation with a
        persistence object. If callback data was stored, it should be returned.

        .. versionadded:: 13.6

        .. versionchanged:: 20.0
           Changed this method into an :external:func:`~abc.abstractmethod`.

        Returns:
            tuple[list[tuple[:obj:`str`, :obj:`float`, dict[:obj:`str`, :class:`object`]]],
            dict[:obj:`str`, :obj:`str`]] | :obj:`None`: The restored metadata or :obj:`None`,
            if no data was stored.
        """

    @abstractmethod
    async def get_conversations(self, name: str) -> ConversationDict:
        """Will be called by :class:`telegram.ext.Application` when a
        :class:`telegram.ext.ConversationHandler` is added if
        :attr:`telegram.ext.ConversationHandler.persistent` is :obj:`True`.
        It should return the conversations for the handler with :paramref:`name` or an empty
        :obj:`dict`.

        Args:
            name (:obj:`str`): The handlers name.

        Returns:
            :obj:`dict`: The restored conversations for the handler.
        """

    @abstractmethod
    async def update_conversation(
        self, name: str, key: ConversationKey, new_state: object | None
    ) -> None:
        """Will be called when a :class:`telegram.ext.ConversationHandler` changes states.
        This allows the storage of the new state in the persistence.

        Args:
            name (:obj:`str`): The handler's name.
            key (:obj:`tuple`): The key the state is changed for.
            new_state (:class:`object`): The new state for the given key.
        """

    @abstractmethod
    async def update_user_data(self, user_id: int, data: UD) -> None:
        """Will be called by the :class:`telegram.ext.Application` after a handler has
        handled an update.

        Args:
            user_id (:obj:`int`): The user the data might have been changed for.
            data (:obj:`dict` | :attr:`telegram.ext.ContextTypes.user_data`):
                The :attr:`telegram.ext.Application.user_data` ``[user_id]``.
        """

    @abstractmethod
    async def update_chat_data(self, chat_id: int, data: CD) -> None:
        """Will be called by the :class:`telegram.ext.Application` after a handler has
        handled an update.

        Args:
            chat_id (:obj:`int`): The chat the data might have been changed for.
            data (:obj:`dict` | :attr:`telegram.ext.ContextTypes.chat_data`):
                The :attr:`telegram.ext.Application.chat_data` ``[chat_id]``.
        """

    @abstractmethod
    async def update_bot_data(self, data: BD) -> None:
        """Will be called by the :class:`telegram.ext.Application` after a handler has
        handled an update.

        Args:
            data (:obj:`dict` | :attr:`telegram.ext.ContextTypes.bot_data`):
                The :attr:`telegram.ext.Application.bot_data`.
        """

    @abstractmethod
    async def update_callback_data(self, data: CDCData) -> None:
        """Will be called by the :class:`telegram.ext.Application` after a handler has
        handled an update.

        .. versionadded:: 13.6

        .. versionchanged:: 20.0
           Changed this method into an :external:func:`~abc.abstractmethod`.

        Args:
            data (tuple[list[tuple[:obj:`str`, :obj:`float`, \
                dict[:obj:`str`, :obj:`Any`]]], dict[:obj:`str`, :obj:`str`]] | :obj:`None`):
                The relevant data to restore :class:`telegram.ext.CallbackDataCache`.
        """

    @abstractmethod
    async def drop_chat_data(self, chat_id: int) -> None:
        """Will be called by the :class:`telegram.ext.Application`, when using
        :meth:`~telegram.ext.Application.drop_chat_data`.

        .. versionadded:: 20.0

        Args:
            chat_id (:obj:`int`): The chat id to delete from the persistence.
        """

    @abstractmethod
    async def drop_user_data(self, user_id: int) -> None:
        """Will be called by the :class:`telegram.ext.Application`, when using
        :meth:`~telegram.ext.Application.drop_user_data`.

        .. versionadded:: 20.0

        Args:
            user_id (:obj:`int`): The user id to delete from the persistence.
        """

    @abstractmethod
    async def refresh_user_data(self, user_id: int, user_data: UD) -> None:
        """Will be called by the :class:`telegram.ext.Application` before passing the
        :attr:`~telegram.ext.Application.user_data` to a callback. Can be used to update data
        stored in :attr:`~telegram.ext.Application.user_data` from an external source.

        Tip:
            This method is expected to edit the object :paramref:`user_data` in-place instead of
            returning a new object.

        Warning:
            When using :meth:`~telegram.ext.ApplicationBuilder.concurrent_updates`, this method
            may be called while a handler callback is still running. This might lead to race
            conditions.

        .. versionadded:: 13.6

        .. versionchanged:: 20.0
           Changed this method into an :external:func:`~abc.abstractmethod`.

        Args:
            user_id (:obj:`int`): The user ID this :attr:`~telegram.ext.Application.user_data` is
                associated with.
            user_data (:obj:`dict` | :attr:`telegram.ext.ContextTypes.user_data`):
                The ``user_data`` of a single user.
        """

    @abstractmethod
    async def refresh_chat_data(self, chat_id: int, chat_data: CD) -> None:
        """Will be called by the :class:`telegram.ext.Application` before passing the
        :attr:`~telegram.ext.Application.chat_data` to a callback. Can be used to update data
        stored in :attr:`~telegram.ext.Application.chat_data` from an external source.

        Tip:
            This method is expected to edit the object :paramref:`chat_data` in-place instead of
            returning a new object.

        Warning:
            When using :meth:`~telegram.ext.ApplicationBuilder.concurrent_updates`, this method
            may be called while a handler callback is still running. This might lead to race
            conditions.

        .. versionadded:: 13.6

        .. versionchanged:: 20.0
           Changed this method into an :external:func:`~abc.abstractmethod`.

        Args:
            chat_id (:obj:`int`): The chat ID this :attr:`~telegram.ext.Application.chat_data` is
                associated with.
            chat_data (:obj:`dict` | :attr:`telegram.ext.ContextTypes.chat_data`):
                The ``chat_data`` of a single chat.
        """

    @abstractmethod
    async def refresh_bot_data(self, bot_data: BD) -> None:
        """Will be called by the :class:`telegram.ext.Application` before passing the
        :attr:`~telegram.ext.Application.bot_data` to a callback. Can be used to update data stored
        in :attr:`~telegram.ext.Application.bot_data` from an external source.

        Tip:
            This method is expected to edit the object :paramref:`bot_data` in-place instead of
            returning a new object.

        Warning:
            When using :meth:`~telegram.ext.ApplicationBuilder.concurrent_updates`, this method
            may be called while a handler callback is still running. This might lead to race
            conditions.

        .. versionadded:: 13.6

        .. versionchanged:: 20.0
           Changed this method into an :external:func:`~abc.abstractmethod`.

        Args:
            bot_data (:obj:`dict` | :attr:`telegram.ext.ContextTypes.bot_data`):
                The ``bot_data``.
        """

    @abstractmethod
    async def flush(self) -> None:
        """Will be called by :meth:`telegram.ext.Application.stop`. Gives the
        persistence a chance to finish up saving or close a database connection gracefully.

        .. versionchanged:: 20.0
           Changed this method into an :external:func:`~abc.abstractmethod`.
        """
