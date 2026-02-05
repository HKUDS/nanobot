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
"""
This module contains filters for use with :class:`telegram.ext.MessageHandler`,
:class:`telegram.ext.CommandHandler`, or :class:`telegram.ext.PrefixHandler`.

.. versionchanged:: 20.0

    #. Filters are no longer callable, if you're using a custom filter and are calling an existing
       filter, then switch to the new syntax: ``filters.{filter}.check_update(update)``.
    #. Removed the ``Filters`` class. The filters are now directly attributes/classes of the
       :mod:`~telegram.ext.filters` module.
    #. The names of all filters has been updated:

       * Filter classes which are ready for use, e.g ``Filters.all`` are now capitalized, e.g
         ``filters.ALL``.
       * Filters which need to be initialized are now in CamelCase. E.g. ``filters.User(...)``.
       * Filters which do both (like ``Filters.text``) are now split as ready-to-use version
         ``filters.TEXT`` and class version ``filters.Text(...)``.

.. versionchanged:: 22.0
    Removed deprecated attribute `CHAT`.

"""

__all__ = (
    "ALL",
    "ANIMATION",
    "ATTACHMENT",
    "AUDIO",
    "BOOST_ADDED",
    "CAPTION",
    "CHECKLIST",
    "COMMAND",
    "CONTACT",
    "DIRECT_MESSAGES",
    "EFFECT_ID",
    "FORUM",
    "FORWARDED",
    "GAME",
    "GIVEAWAY",
    "GIVEAWAY_WINNERS",
    "HAS_MEDIA_SPOILER",
    "HAS_PROTECTED_CONTENT",
    "INVOICE",
    "IS_AUTOMATIC_FORWARD",
    "IS_FROM_OFFLINE",
    "IS_TOPIC_MESSAGE",
    "LOCATION",
    "PAID_MEDIA",
    "PASSPORT_DATA",
    "PHOTO",
    "POLL",
    "PREMIUM_USER",
    "REPLY",
    "REPLY_TO_STORY",
    "SENDER_BOOST_COUNT",
    "STORY",
    "SUCCESSFUL_PAYMENT",
    "SUGGESTED_POST_INFO",
    "TEXT",
    "USER",
    "USER_ATTACHMENT",
    "VENUE",
    "VIA_BOT",
    "VIDEO",
    "VIDEO_NOTE",
    "VOICE",
    "BaseFilter",
    "Caption",
    "CaptionEntity",
    "CaptionRegex",
    "Chat",
    "ChatType",
    "Command",
    "Dice",
    "Document",
    "Entity",
    "ForwardedFrom",
    "Language",
    "Mention",
    "MessageFilter",
    "Regex",
    "SenderChat",
    "StatusUpdate",
    "Sticker",
    "SuccessfulPayment",
    "Text",
    "UpdateFilter",
    "UpdateType",
    "User",
    "ViaBot",
)
import mimetypes
import re
from abc import ABC, abstractmethod
from collections.abc import Collection, Iterable, Sequence
from re import Match, Pattern
from typing import NoReturn, cast

from telegram import Chat as TGChat
from telegram import (
    Message,
    MessageEntity,
    MessageOriginChannel,
    MessageOriginChat,
    MessageOriginUser,
    Update,
)
from telegram import User as TGUser
from telegram._utils.types import SCT
from telegram.constants import DiceEmoji as DiceEmojiEnum
from telegram.ext._utils._update_parsing import parse_chat_id, parse_username
from telegram.ext._utils.types import FilterDataDict


class BaseFilter:
    """Base class for all Filters.

    Filters subclassing from this class can combined using bitwise operators:

    And::

        filters.TEXT & filters.Entity(MENTION)

    Or::

        filters.AUDIO | filters.VIDEO

    Exclusive Or::

        filters.Regex('To Be') ^ filters.Regex('Not 2B')

    Not::

        ~ filters.COMMAND

    Also works with more than two filters::

        filters.TEXT & (filters.Entity("url") | filters.Entity("text_link"))
        filters.TEXT & (~ filters.FORWARDED)

    Note:
        Filters use the same short circuiting logic as python's :keyword:`and`, :keyword:`or` and
        :keyword:`not`. This means that for example::

            filters.Regex(r'(a?x)') | filters.Regex(r'(b?x)')

        With ``message.text == 'x'``, will only ever return the matches for the first filter,
        since the second one is never evaluated.

    If you want to create your own filters create a class inheriting from either
    :class:`MessageFilter` or :class:`UpdateFilter` and implement a ``filter()``
    method that returns a boolean: :obj:`True` if the message should be
    handled, :obj:`False` otherwise.
    Note that the filters work only as class instances, not actual class objects (so remember to
    initialize your filter classes).

    By default, the filters name (what will get printed when converted to a string for display)
    will be the class name. If you want to overwrite this assign a better name to the :attr:`name`
    class variable.

    .. versionadded:: 20.0
        Added the arguments :attr:`name` and :attr:`data_filter`.

    Args:
        name (:obj:`str`): Name for this filter. Defaults to the type of filter.
        data_filter (:obj:`bool`): Whether this filter is a data filter. A data filter should
            return a dict with lists. The dict will be merged with
            :class:`telegram.ext.CallbackContext`'s internal dict in most cases
            (depends on the handler).
    """

    __slots__ = ("_data_filter", "_name")

    def __init__(self, name: str | None = None, data_filter: bool = False):
        self._name = self.__class__.__name__ if name is None else name
        self._data_filter = data_filter

    def __and__(self, other: "BaseFilter") -> "BaseFilter":
        """Defines `AND` bitwise operator for :class:`BaseFilter` object.
        The combined filter accepts an update only if it is accepted by both filters.
        For example, ``filters.PHOTO & filters.CAPTION`` will only accept messages that contain
        both a photo and a caption.

        Returns:
           :obj:`BaseFilter`
        """
        return _MergedFilter(self, and_filter=other)

    def __or__(self, other: "BaseFilter") -> "BaseFilter":
        """Defines `OR` bitwise operator for :class:`BaseFilter` object.
        The combined filter accepts an update only if it is accepted by any of the filters.
        For example, ``filters.PHOTO | filters.CAPTION`` will only accept messages that contain
        photo or caption or both.

        Returns:
           :obj:`BaseFilter`
        """
        return _MergedFilter(self, or_filter=other)

    def __xor__(self, other: "BaseFilter") -> "BaseFilter":
        """Defines `XOR` bitwise operator for :class:`BaseFilter` object.
        The combined filter accepts an update only if it is accepted by any of the filters and
        not both of them. For example, ``filters.PHOTO ^ filters.CAPTION`` will only accept
        messages that contain photo or caption, not both of them.

        Returns:
           :obj:`BaseFilter`
        """
        return _XORFilter(self, other)

    def __invert__(self) -> "BaseFilter":
        """Defines `NOT` bitwise operator for :class:`BaseFilter` object.
        The combined filter accepts an update only if it is accepted by any of the filters.
        For example, ``~ filters.PHOTO`` will only accept messages that do not contain photo.

        Returns:
           :obj:`BaseFilter`
        """
        return _InvertedFilter(self)

    def __repr__(self) -> str:
        """Gives name for this filter.

        .. seealso::
               :meth:`name`

        Returns:
            :obj:`str`:
        """
        return self.name

    @property
    def data_filter(self) -> bool:
        """:obj:`bool`: Whether this filter is a data filter."""
        return self._data_filter

    @data_filter.setter
    def data_filter(self, value: bool) -> None:
        self._data_filter = value

    @property
    def name(self) -> str:
        """:obj:`str`: Name for this filter."""
        return self._name

    @name.setter
    def name(self, name: str) -> None:
        self._name = name

    def check_update(self, update: Update) -> bool | FilterDataDict | None:
        """Checks if the specified update should be handled by this filter.

        .. versionchanged:: 21.1
            This filter now also returns :obj:`True` if the update contains
            :attr:`~telegram.Update.business_message`
            or :attr:`~telegram.Update.edited_business_message`.

        Args:
            update (:class:`telegram.Update`): The update to check.

        Returns:
            :obj:`bool`: :obj:`True` if the update contains one of
            :attr:`~telegram.Update.channel_post`, :attr:`~telegram.Update.message`,
            :attr:`~telegram.Update.edited_channel_post`,
            :attr:`~telegram.Update.edited_message`, :attr:`telegram.Update.business_message`,
            :attr:`telegram.Update.edited_business_message`, or :obj:`False` otherwise.
        """
        return bool(  # Only message updates should be handled.
            update.channel_post
            or update.message
            or update.edited_channel_post
            or update.edited_message
            or update.business_message
            or update.edited_business_message
        )


class MessageFilter(BaseFilter):
    """Base class for all Message Filters. In contrast to :class:`UpdateFilter`, the object passed
    to :meth:`filter` is :attr:`telegram.Update.effective_message`.

    Please see :class:`BaseFilter` for details on how to create custom filters.

    .. seealso:: :wiki:`Advanced Filters <Extensions---Advanced-Filters>`

    """

    __slots__ = ()

    def check_update(self, update: Update) -> bool | FilterDataDict | None:
        """Checks if the specified update should be handled by this filter by passing
        :attr:`~telegram.Update.effective_message` to :meth:`filter`.

        Args:
            update (:class:`telegram.Update`): The update to check.

        Returns:
            :obj:`bool` | dict[:obj:`str`, :obj:`list`] | :obj:`None`: If the update should be
            handled by this filter, returns :obj:`True` or a dict with lists, in case the filter
            is a data filter. If the update should not be handled by this filter, :obj:`False` or
            :obj:`None`.
        """
        if super().check_update(update):
            return self.filter(update.effective_message)  # type: ignore[arg-type]
        return False

    @abstractmethod
    def filter(self, message: Message) -> bool | FilterDataDict | None:
        """This method must be overwritten.

        Args:
            message (:class:`telegram.Message`): The message that is tested.

        Returns:
            :obj:`dict` or :obj:`bool`

        """


class UpdateFilter(BaseFilter):
    """Base class for all Update Filters. In contrast to :class:`MessageFilter`, the object
    passed to :meth:`filter` is an instance of :class:`telegram.Update`, which allows to create
    filters like :attr:`telegram.ext.filters.UpdateType.EDITED_MESSAGE`.

    Please see :class:`telegram.ext.filters.BaseFilter` for details on how to create custom
    filters.

    """

    __slots__ = ()

    def check_update(self, update: Update) -> bool | FilterDataDict | None:
        """Checks if the specified update should be handled by this filter.

        Args:
            update (:class:`telegram.Update`): The update to check.

        Returns:
            :obj:`bool` | dict[:obj:`str`, :obj:`list`] | :obj:`None`: If the update should be
            handled by this filter, returns :obj:`True` or a dict with lists, in case the filter
            is a data filter. If the update should not be handled by this filter, :obj:`False` or
            :obj:`None`.
        """
        return self.filter(update) if super().check_update(update) else False

    @abstractmethod
    def filter(self, update: Update) -> bool | FilterDataDict | None:
        """This method must be overwritten.

        Args:
            update (:class:`telegram.Update`): The update that is tested.

        Returns:
            :obj:`dict` or :obj:`bool`.

        """


class _InvertedFilter(UpdateFilter):
    """Represents a filter that has been inverted.

    Args:
        f: The filter to invert.

    """

    __slots__ = ("inv_filter",)

    def __init__(self, f: BaseFilter):
        super().__init__()
        self.inv_filter = f

    def filter(self, update: Update) -> bool:
        return not bool(self.inv_filter.check_update(update))

    @property
    def name(self) -> str:
        return f"<inverted {self.inv_filter}>"

    @name.setter
    def name(self, _: str) -> NoReturn:
        raise RuntimeError("Cannot set name for combined filters.")


class _MergedFilter(UpdateFilter):
    """Represents a filter consisting of two other filters.

    Args:
        base_filter: Filter 1 of the merged filter.
        and_filter: Optional filter to "and" with base_filter. Mutually exclusive with or_filter.
        or_filter: Optional filter to "or" with base_filter. Mutually exclusive with and_filter.

    """

    __slots__ = ("and_filter", "base_filter", "or_filter")

    def __init__(
        self,
        base_filter: BaseFilter,
        and_filter: BaseFilter | None = None,
        or_filter: BaseFilter | None = None,
    ):
        super().__init__()
        self.base_filter = base_filter
        if self.base_filter.data_filter:
            self.data_filter = True
        self.and_filter = and_filter
        if (
            self.and_filter
            and not isinstance(self.and_filter, bool)
            and self.and_filter.data_filter
        ):
            self.data_filter = True
        self.or_filter = or_filter
        if self.or_filter and not isinstance(self.and_filter, bool) and self.or_filter.data_filter:
            self.data_filter = True

    @staticmethod
    def _merge(base_output: bool | dict, comp_output: bool | dict) -> FilterDataDict:
        base = base_output if isinstance(base_output, dict) else {}
        comp = comp_output if isinstance(comp_output, dict) else {}
        for k in comp:
            # Make sure comp values are lists
            comp_value = comp[k] if isinstance(comp[k], list) else []
            try:
                # If base is a list then merge
                if isinstance(base[k], list):
                    base[k] += comp_value
                else:
                    base[k] = [base[k], *comp_value]
            except KeyError:
                base[k] = comp_value
        return base

    # pylint: disable=too-many-return-statements
    def filter(self, update: Update) -> bool | FilterDataDict:
        base_output = self.base_filter.check_update(update)
        # We need to check if the filters are data filters and if so return the merged data.
        # If it's not a data filter or an or_filter but no matches return bool
        if self.and_filter:
            # And filter needs to short circuit if base is falsy
            if base_output:
                comp_output = self.and_filter.check_update(update)
                if comp_output:
                    if self.data_filter:
                        merged = self._merge(base_output, comp_output)
                        if merged:
                            return merged
                    return True
        elif self.or_filter:
            # Or filter needs to short circuit if base is truthy
            if base_output:
                if self.data_filter:
                    return base_output
                return True

            comp_output = self.or_filter.check_update(update)
            if comp_output:
                if self.data_filter:
                    return comp_output
                return True
        return False

    @property
    def name(self) -> str:
        return (
            f"<{self.base_filter} {'and' if self.and_filter else 'or'} "
            f"{self.and_filter or self.or_filter}>"
        )

    @name.setter
    def name(self, _: str) -> NoReturn:
        raise RuntimeError("Cannot set name for combined filters.")


class _XORFilter(UpdateFilter):
    """Convenience filter acting as wrapper for :class:`MergedFilter` representing the an XOR gate
    for two filters.

    Args:
        base_filter: Filter 1 of the merged filter.
        xor_filter: Filter 2 of the merged filter.

    """

    __slots__ = ("base_filter", "merged_filter", "xor_filter")

    def __init__(self, base_filter: BaseFilter, xor_filter: BaseFilter):
        super().__init__()
        self.base_filter = base_filter
        self.xor_filter = xor_filter
        self.merged_filter = (base_filter & ~xor_filter) | (~base_filter & xor_filter)

    def filter(self, update: Update) -> bool | FilterDataDict | None:
        return self.merged_filter.check_update(update)

    @property
    def name(self) -> str:
        return f"<{self.base_filter} xor {self.xor_filter}>"

    @name.setter
    def name(self, _: str) -> NoReturn:
        raise RuntimeError("Cannot set name for combined filters.")


class _All(MessageFilter):
    __slots__ = ()

    def filter(self, message: Message) -> bool:  # noqa: ARG002
        return True


ALL = _All(name="filters.ALL")  # pylint: disable=invalid-name
"""All Messages."""


class _Animation(MessageFilter):
    __slots__ = ()

    def filter(self, message: Message) -> bool:
        return bool(message.animation)


ANIMATION = _Animation(name="filters.ANIMATION")
"""Messages that contain :attr:`telegram.Message.animation`."""


class _Attachment(MessageFilter):
    __slots__ = ()

    def filter(self, message: Message) -> bool:
        return bool(message.effective_attachment)


ATTACHMENT = _Attachment(name="filters.ATTACHMENT")
"""Messages that contain :meth:`telegram.Message.effective_attachment`.

.. versionadded:: 13.6"""


class _Audio(MessageFilter):
    __slots__ = ()

    def filter(self, message: Message) -> bool:
        return bool(message.audio)


AUDIO = _Audio(name="filters.AUDIO")  # pylint: disable=invalid-name
"""Messages that contain :attr:`telegram.Message.audio`."""


class Caption(MessageFilter):
    """Messages with a caption. If a list of strings is passed, it filters messages to only
    allow those whose caption is appearing in the given list.

    Examples:
        ``MessageHandler(filters.Caption(['PTB rocks!', 'PTB']), callback_method_2)``

    .. seealso::
        :attr:`telegram.ext.filters.CAPTION`

    Args:
        strings (list[:obj:`str`] | tuple[:obj:`str`], optional): Which captions to allow. Only
            exact matches are allowed. If not specified, will allow any message with a caption.
    """

    __slots__ = ("strings",)

    def __init__(self, strings: list[str] | tuple[str, ...] | None = None):
        self.strings: Sequence[str] | None = strings
        super().__init__(name=f"filters.Caption({strings})" if strings else "filters.CAPTION")

    def filter(self, message: Message) -> bool:
        if self.strings is None:
            return bool(message.caption)
        return message.caption in self.strings if message.caption else False


CAPTION = Caption()
"""Shortcut for :class:`telegram.ext.filters.Caption()`.

Examples:
    To allow any caption, simply use ``MessageHandler(filters.CAPTION, callback_method)``.
"""


class CaptionEntity(MessageFilter):
    """
    Filters media messages to only allow those which have a :class:`telegram.MessageEntity`
    where their :class:`~telegram.MessageEntity.type` matches `entity_type`.

    Examples:
        ``MessageHandler(filters.CaptionEntity("hashtag"), callback_method)``

    Args:
        entity_type (:obj:`str`): Caption Entity type to check for. All types can be found as
            constants in :class:`telegram.MessageEntity`.

    """

    __slots__ = ("entity_type",)

    def __init__(self, entity_type: str):
        self.entity_type: str = entity_type
        super().__init__(name=f"filters.CaptionEntity({self.entity_type})")

    def filter(self, message: Message) -> bool:
        return any(entity.type == self.entity_type for entity in message.caption_entities)


class CaptionRegex(MessageFilter):
    """
    Filters updates by searching for an occurrence of :paramref:`~CaptionRegex.pattern` in the
    message caption.

    This filter works similarly to :class:`Regex`, with the only exception being that
    it applies to the message caption instead of the text.

    Examples:
        Use ``MessageHandler(filters.PHOTO & filters.CaptionRegex(r'help'), callback)``
        to capture all photos with caption containing the word 'help'.

    Note:
        This filter will not work on simple text messages, but only on media with caption.

    Args:
        pattern (:obj:`str` | :func:`re.Pattern <re.compile>`): The regex pattern.
    """

    __slots__ = ("pattern",)

    def __init__(self, pattern: str | Pattern[str]):
        if isinstance(pattern, str):
            pattern = re.compile(pattern)
        self.pattern: Pattern[str] = pattern
        super().__init__(name=f"filters.CaptionRegex({self.pattern})", data_filter=True)

    def filter(self, message: Message) -> dict[str, list[Match[str]]] | None:
        if message.caption and (match := self.pattern.search(message.caption)):
            return {"matches": [match]}
        return {}


class _ChatUserBaseFilter(MessageFilter, ABC):
    __slots__ = (
        "_chat_id_name",
        "_chat_ids",
        "_username_name",
        "_usernames",
        "allow_empty",
    )

    def __init__(
        self,
        chat_id: SCT[int] | None = None,
        username: SCT[str] | None = None,
        allow_empty: bool = False,
    ):
        super().__init__()
        self._chat_id_name: str = "chat_id"
        self._username_name: str = "username"
        self.allow_empty: bool = allow_empty

        self._chat_ids: set[int] = set()
        self._usernames: set[str] = set()

        self._set_chat_ids(chat_id)
        self._set_usernames(username)

    @abstractmethod
    def _get_chat_or_user(self, message: Message) -> TGChat | TGUser | None: ...

    def _set_chat_ids(self, chat_id: SCT[int] | None) -> None:
        if chat_id and self._usernames:
            raise RuntimeError(
                f"Can't set {self._chat_id_name} in conjunction with (already set) "
                f"{self._username_name}s."
            )
        self._chat_ids = set(parse_chat_id(chat_id))

    def _set_usernames(self, username: SCT[str] | None) -> None:
        if username and self._chat_ids:
            raise RuntimeError(
                f"Can't set {self._username_name} in conjunction with (already set) "
                f"{self._chat_id_name}s."
            )
        self._usernames = set(parse_username(username))

    @property
    def chat_ids(self) -> frozenset[int]:
        return frozenset(self._chat_ids)

    @chat_ids.setter
    def chat_ids(self, chat_id: SCT[int]) -> None:
        self._set_chat_ids(chat_id)

    @property
    def usernames(self) -> frozenset[str]:
        """Which username(s) to allow through.

        Warning:
            :attr:`usernames` will give a *copy* of the saved usernames as :obj:`frozenset`. This
            is to ensure thread safety. To add/remove a user, you should use :meth:`add_usernames`,
            and :meth:`remove_usernames`. Only update the entire set by
            ``filter.usernames = new_set``, if you are entirely sure that it is not causing race
            conditions, as this will complete replace the current set of allowed users.

        Returns:
            frozenset(:obj:`str`)
        """
        return frozenset(self._usernames)

    @usernames.setter
    def usernames(self, username: SCT[str]) -> None:
        self._set_usernames(username)

    def add_usernames(self, username: SCT[str]) -> None:
        """
        Add one or more chats to the allowed usernames.

        Args:
            username(:obj:`str` | Collection[:obj:`str`]): Which username(s) to
                allow through. Leading ``'@'`` s in usernames will be discarded.
        """
        if self._chat_ids:
            raise RuntimeError(
                f"Can't set {self._username_name} in conjunction with (already set) "
                f"{self._chat_id_name}s."
            )

        parsed_username = set(parse_username(username))
        self._usernames |= parsed_username

    def _add_chat_ids(self, chat_id: SCT[int]) -> None:
        if self._usernames:
            raise RuntimeError(
                f"Can't set {self._chat_id_name} in conjunction with (already set) "
                f"{self._username_name}s."
            )

        parsed_chat_id = set(parse_chat_id(chat_id))

        self._chat_ids |= parsed_chat_id

    def remove_usernames(self, username: SCT[str]) -> None:
        """
        Remove one or more chats from allowed usernames.

        Args:
            username(:obj:`str` | Collection[:obj:`str`]): Which username(s) to
                disallow through. Leading ``'@'`` s in usernames will be discarded.
        """
        if self._chat_ids:
            raise RuntimeError(
                f"Can't set {self._username_name} in conjunction with (already set) "
                f"{self._chat_id_name}s."
            )

        parsed_username = set(parse_username(username))
        self._usernames -= parsed_username

    def _remove_chat_ids(self, chat_id: SCT[int]) -> None:
        if self._usernames:
            raise RuntimeError(
                f"Can't set {self._chat_id_name} in conjunction with (already set) "
                f"{self._username_name}s."
            )
        parsed_chat_id = set(parse_chat_id(chat_id))
        self._chat_ids -= parsed_chat_id

    def filter(self, message: Message) -> bool:
        chat_or_user = self._get_chat_or_user(message)
        if chat_or_user:
            if self.chat_ids:
                return chat_or_user.id in self.chat_ids
            if self.usernames:
                return bool(chat_or_user.username and chat_or_user.username in self.usernames)
            return self.allow_empty
        return False

    @property
    def name(self) -> str:
        return (
            f"filters.{self.__class__.__name__}("
            f"{', '.join(str(s) for s in (self.usernames or self.chat_ids))})"
        )

    @name.setter
    def name(self, _: str) -> NoReturn:
        raise RuntimeError(f"Cannot set name for filters.{self.__class__.__name__}")


class Chat(_ChatUserBaseFilter):
    """Filters messages to allow only those which are from a specified chat ID or username.

    Examples:
        ``MessageHandler(filters.Chat(-1234), callback_method)``

    Warning:
        :attr:`chat_ids` will give a *copy* of the saved chat ids as :class:`frozenset`. This
        is to ensure thread safety. To add/remove a chat, you should use :meth:`add_chat_ids`, and
        :meth:`remove_chat_ids`. Only update the entire set by ``filter.chat_ids = new_set``,
        if you are entirely sure that it is not causing race conditions, as this will complete
        replace the current set of allowed chats.

    Args:
        chat_id(:obj:`int` | Collection[:obj:`int`], optional):
            Which chat ID(s) to allow through.
        username(:obj:`str` | Collection[:obj:`str`], optional):
            Which username(s) to allow through.
            Leading ``'@'`` s in usernames will be discarded.
        allow_empty(:obj:`bool`, optional): Whether updates should be processed, if no chat
            is specified in :attr:`chat_ids` and :attr:`usernames`. Defaults to :obj:`False`.

    Attributes:
        chat_ids (set(:obj:`int`)): Which chat ID(s) to allow through.
        allow_empty (:obj:`bool`): Whether updates should be processed, if no chat
            is specified in :attr:`chat_ids` and :attr:`usernames`.

    Raises:
        RuntimeError: If ``chat_id`` and ``username`` are both present.
    """

    __slots__ = ()

    def _get_chat_or_user(self, message: Message) -> TGChat | None:
        return message.chat

    def add_chat_ids(self, chat_id: SCT[int]) -> None:
        """
        Add one or more chats to the allowed chat ids.

        Args:
            chat_id(:obj:`int` | Collection[:obj:`int`]): Which chat ID(s) to allow
                through.
        """
        return super()._add_chat_ids(chat_id)

    def remove_chat_ids(self, chat_id: SCT[int]) -> None:
        """
        Remove one or more chats from allowed chat ids.

        Args:
            chat_id(:obj:`int` | Collection[:obj:`int`]): Which chat ID(s) to
                disallow through.
        """
        return super()._remove_chat_ids(chat_id)


class ChatType:  # A convenience namespace for Chat types.
    """Subset for filtering the type of chat.

    Examples:
        Use these filters like: ``filters.ChatType.CHANNEL`` or
        ``filters.ChatType.SUPERGROUP`` etc.

    Caution:
        ``filters.ChatType`` itself is *not* a filter, but just a convenience namespace.
    """

    __slots__ = ()

    class _Channel(MessageFilter):
        __slots__ = ()

        def filter(self, message: Message) -> bool:
            return message.chat.type == TGChat.CHANNEL

    CHANNEL = _Channel(name="filters.ChatType.CHANNEL")
    """Updates from channel."""

    class _Group(MessageFilter):
        __slots__ = ()

        def filter(self, message: Message) -> bool:
            return message.chat.type == TGChat.GROUP

    GROUP = _Group(name="filters.ChatType.GROUP")
    """Updates from group."""

    class _Groups(MessageFilter):
        __slots__ = ()

        def filter(self, message: Message) -> bool:
            return message.chat.type in [TGChat.GROUP, TGChat.SUPERGROUP]

    GROUPS = _Groups(name="filters.ChatType.GROUPS")
    """Update from group *or* supergroup."""

    class _Private(MessageFilter):
        __slots__ = ()

        def filter(self, message: Message) -> bool:
            return message.chat.type == TGChat.PRIVATE

    PRIVATE = _Private(name="filters.ChatType.PRIVATE")
    """Update from private chats."""

    class _SuperGroup(MessageFilter):
        __slots__ = ()

        def filter(self, message: Message) -> bool:
            return message.chat.type == TGChat.SUPERGROUP

    SUPERGROUP = _SuperGroup(name="filters.ChatType.SUPERGROUP")
    """Updates from supergroup."""


class _Checklist(MessageFilter):
    __slots__ = ()

    def filter(self, message: Message) -> bool:
        return bool(message.checklist)


CHECKLIST = _Checklist(name="filters.CHECKLIST")
"""Messages that contain :attr:`telegram.Message.checklist`.

.. versionadded:: 22.3
"""


class Command(MessageFilter):
    """
    Messages with a :attr:`telegram.MessageEntity.BOT_COMMAND`. By default, only allows
    messages `starting` with a bot command. Pass :obj:`False` to also allow messages that contain a
    bot command `anywhere` in the text.

    Examples:
        ``MessageHandler(filters.Command(False), command_anywhere_callback)``

    .. seealso::
        :attr:`telegram.ext.filters.COMMAND`.

    Note:
        :attr:`telegram.ext.filters.TEXT` also accepts messages containing a command.

    Args:
        only_start (:obj:`bool`, optional): Whether to only allow messages that `start` with a bot
            command. Defaults to :obj:`True`.
    """

    __slots__ = ("only_start",)

    def __init__(self, only_start: bool = True):
        self.only_start: bool = only_start
        super().__init__(f"filters.Command({only_start})" if not only_start else "filters.COMMAND")

    def filter(self, message: Message) -> bool:
        if not message.entities:
            return False

        first = message.entities[0]

        if self.only_start:
            return bool(first.type == MessageEntity.BOT_COMMAND and first.offset == 0)
        return bool(any(e.type == MessageEntity.BOT_COMMAND for e in message.entities))


COMMAND = Command()
"""Shortcut for :class:`telegram.ext.filters.Command()`.

Examples:
    To allow messages starting with a command use
    ``MessageHandler(filters.COMMAND, command_at_start_callback)``.
"""


class _Contact(MessageFilter):
    __slots__ = ()

    def filter(self, message: Message) -> bool:
        return bool(message.contact)


CONTACT = _Contact(name="filters.CONTACT")
"""Messages that contain :attr:`telegram.Message.contact`."""


class _Dice(MessageFilter):
    __slots__ = ("emoji", "values")

    def __init__(self, values: SCT[int] | None = None, emoji: DiceEmojiEnum | None = None):
        super().__init__()
        self.emoji: DiceEmojiEnum | None = emoji
        self.values: Collection[int] | None = [values] if isinstance(values, int) else values

        if emoji:  # for filters.Dice.BASKETBALL
            self.name = f"filters.Dice.{emoji.name}"
            if self.values and emoji:  # for filters.Dice.Dice(4)  SLOT_MACHINE -> SlotMachine
                self.name = f"filters.Dice.{emoji.name.title().replace('_', '')}({self.values})"
        elif values:  # for filters.Dice(4)
            self.name = f"filters.Dice({self.values})"
        else:
            self.name = "filters.Dice.ALL"

    def filter(self, message: Message) -> bool:
        if not (dice := message.dice):  # no dice
            return False

        if self.emoji:
            emoji_match = dice.emoji == self.emoji
            if self.values:
                return dice.value in self.values and emoji_match  # emoji and value
            return emoji_match  # emoji, no value
        return dice.value in self.values if self.values else True  # no emoji, only value


class Dice(_Dice):
    """Dice Messages. If an integer or a list of integers is passed, it filters messages to only
    allow those whose dice value is appearing in the given list.

    .. versionadded:: 13.4

    Examples:
        To allow any dice message, simply use
        ``MessageHandler(filters.Dice.ALL, callback_method)``.

        To allow any dice message, but with value 3 `or` 4, use
        ``MessageHandler(filters.Dice([3, 4]), callback_method)``

        To allow only dice messages with the emoji 🎲, but any value, use
        ``MessageHandler(filters.Dice.DICE, callback_method)``.

        To allow only dice messages with the emoji 🎯 and with value 6, use
        ``MessageHandler(filters.Dice.Darts(6), callback_method)``.

        To allow only dice messages with the emoji ⚽ and with value 5 `or` 6, use
        ``MessageHandler(filters.Dice.Football([5, 6]), callback_method)``.

    Note:
        Dice messages don't have text. If you want to filter either text or dice messages, use
        ``filters.TEXT | filters.Dice.ALL``.

    Args:
        values (:obj:`int` | Collection[:obj:`int`], optional):
            Which values to allow. If not specified, will allow the specified dice message.
    """

    __slots__ = ()

    ALL = _Dice()
    """Dice messages with any value and any emoji."""

    class Basketball(_Dice):
        """Dice messages with the emoji 🏀. Supports passing a list of integers.

        Args:
            values (:obj:`int` | Collection[:obj:`int`]): Which values to allow.
        """

        __slots__ = ()

        def __init__(self, values: SCT[int]):
            super().__init__(values, emoji=DiceEmojiEnum.BASKETBALL)

    BASKETBALL = _Dice(emoji=DiceEmojiEnum.BASKETBALL)
    """Dice messages with the emoji 🏀. Matches any dice value."""

    class Bowling(_Dice):
        """Dice messages with the emoji 🎳. Supports passing a list of integers.

        Args:
            values (:obj:`int` | Collection[:obj:`int`]): Which values to allow.
        """

        __slots__ = ()

        def __init__(self, values: SCT[int]):
            super().__init__(values, emoji=DiceEmojiEnum.BOWLING)

    BOWLING = _Dice(emoji=DiceEmojiEnum.BOWLING)
    """Dice messages with the emoji 🎳. Matches any dice value."""

    class Darts(_Dice):
        """Dice messages with the emoji 🎯. Supports passing a list of integers.

        Args:
            values (:obj:`int` | Collection[:obj:`int`]): Which values to allow.
        """

        __slots__ = ()

        def __init__(self, values: SCT[int]):
            super().__init__(values, emoji=DiceEmojiEnum.DARTS)

    DARTS = _Dice(emoji=DiceEmojiEnum.DARTS)
    """Dice messages with the emoji 🎯. Matches any dice value."""

    class Dice(_Dice):
        """Dice messages with the emoji 🎲. Supports passing a list of integers.

        Args:
            values (:obj:`int` | Collection[:obj:`int`]): Which values to allow.
        """

        __slots__ = ()

        def __init__(self, values: SCT[int]):
            super().__init__(values, emoji=DiceEmojiEnum.DICE)

    DICE = _Dice(emoji=DiceEmojiEnum.DICE)
    """Dice messages with the emoji 🎲. Matches any dice value."""

    class Football(_Dice):
        """Dice messages with the emoji ⚽. Supports passing a list of integers.

        Args:
            values (:obj:`int` | Collection[:obj:`int`]): Which values to allow.
        """

        __slots__ = ()

        def __init__(self, values: SCT[int]):
            super().__init__(values, emoji=DiceEmojiEnum.FOOTBALL)

    FOOTBALL = _Dice(emoji=DiceEmojiEnum.FOOTBALL)
    """Dice messages with the emoji ⚽. Matches any dice value."""

    class SlotMachine(_Dice):
        """Dice messages with the emoji 🎰. Supports passing a list of integers.

        Args:
            values (:obj:`int` | Collection[:obj:`int`]): Which values to allow.
        """

        __slots__ = ()

        def __init__(self, values: SCT[int]):
            super().__init__(values, emoji=DiceEmojiEnum.SLOT_MACHINE)

    SLOT_MACHINE = _Dice(emoji=DiceEmojiEnum.SLOT_MACHINE)
    """Dice messages with the emoji 🎰. Matches any dice value."""


class _DirectMessages(UpdateFilter):
    __slots__ = ()

    def filter(self, update: Update) -> bool:
        return bool(update.effective_chat and update.effective_chat.is_direct_messages)


DIRECT_MESSAGES = _DirectMessages(name="filters.DIRECT_MESSAGES")
"""Filter chats which are the direct messages for a channel.

.. seealso:: :attr:`telegram.Chat.is_direct_messages`

.. versionadded:: 22.4
"""


class Document:
    """
    Subset for messages containing a document/file.

    Examples:
        Use these filters like: ``filters.Document.MP3``,
        ``filters.Document.MimeType("text/plain")`` etc. Or just use ``filters.Document.ALL`` for
        all document messages.

    Caution:
        ``filters.Document`` itself is *not* a filter, but just a convenience namespace.
    """

    __slots__ = ()

    class _All(MessageFilter):
        __slots__ = ()

        def filter(self, message: Message) -> bool:
            return bool(message.document)

    ALL = _All(name="filters.Document.ALL")
    """Messages that contain a :attr:`telegram.Message.document`."""

    class Category(MessageFilter):
        """Filters documents by their category in the mime-type attribute.

        Args:
            category (:obj:`str`): Category of the media you want to filter.

        Example:
            ``filters.Document.Category('audio/')`` returns :obj:`True` for all types
            of audio sent as a file, for example ``'audio/mpeg'`` or ``'audio/x-wav'``.

        Note:
            This Filter only filters by the mime_type of the document, it doesn't check the
            validity of the document. The user can manipulate the mime-type of a message and
            send media with wrong types that don't fit to this handler.
        """

        __slots__ = ("_category",)

        def __init__(self, category: str):
            self._category = category
            super().__init__(name=f"filters.Document.Category('{self._category}')")

        def filter(self, message: Message) -> bool:
            if message.document and message.document.mime_type:
                return message.document.mime_type.startswith(self._category)
            return False

    APPLICATION = Category("application/")
    """Use as ``filters.Document.APPLICATION``."""
    AUDIO = Category("audio/")
    """Use as ``filters.Document.AUDIO``."""
    IMAGE = Category("image/")
    """Use as ``filters.Document.IMAGE``."""
    VIDEO = Category("video/")
    """Use as ``filters.Document.VIDEO``."""
    TEXT = Category("text/")
    """Use as ``filters.Document.TEXT``."""

    class FileExtension(MessageFilter):
        """This filter filters documents by their file ending/extension.

        Args:
            file_extension (:obj:`str` | :obj:`None`): Media file extension you want to filter.
            case_sensitive (:obj:`bool`, optional): Pass :obj:`True` to make the filter case
                sensitive. Default: :obj:`False`.

        Example:
            * ``filters.Document.FileExtension("jpg")``
              filters files with extension ``".jpg"``.
            * ``filters.Document.FileExtension(".jpg")``
              filters files with extension ``"..jpg"``.
            * ``filters.Document.FileExtension("Dockerfile", case_sensitive=True)``
              filters files with extension ``".Dockerfile"`` minding the case.
            * ``filters.Document.FileExtension(None)``
              filters files without a dot in the filename.

        Note:
            * This Filter only filters by the file ending/extension of the document,
              it doesn't check the validity of document.
            * The user can manipulate the file extension of a document and
              send media with wrong types that don't fit to this handler.
            * Case insensitive by default,
              you may change this with the flag ``case_sensitive=True``.
            * Extension should be passed without leading dot
              unless it's a part of the extension.
            * Pass :obj:`None` to filter files with no extension,
              i.e. without a dot in the filename.
        """

        __slots__ = ("_file_extension", "is_case_sensitive")

        def __init__(self, file_extension: str | None, case_sensitive: bool = False):
            super().__init__()
            self.is_case_sensitive: bool = case_sensitive
            if file_extension is None:
                self._file_extension = None
                self.name = "filters.Document.FileExtension(None)"
            elif self.is_case_sensitive:
                self._file_extension = f".{file_extension}"
                self.name = (
                    f"filters.Document.FileExtension({file_extension!r}, case_sensitive=True)"
                )
            else:
                self._file_extension = f".{file_extension}".lower()
                self.name = f"filters.Document.FileExtension({file_extension.lower()!r})"

        def filter(self, message: Message) -> bool:
            if message.document is None or message.document.file_name is None:
                return False
            if self._file_extension is None:
                return "." not in message.document.file_name
            if self.is_case_sensitive:
                filename = message.document.file_name
            else:
                filename = message.document.file_name.lower()
            return filename.endswith(self._file_extension)

    class MimeType(MessageFilter):
        """This Filter filters documents by their mime-type attribute.

        Args:
            mimetype (:obj:`str`): The mimetype to filter.

        Example:
            ``filters.Document.MimeType('audio/mpeg')`` filters all audio in `.mp3` format.

        Note:
            This Filter only filters by the mime_type of the document, it doesn't check the
            validity of document. The user can manipulate the mime-type of a message and
            send media with wrong types that don't fit to this handler.
        """

        __slots__ = ("mimetype",)

        def __init__(self, mimetype: str):
            self.mimetype: str = mimetype
            super().__init__(name=f"filters.Document.MimeType('{self.mimetype}')")

        def filter(self, message: Message) -> bool:
            if message.document:
                return message.document.mime_type == self.mimetype
            return False

    APK = MimeType("application/vnd.android.package-archive")
    """Use as ``filters.Document.APK``."""
    DOC = MimeType(mimetypes.types_map[".doc"])
    """Use as ``filters.Document.DOC``."""
    DOCX = MimeType("application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    """Use as ``filters.Document.DOCX``."""
    EXE = MimeType(mimetypes.types_map[".exe"])
    """Use as ``filters.Document.EXE``."""
    MP4 = MimeType(mimetypes.types_map[".mp4"])
    """Use as ``filters.Document.MP4``."""
    GIF = MimeType(mimetypes.types_map[".gif"])
    """Use as ``filters.Document.GIF``."""
    JPG = MimeType(mimetypes.types_map[".jpg"])
    """Use as ``filters.Document.JPG``."""
    MP3 = MimeType(mimetypes.types_map[".mp3"])
    """Use as ``filters.Document.MP3``."""
    PDF = MimeType(mimetypes.types_map[".pdf"])
    """Use as ``filters.Document.PDF``."""
    PY = MimeType(mimetypes.types_map[".py"])
    """Use as ``filters.Document.PY``."""
    SVG = MimeType(mimetypes.types_map[".svg"])
    """Use as ``filters.Document.SVG``."""
    TXT = MimeType(mimetypes.types_map[".txt"])
    """Use as ``filters.Document.TXT``."""
    TARGZ = MimeType("application/x-compressed-tar")
    """Use as ``filters.Document.TARGZ``."""
    WAV = MimeType(mimetypes.types_map[".wav"])
    """Use as ``filters.Document.WAV``."""
    XML = MimeType(mimetypes.types_map[".xml"])
    """Use as ``filters.Document.XML``."""
    ZIP = MimeType(mimetypes.types_map[".zip"])
    """Use as ``filters.Document.ZIP``."""


class _EffectId(MessageFilter):
    __slots__ = ()

    def filter(self, message: Message) -> bool:
        return bool(message.effect_id)


EFFECT_ID = _EffectId(name="filters.EFFECT_ID")
"""Messages that contain :attr:`telegram.Message.effect_id`.

.. versionadded:: 21.3"""


class Entity(MessageFilter):
    """
    Filters messages to only allow those which have a :class:`telegram.MessageEntity`
    where their :class:`~telegram.MessageEntity.type` matches `entity_type`.

    Examples:
        ``MessageHandler(filters.Entity("hashtag"), callback_method)``

    Args:
        entity_type (:obj:`str`): Entity type to check for. All types can be found as constants
            in :class:`telegram.MessageEntity`.

    """

    __slots__ = ("entity_type",)

    def __init__(self, entity_type: str):
        self.entity_type: str = entity_type
        super().__init__(name=f"filters.Entity({self.entity_type})")

    def filter(self, message: Message) -> bool:
        return any(entity.type == self.entity_type for entity in message.entities)


class _Forum(UpdateFilter):
    __slots__ = ()

    def filter(self, update: Update) -> bool:
        return bool(update.effective_chat and update.effective_chat.is_forum)


FORUM = _Forum(name="filters.FORUM")
"""Messages that are from a forum (topics enabled) chat.

.. versionadded:: 22.4
"""


class _Forwarded(MessageFilter):
    __slots__ = ()

    def filter(self, message: Message) -> bool:
        return bool(message.forward_origin)


FORWARDED = _Forwarded(name="filters.FORWARDED")
"""Messages that contain :attr:`telegram.Message.forward_origin`.

.. versionchanged:: 20.8
   Now based on :attr:`telegram.Message.forward_origin` instead of
   ``telegram.Message.forward_date``.
"""


class ForwardedFrom(_ChatUserBaseFilter):
    """Filters messages to allow only those which are forwarded from the specified chat ID(s)
    or username(s) based on :attr:`telegram.Message.forward_origin` and in particular

    * :attr:`telegram.MessageOriginUser.sender_user`
    * :attr:`telegram.MessageOriginChat.sender_chat`
    * :attr:`telegram.MessageOriginChannel.chat`

    .. versionadded:: 13.5

    .. versionchanged:: 20.8
       Was previously based on ``telegram.Message.forward_from`` and
         ``telegram.Message.forward_from_chat``.

    Examples:
        ``MessageHandler(filters.ForwardedFrom(chat_id=1234), callback_method)``

    Note:
        When a user has disallowed adding a link to their account while forwarding their
        messages, this filter will *not* work since
        :attr:`telegram.Message.forward_origin` will be of type
        :class:`telegram.MessageOriginHiddenUser`. However, this behaviour
        is undocumented and might be changed by Telegram.

    Warning:
        :attr:`chat_ids` will give a *copy* of the saved chat ids as :class:`frozenset`. This
        is to ensure thread safety. To add/remove a chat, you should use :meth:`add_chat_ids`, and
        :meth:`remove_chat_ids`. Only update the entire set by ``filter.chat_ids = new_set``, if
        you are entirely sure that it is not causing race conditions, as this will complete replace
        the current set of allowed chats.

    Args:
        chat_id(:obj:`int` | Collection[:obj:`int`], optional):
            Which chat/user ID(s) to allow through.
        username(:obj:`str` | Collection[:obj:`str`], optional):
            Which username(s) to allow through. Leading ``'@'`` s in usernames will be
            discarded.
        allow_empty(:obj:`bool`, optional): Whether updates should be processed, if no chat
            is specified in :attr:`chat_ids` and :attr:`usernames`. Defaults to :obj:`False`.

    Attributes:
        chat_ids (set(:obj:`int`)): Which chat/user ID(s) to allow through.
        allow_empty (:obj:`bool`): Whether updates should be processed, if no chat
            is specified in :attr:`chat_ids` and :attr:`usernames`.

    Raises:
        RuntimeError: If both ``chat_id`` and ``username`` are present.
    """

    __slots__ = ()

    def _get_chat_or_user(self, message: Message) -> TGUser | TGChat | None:
        if (forward_origin := message.forward_origin) is None:
            return None

        if isinstance(forward_origin, MessageOriginUser):
            return forward_origin.sender_user
        if isinstance(forward_origin, MessageOriginChat):
            return forward_origin.sender_chat
        if isinstance(forward_origin, MessageOriginChannel):
            return forward_origin.chat

        return None

    def add_chat_ids(self, chat_id: SCT[int]) -> None:
        """
        Add one or more chats to the allowed chat ids.

        Args:
            chat_id(:obj:`int` | Collection[:obj:`int`]): Which chat/user ID(s) to
                allow through.
        """
        return super()._add_chat_ids(chat_id)

    def remove_chat_ids(self, chat_id: SCT[int]) -> None:
        """
        Remove one or more chats from allowed chat ids.

        Args:
            chat_id(:obj:`int` | Collection[:obj:`int`]): Which chat/user ID(s) to
                disallow through.
        """
        return super()._remove_chat_ids(chat_id)


class _Game(MessageFilter):
    __slots__ = ()

    def filter(self, message: Message) -> bool:
        return bool(message.game)


GAME = _Game(name="filters.GAME")
"""Messages that contain :attr:`telegram.Message.game`."""


class _Giveaway(MessageFilter):
    __slots__ = ()

    def filter(self, message: Message) -> bool:
        return bool(message.giveaway)


GIVEAWAY = _Giveaway(name="filters.GIVEAWAY")
"""Messages that contain :attr:`telegram.Message.giveaway`."""


class _GiveawayWinners(MessageFilter):
    __slots__ = ()

    def filter(self, message: Message) -> bool:
        return bool(message.giveaway_winners)


GIVEAWAY_WINNERS = _GiveawayWinners(name="filters.GIVEAWAY_WINNERS")
"""Messages that contain :attr:`telegram.Message.giveaway_winners`."""


class _HasMediaSpoiler(MessageFilter):
    __slots__ = ()

    def filter(self, message: Message) -> bool:
        return bool(message.has_media_spoiler)


HAS_MEDIA_SPOILER = _HasMediaSpoiler(name="filters.HAS_MEDIA_SPOILER")
"""Messages that contain :attr:`telegram.Message.has_media_spoiler`.

    .. versionadded:: 20.0
"""


class _HasProtectedContent(MessageFilter):
    __slots__ = ()

    def filter(self, message: Message) -> bool:
        return bool(message.has_protected_content)


HAS_PROTECTED_CONTENT = _HasProtectedContent(name="filters.HAS_PROTECTED_CONTENT")
"""Messages that contain :attr:`telegram.Message.has_protected_content`.

    .. versionadded:: 13.9
"""


class _Invoice(MessageFilter):
    __slots__ = ()

    def filter(self, message: Message) -> bool:
        return bool(message.invoice)


INVOICE = _Invoice(name="filters.INVOICE")
"""Messages that contain :attr:`telegram.Message.invoice`."""


class _IsAutomaticForward(MessageFilter):
    __slots__ = ()

    def filter(self, message: Message) -> bool:
        return bool(message.is_automatic_forward)


IS_AUTOMATIC_FORWARD = _IsAutomaticForward(name="filters.IS_AUTOMATIC_FORWARD")
"""Messages that contain :attr:`telegram.Message.is_automatic_forward`.

    .. versionadded:: 13.9
"""


class _IsTopicMessage(MessageFilter):
    __slots__ = ()

    def filter(self, message: Message) -> bool:
        return bool(message.is_topic_message)


IS_TOPIC_MESSAGE = _IsTopicMessage(name="filters.IS_TOPIC_MESSAGE")
"""Messages that contain :attr:`telegram.Message.is_topic_message`.

    .. versionadded:: 20.0
"""


class _IsFromOffline(MessageFilter):
    __slots__ = ()

    def filter(self, message: Message) -> bool:
        return bool(message.is_from_offline)


IS_FROM_OFFLINE = _IsFromOffline(name="filters.IS_FROM_OFFLINE")
"""Messages that contain :attr:`telegram.Message.is_from_offline`.

    .. versionadded:: 21.1
"""


class Language(MessageFilter):
    """Filters messages to only allow those which are from users with a certain language code.

    Note:
        According to official Telegram Bot API documentation, not every single user has the
        `language_code` attribute. Do not count on this filter working on all users.

    Examples:
        ``MessageHandler(filters.Language("en"), callback_method)``

    Args:
        lang (:obj:`str` | Collection[:obj:`str`]):
            Which language code(s) to allow through.
            This will be matched using :obj:`str.startswith` meaning that
            'en' will match both 'en_US' and 'en_GB'.

    """

    __slots__ = ("lang",)

    def __init__(self, lang: SCT[str]):
        if isinstance(lang, str):
            lang = cast("str", lang)
            self.lang: Sequence[str] = [lang]
        else:
            lang = cast("list[str]", lang)
            self.lang = lang
        super().__init__(name=f"filters.Language({self.lang})")

    def filter(self, message: Message) -> bool:
        return bool(
            message.from_user
            and message.from_user.language_code
            and any(message.from_user.language_code.startswith(x) for x in self.lang)
        )


class _Location(MessageFilter):
    __slots__ = ()

    def filter(self, message: Message) -> bool:
        return bool(message.location)


LOCATION = _Location(name="filters.LOCATION")
"""Messages that contain :attr:`telegram.Message.location`."""


class Mention(MessageFilter):
    """Messages containing mentions of specified users or chats.

    Examples:
        .. code-block:: python

            MessageHandler(filters.Mention("username"), callback)
            MessageHandler(filters.Mention(["@username", 123456]), callback)

    .. versionadded:: 20.7

    Args:
        mentions (:obj:`int` | :obj:`str` | :class:`telegram.User` | Collection[:obj:`int` | \
            :obj:`str` | :class:`telegram.User`]):
            Specifies the users and chats to filter for. Messages that do not mention at least one
            of the specified users or chats will not be handled. Leading ``'@'`` s in usernames
            will be discarded.
    """

    __slots__ = ("_mentions",)

    def __init__(self, mentions: SCT[int | str | TGUser]):
        super().__init__(name=f"filters.Mention({mentions})")
        if isinstance(mentions, Iterable) and not isinstance(mentions, str):
            self._mentions = {self._fix_mention_username(mention) for mention in mentions}
        else:
            self._mentions = {self._fix_mention_username(mentions)}

    @staticmethod
    def _fix_mention_username(mention: int | str | TGUser) -> int | str | TGUser:
        if not isinstance(mention, str):
            return mention
        return mention.lstrip("@")

    @classmethod
    def _check_mention(cls, message: Message, mention: int | str | TGUser) -> bool:
        if not message.entities:
            return False

        entity_texts = message.parse_entities(
            types=[MessageEntity.MENTION, MessageEntity.TEXT_MENTION]
        )

        if isinstance(mention, TGUser):
            return any(
                mention.id == entity.user.id
                or mention.username == entity.user.username
                or mention.username == cls._fix_mention_username(entity_texts[entity])
                for entity in message.entities
                if entity.user
            ) or any(
                mention.username == cls._fix_mention_username(entity_text)
                for entity_text in entity_texts.values()
            )
        if isinstance(mention, int):
            return bool(
                any(mention == entity.user.id for entity in message.entities if entity.user)
            )
        return any(
            mention == cls._fix_mention_username(entity_text)
            for entity_text in entity_texts.values()
        )

    def filter(self, message: Message) -> bool:
        return any(self._check_mention(message, mention) for mention in self._mentions)


class _PaidMedia(MessageFilter):
    __slots__ = ()

    def filter(self, message: Message) -> bool:
        return bool(message.paid_media)


PAID_MEDIA = _PaidMedia(name="filters.PAID_MEDIA")
"""Messages that contain :attr:`telegram.Message.paid_media`.

.. versionadded:: 21.4
"""


class _PassportData(MessageFilter):
    __slots__ = ()

    def filter(self, message: Message) -> bool:
        return bool(message.passport_data)


PASSPORT_DATA = _PassportData(name="filters.PASSPORT_DATA")
"""Messages that contain :attr:`telegram.Message.passport_data`."""


class _Photo(MessageFilter):
    __slots__ = ()

    def filter(self, message: Message) -> bool:
        return bool(message.photo)


PHOTO = _Photo("filters.PHOTO")
"""Messages that contain :attr:`telegram.Message.photo`."""


class _Poll(MessageFilter):
    __slots__ = ()

    def filter(self, message: Message) -> bool:
        return bool(message.poll)


POLL = _Poll(name="filters.POLL")
"""Messages that contain :attr:`telegram.Message.poll`."""


class Regex(MessageFilter):
    """
    Filters updates by searching for an occurrence of :paramref:`~Regex.pattern` in the message
    text.
    The :func:`re.search` function is used to determine whether an update should be filtered.

    Refer to the documentation of the :obj:`re` module for more information.

    To get the groups and groupdict matched, see :attr:`telegram.ext.CallbackContext.matches`.

    Examples:
        Use ``MessageHandler(filters.Regex(r'help'), callback)`` to capture all messages that
        contain the word 'help'. You can also use
        ``MessageHandler(filters.Regex(re.compile(r'help', re.IGNORECASE)), callback)`` if
        you want your pattern to be case insensitive. This approach is recommended
        if you need to specify flags on your pattern.

    Note:
        Filters use the same short circuiting logic as python's :keyword:`and`, :keyword:`or` and
        :keyword:`not`.
        This means that for example:

            >>> filters.Regex(r'(a?x)') | filters.Regex(r'(b?x)')

        With a :attr:`telegram.Message.text` of `x`, will only ever return the matches for the
        first filter, since the second one is never evaluated.

    .. seealso:: :wiki:`Types of Handlers <Types-of-Handlers>`

    Args:
        pattern (:obj:`str` | :func:`re.Pattern <re.compile>`): The regex pattern.
    """

    __slots__ = ("pattern",)

    def __init__(self, pattern: str | Pattern[str]):
        if isinstance(pattern, str):
            pattern = re.compile(pattern)
        self.pattern: Pattern[str] = pattern
        super().__init__(name=f"filters.Regex({self.pattern})", data_filter=True)

    def filter(self, message: Message) -> dict[str, list[Match[str]]] | None:
        if message.text and (match := self.pattern.search(message.text)):
            return {"matches": [match]}
        return {}


class _Reply(MessageFilter):
    __slots__ = ()

    def filter(self, message: Message) -> bool:
        return bool(message.reply_to_message)


REPLY = _Reply(name="filters.REPLY")
"""Messages that contain :attr:`telegram.Message.reply_to_message`."""


class _SenderChat(MessageFilter):
    __slots__ = ()

    def filter(self, message: Message) -> bool:
        return bool(message.sender_chat)


class SenderChat(_ChatUserBaseFilter):
    """Filters messages to allow only those which are from a specified sender chat's chat ID or
    username.

    Examples:
        * To filter for messages sent to a group by a channel with ID
          ``-1234``, use ``MessageHandler(filters.SenderChat(-1234), callback_method)``.
        * To filter for messages of anonymous admins in a super group with username
          ``@anonymous``, use
          ``MessageHandler(filters.SenderChat(username='anonymous'), callback_method)``.
        * To filter for messages sent to a group by *any* channel, use
          ``MessageHandler(filters.SenderChat.CHANNEL, callback_method)``.
        * To filter for messages of anonymous admins in *any* super group, use
          ``MessageHandler(filters.SenderChat.SUPERGROUP, callback_method)``.
        * To filter for messages forwarded to a discussion group from *any* channel or of anonymous
          admins in *any* super group, use ``MessageHandler(filters.SenderChat.ALL, callback)``

    Note:
        Remember, ``sender_chat`` is also set for messages in a channel as the channel itself,
        so when your bot is an admin in a channel and the linked discussion group, you would
        receive the message twice (once from inside the channel, once inside the discussion
        group). Since v13.9, the field :attr:`telegram.Message.is_automatic_forward` will be
        :obj:`True` for the discussion group message.

    .. seealso:: :attr:`telegram.ext.filters.IS_AUTOMATIC_FORWARD`

    Warning:
        :attr:`chat_ids` will return a *copy* of the saved chat ids as :obj:`frozenset`. This
        is to ensure thread safety. To add/remove a chat, you should use :meth:`add_chat_ids`, and
        :meth:`remove_chat_ids`. Only update the entire set by ``filter.chat_ids = new_set``, if
        you are entirely sure that it is not causing race conditions, as this will complete replace
        the current set of allowed chats.

    Args:
        chat_id(:obj:`int` | Collection[:obj:`int`], optional):
            Which sender chat chat ID(s) to allow through.
        username(:obj:`str` | Collection[:obj:`str`], optional):
            Which sender chat username(s) to allow through.
            Leading ``'@'`` s in usernames will be discarded.
        allow_empty(:obj:`bool`, optional): Whether updates should be processed, if no sender
            chat is specified in :attr:`chat_ids` and :attr:`usernames`. Defaults to :obj:`False`.

    Attributes:
        chat_ids (set(:obj:`int`)): Which sender chat chat ID(s) to allow through.
        allow_empty (:obj:`bool`): Whether updates should be processed, if no sender chat is
            specified in :attr:`chat_ids` and :attr:`usernames`.

    Raises:
        RuntimeError: If both ``chat_id`` and ``username`` are present.
    """

    __slots__ = ()

    class _CHANNEL(MessageFilter):
        __slots__ = ()

        def filter(self, message: Message) -> bool:
            if message.sender_chat:
                return message.sender_chat.type == TGChat.CHANNEL
            return False

    class _SUPERGROUP(MessageFilter):
        __slots__ = ()

        def filter(self, message: Message) -> bool:
            if message.sender_chat:
                return message.sender_chat.type == TGChat.SUPERGROUP
            return False

    ALL = _SenderChat(name="filters.SenderChat.ALL")
    """All messages with a :attr:`telegram.Message.sender_chat`."""
    SUPER_GROUP = _SUPERGROUP(name="filters.SenderChat.SUPER_GROUP")
    """Messages whose sender chat is a super group."""
    CHANNEL = _CHANNEL(name="filters.SenderChat.CHANNEL")
    """Messages whose sender chat is a channel."""

    def add_chat_ids(self, chat_id: SCT[int]) -> None:
        """
        Add one or more sender chats to the allowed chat ids.

        Args:
            chat_id(:obj:`int` | Collection[:obj:`int`]): Which sender chat ID(s) to
                allow through.
        """
        return super()._add_chat_ids(chat_id)

    def _get_chat_or_user(self, message: Message) -> TGChat | None:
        return message.sender_chat

    def remove_chat_ids(self, chat_id: SCT[int]) -> None:
        """
        Remove one or more sender chats from allowed chat ids.

        Args:
            chat_id(:obj:`int` | Collection[:obj:`int`]): Which sender chat ID(s) to
                disallow through.
        """
        return super()._remove_chat_ids(chat_id)


class StatusUpdate:
    """Subset for messages containing a status update.

    Examples:
        Use these filters like: ``filters.StatusUpdate.NEW_CHAT_MEMBERS`` etc. Or use just
        ``filters.StatusUpdate.ALL`` for all status update messages.

    Caution:
        ``filters.StatusUpdate`` itself is *not* a filter, but just a convenience namespace.

    .. versionchanged:: 22.0
        Removed deprecated attribute `USER_SHARED`.
    """

    __slots__ = ()

    class _All(UpdateFilter):
        __slots__ = ()

        def filter(self, update: Update) -> bool:
            return bool(
                # keep this alphabetically sorted for easier maintenance
                StatusUpdate.CHAT_BACKGROUND_SET.check_update(update)
                or StatusUpdate.CHAT_CREATED.check_update(update)
                or StatusUpdate.CHAT_SHARED.check_update(update)
                or StatusUpdate.CHECKLIST_TASKS_ADDED.check_update(update)
                or StatusUpdate.CHECKLIST_TASKS_DONE.check_update(update)
                or StatusUpdate.CONNECTED_WEBSITE.check_update(update)
                or StatusUpdate.DIRECT_MESSAGE_PRICE_CHANGED.check_update(update)
                or StatusUpdate.DELETE_CHAT_PHOTO.check_update(update)
                or StatusUpdate.FORUM_TOPIC_CLOSED.check_update(update)
                or StatusUpdate.FORUM_TOPIC_CREATED.check_update(update)
                or StatusUpdate.FORUM_TOPIC_EDITED.check_update(update)
                or StatusUpdate.FORUM_TOPIC_REOPENED.check_update(update)
                or StatusUpdate.GENERAL_FORUM_TOPIC_HIDDEN.check_update(update)
                or StatusUpdate.GENERAL_FORUM_TOPIC_UNHIDDEN.check_update(update)
                or StatusUpdate.GIFT.check_update(update)
                or StatusUpdate.GIFT_UPGRADE_SENT.check_update(update)
                or StatusUpdate.GIVEAWAY_COMPLETED.check_update(update)
                or StatusUpdate.GIVEAWAY_CREATED.check_update(update)
                or StatusUpdate.LEFT_CHAT_MEMBER.check_update(update)
                or StatusUpdate.MESSAGE_AUTO_DELETE_TIMER_CHANGED.check_update(update)
                or StatusUpdate.MIGRATE.check_update(update)
                or StatusUpdate.NEW_CHAT_MEMBERS.check_update(update)
                or StatusUpdate.NEW_CHAT_PHOTO.check_update(update)
                or StatusUpdate.NEW_CHAT_TITLE.check_update(update)
                or StatusUpdate.PAID_MESSAGE_PRICE_CHANGED.check_update(update)
                or StatusUpdate.PINNED_MESSAGE.check_update(update)
                or StatusUpdate.PROXIMITY_ALERT_TRIGGERED.check_update(update)
                or StatusUpdate.REFUNDED_PAYMENT.check_update(update)
                or StatusUpdate.SUGGESTED_POST_APPROVAL_FAILED.check_update(update)
                or StatusUpdate.SUGGESTED_POST_APPROVED.check_update(update)
                or StatusUpdate.SUGGESTED_POST_DECLINED.check_update(update)
                or StatusUpdate.SUGGESTED_POST_PAID.check_update(update)
                or StatusUpdate.SUGGESTED_POST_REFUNDED.check_update(update)
                or StatusUpdate.UNIQUE_GIFT.check_update(update)
                or StatusUpdate.USERS_SHARED.check_update(update)
                or StatusUpdate.VIDEO_CHAT_ENDED.check_update(update)
                or StatusUpdate.VIDEO_CHAT_PARTICIPANTS_INVITED.check_update(update)
                or StatusUpdate.VIDEO_CHAT_SCHEDULED.check_update(update)
                or StatusUpdate.VIDEO_CHAT_STARTED.check_update(update)
                or StatusUpdate.WEB_APP_DATA.check_update(update)
                or StatusUpdate.WRITE_ACCESS_ALLOWED.check_update(update)
            )

    ALL = _All(name="filters.StatusUpdate.ALL")
    """Messages that contain any of the below."""

    class _ChatBackgroundSet(MessageFilter):
        __slots__ = ()

        def filter(self, message: Message) -> bool:
            return bool(message.chat_background_set)

    CHAT_BACKGROUND_SET = _ChatBackgroundSet(name="filters.StatusUpdate.CHAT_BACKGROUND_SET")
    """Messages that contain :attr:`telegram.Message.chat_background_set`."""

    class _ChatCreated(MessageFilter):
        __slots__ = ()

        def filter(self, message: Message) -> bool:
            return bool(
                message.group_chat_created
                or message.supergroup_chat_created
                or message.channel_chat_created
            )

    CHAT_CREATED = _ChatCreated(name="filters.StatusUpdate.CHAT_CREATED")
    """Messages that contain :attr:`telegram.Message.group_chat_created`,
        :attr:`telegram.Message.supergroup_chat_created` or
        :attr:`telegram.Message.channel_chat_created`."""

    class _ChatShared(MessageFilter):
        __slots__ = ()

        def filter(self, message: Message) -> bool:
            return bool(message.chat_shared)

    CHAT_SHARED = _ChatShared(name="filters.StatusUpdate.CHAT_SHARED")
    """Messages that contain :attr:`telegram.Message.chat_shared`.

    .. versionadded:: 20.1
    """

    class _ChecklistTasksAdded(MessageFilter):
        __slots__ = ()

        def filter(self, message: Message) -> bool:
            return bool(message.checklist_tasks_added)

    CHECKLIST_TASKS_ADDED = _ChecklistTasksAdded(name="filters.StatusUpdate.CHECKLIST_TASKS_ADDED")
    """Messages that contain :attr:`telegram.Message.checklist_tasks_added`.

    .. versionadded:: 22.3
    """

    class _ChecklistTasksDone(MessageFilter):
        __slots__ = ()

        def filter(self, message: Message) -> bool:
            return bool(message.checklist_tasks_done)

    CHECKLIST_TASKS_DONE = _ChecklistTasksDone(name="filters.StatusUpdate.CHECKLIST_TASKS_DONE")
    """Messages that contain :attr:`telegram.Message.checklist_tasks_done`.

    .. versionadded:: 22.3
    """

    class _ConnectedWebsite(MessageFilter):
        __slots__ = ()

        def filter(self, message: Message) -> bool:
            return bool(message.connected_website)

    CONNECTED_WEBSITE = _ConnectedWebsite(name="filters.StatusUpdate.CONNECTED_WEBSITE")
    """Messages that contain :attr:`telegram.Message.connected_website`."""

    class _DirectMessagePriceChanged(MessageFilter):
        __slots__ = ()

        def filter(self, message: Message) -> bool:
            return bool(message.direct_message_price_changed)

    DIRECT_MESSAGE_PRICE_CHANGED = _DirectMessagePriceChanged(
        name="filters.StatusUpdate.DIRECT_MESSAGE_PRICE_CHANGED"
    )
    """Messages that contain :attr:`telegram.Message.direct_message_price_changed`.

    .. versionadded:: 22.3
    """

    class _DeleteChatPhoto(MessageFilter):
        __slots__ = ()

        def filter(self, message: Message) -> bool:
            return bool(message.delete_chat_photo)

    DELETE_CHAT_PHOTO = _DeleteChatPhoto(name="filters.StatusUpdate.DELETE_CHAT_PHOTO")
    """Messages that contain :attr:`telegram.Message.delete_chat_photo`."""

    class _ForumTopicClosed(MessageFilter):
        __slots__ = ()

        def filter(self, message: Message) -> bool:
            return bool(message.forum_topic_closed)

    FORUM_TOPIC_CLOSED = _ForumTopicClosed(name="filters.StatusUpdate.FORUM_TOPIC_CLOSED")
    """Messages that contain :attr:`telegram.Message.forum_topic_closed`.

    .. versionadded:: 20.0
    """

    class _ForumTopicCreated(MessageFilter):
        __slots__ = ()

        def filter(self, message: Message) -> bool:
            return bool(message.forum_topic_created)

    FORUM_TOPIC_CREATED = _ForumTopicCreated(name="filters.StatusUpdate.FORUM_TOPIC_CREATED")
    """Messages that contain :attr:`telegram.Message.forum_topic_created`.

    .. versionadded:: 20.0
    """

    class _ForumTopicEdited(MessageFilter):
        __slots__ = ()

        def filter(self, message: Message) -> bool:
            return bool(message.forum_topic_edited)

    FORUM_TOPIC_EDITED = _ForumTopicEdited(name="filters.StatusUpdate.FORUM_TOPIC_EDITED")
    """Messages that contain :attr:`telegram.Message.forum_topic_edited`.

    .. versionadded:: 20.0
    """

    class _ForumTopicReopened(MessageFilter):
        __slots__ = ()

        def filter(self, message: Message) -> bool:
            return bool(message.forum_topic_reopened)

    FORUM_TOPIC_REOPENED = _ForumTopicReopened(name="filters.StatusUpdate.FORUM_TOPIC_REOPENED")
    """Messages that contain :attr:`telegram.Message.forum_topic_reopened`.

    .. versionadded:: 20.0
    """

    class _GeneralForumTopicHidden(MessageFilter):
        __slots__ = ()

        def filter(self, message: Message) -> bool:
            return bool(message.general_forum_topic_hidden)

    GENERAL_FORUM_TOPIC_HIDDEN = _GeneralForumTopicHidden(
        name="filters.StatusUpdate.GENERAL_FORUM_TOPIC_HIDDEN"
    )
    """Messages that contain :attr:`telegram.Message.general_forum_topic_hidden`.

    .. versionadded:: 20.0
    """

    class _GeneralForumTopicUnhidden(MessageFilter):
        __slots__ = ()

        def filter(self, message: Message) -> bool:
            return bool(message.general_forum_topic_unhidden)

    GENERAL_FORUM_TOPIC_UNHIDDEN = _GeneralForumTopicUnhidden(
        name="filters.StatusUpdate.GENERAL_FORUM_TOPIC_UNHIDDEN"
    )
    """Messages that contain :attr:`telegram.Message.general_forum_topic_unhidden`.

    .. versionadded:: 20.0
    """

    class _Gift(MessageFilter):
        __slots__ = ()

        def filter(self, message: Message) -> bool:
            return bool(message.gift)

    GIFT = _Gift(name="filters.StatusUpdate.GIFT")
    """Messages that contain :attr:`telegram.Message.gift`.

    .. versionadded:: 22.1
    """

    class _GiftUpgradeSent(MessageFilter):
        __slots__ = ()

        def filter(self, message: Message) -> bool:
            return bool(message.gift_upgrade_sent)

    GIFT_UPGRADE_SENT = _GiftUpgradeSent(name="filters.StatusUpdate.GIFT_UPGRADE_SENT")
    """Messages that contain :attr:`telegram.Message.gift_upgrade_sent`.

    .. versionadded:: 22.6
    """

    class _GiveawayCreated(MessageFilter):
        __slots__ = ()

        def filter(self, message: Message) -> bool:
            return bool(message.giveaway_created)

    GIVEAWAY_CREATED = _GiveawayCreated(name="filters.StatusUpdate.GIVEAWAY_CREATED")
    """Messages that contain :attr:`telegram.Message.giveaway_created`.

    .. versionadded:: 20.8
    """

    class _GiveawayCompleted(MessageFilter):
        __slots__ = ()

        def filter(self, message: Message) -> bool:
            return bool(message.giveaway_completed)

    GIVEAWAY_COMPLETED = _GiveawayCompleted(name="filters.StatusUpdate.GIVEAWAY_COMPLETED")
    """Messages that contain :attr:`telegram.Message.giveaway_completed`.
    .. versionadded:: 20.8
    """

    class _LeftChatMember(MessageFilter):
        __slots__ = ()

        def filter(self, message: Message) -> bool:
            return bool(message.left_chat_member)

    LEFT_CHAT_MEMBER = _LeftChatMember(name="filters.StatusUpdate.LEFT_CHAT_MEMBER")
    """Messages that contain :attr:`telegram.Message.left_chat_member`."""

    class _MessageAutoDeleteTimerChanged(MessageFilter):
        __slots__ = ()

        def filter(self, message: Message) -> bool:
            return bool(message.message_auto_delete_timer_changed)

    MESSAGE_AUTO_DELETE_TIMER_CHANGED = _MessageAutoDeleteTimerChanged(
        "filters.StatusUpdate.MESSAGE_AUTO_DELETE_TIMER_CHANGED"
    )
    """Messages that contain :attr:`telegram.Message.message_auto_delete_timer_changed`

    .. versionadded:: 13.4
    """

    class _Migrate(MessageFilter):
        __slots__ = ()

        def filter(self, message: Message) -> bool:
            return bool(message.migrate_from_chat_id or message.migrate_to_chat_id)

    MIGRATE = _Migrate(name="filters.StatusUpdate.MIGRATE")
    """Messages that contain :attr:`telegram.Message.migrate_from_chat_id` or
        :attr:`telegram.Message.migrate_to_chat_id`."""

    class _NewChatMembers(MessageFilter):
        __slots__ = ()

        def filter(self, message: Message) -> bool:
            return bool(message.new_chat_members)

    NEW_CHAT_MEMBERS = _NewChatMembers(name="filters.StatusUpdate.NEW_CHAT_MEMBERS")
    """Messages that contain :attr:`telegram.Message.new_chat_members`."""

    class _NewChatPhoto(MessageFilter):
        __slots__ = ()

        def filter(self, message: Message) -> bool:
            return bool(message.new_chat_photo)

    NEW_CHAT_PHOTO = _NewChatPhoto(name="filters.StatusUpdate.NEW_CHAT_PHOTO")
    """Messages that contain :attr:`telegram.Message.new_chat_photo`."""

    class _NewChatTitle(MessageFilter):
        __slots__ = ()

        def filter(self, message: Message) -> bool:
            return bool(message.new_chat_title)

    NEW_CHAT_TITLE = _NewChatTitle(name="filters.StatusUpdate.NEW_CHAT_TITLE")
    """Messages that contain :attr:`telegram.Message.new_chat_title`."""

    class _PaidMessagePriceChanged(MessageFilter):
        __slots__ = ()

        def filter(self, message: Message) -> bool:
            return bool(message.paid_message_price_changed)

    PAID_MESSAGE_PRICE_CHANGED = _PaidMessagePriceChanged(
        name="filters.StatusUpdate.PAID_MESSAGE_PRICE_CHANGED"
    )
    """Messages that contain :attr:`telegram.Message.paid_message_price_changed`.

    .. versionadded:: 22.1
    """

    class _PinnedMessage(MessageFilter):
        __slots__ = ()

        def filter(self, message: Message) -> bool:
            return bool(message.pinned_message)

    PINNED_MESSAGE = _PinnedMessage(name="filters.StatusUpdate.PINNED_MESSAGE")
    """Messages that contain :attr:`telegram.Message.pinned_message`."""

    class _ProximityAlertTriggered(MessageFilter):
        __slots__ = ()

        def filter(self, message: Message) -> bool:
            return bool(message.proximity_alert_triggered)

    PROXIMITY_ALERT_TRIGGERED = _ProximityAlertTriggered(
        "filters.StatusUpdate.PROXIMITY_ALERT_TRIGGERED"
    )
    """Messages that contain :attr:`telegram.Message.proximity_alert_triggered`."""

    class _RefundedPayment(MessageFilter):
        __slots__ = ()

        def filter(self, message: Message) -> bool:
            return bool(message.refunded_payment)

    REFUNDED_PAYMENT = _RefundedPayment("filters.StatusUpdate.REFUNDED_PAYMENT")
    """Messages that contain :attr:`telegram.Message.refunded_payment`.
    .. versionadded:: 21.4
    """

    class _SuggestedPostApprovalFailed(MessageFilter):
        __slots__ = ()

        def filter(self, message: Message) -> bool:
            return bool(message.suggested_post_approval_failed)

    SUGGESTED_POST_APPROVAL_FAILED = _SuggestedPostApprovalFailed(
        "filters.StatusUpdate.SUGGESTED_POST_APPROVAL_FAILED"
    )
    """Messages that contain :attr:`telegram.Message.suggested_post_approval_failed`.
    .. versionadded:: 22.4
    """

    class _SuggestedPostApproved(MessageFilter):
        __slots__ = ()

        def filter(self, message: Message) -> bool:
            return bool(message.suggested_post_approved)

    SUGGESTED_POST_APPROVED = _SuggestedPostApproved(
        "filters.StatusUpdate.SUGGESTED_POST_APPROVED"
    )
    """Messages that contain :attr:`telegram.Message.suggested_post_approved`.
    .. versionadded:: 22.4
    """

    class _SuggestedPostDeclined(MessageFilter):
        __slots__ = ()

        def filter(self, message: Message) -> bool:
            return bool(message.suggested_post_declined)

    SUGGESTED_POST_DECLINED = _SuggestedPostDeclined(
        "filters.StatusUpdate.SUGGESTED_POST_DECLINED"
    )
    """Messages that contain :attr:`telegram.Message.suggested_post_declined`.
    .. versionadded:: 22.4
    """

    class _SuggestedPostPaid(MessageFilter):
        __slots__ = ()

        def filter(self, message: Message) -> bool:
            return bool(message.suggested_post_paid)

    SUGGESTED_POST_PAID = _SuggestedPostPaid("filters.StatusUpdate.SUGGESTED_POST_PAID")
    """Messages that contain :attr:`telegram.Message.suggested_post_paid`.
    .. versionadded:: 22.4
    """

    class _SuggestedPostRefunded(MessageFilter):
        __slots__ = ()

        def filter(self, message: Message) -> bool:
            return bool(message.suggested_post_refunded)

    SUGGESTED_POST_REFUNDED = _SuggestedPostRefunded(
        "filters.StatusUpdate.SUGGESTED_POST_REFUNDED"
    )
    """Messages that contain :attr:`telegram.Message.suggested_post_refunded`.
    .. versionadded:: 22.4
    """

    class _UniqueGift(MessageFilter):
        __slots__ = ()

        def filter(self, message: Message) -> bool:
            return bool(message.unique_gift)

    UNIQUE_GIFT = _UniqueGift(name="filters.StatusUpdate.UNIQUE_GIFT")
    """Messages that contain :attr:`telegram.Message.unique_gift`.

    .. versionadded:: 22.1
    """

    class _UsersShared(MessageFilter):
        __slots__ = ()

        def filter(self, message: Message) -> bool:
            return bool(message.users_shared)

    USERS_SHARED = _UsersShared(name="filters.StatusUpdate.USERS_SHARED")
    """Messages that contain :attr:`telegram.Message.users_shared`.

    .. versionadded:: 20.8
    """

    class _VideoChatEnded(MessageFilter):
        __slots__ = ()

        def filter(self, message: Message) -> bool:
            return bool(message.video_chat_ended)

    VIDEO_CHAT_ENDED = _VideoChatEnded(name="filters.StatusUpdate.VIDEO_CHAT_ENDED")
    """Messages that contain :attr:`telegram.Message.video_chat_ended`.

    .. versionadded:: 13.4
    .. versionchanged:: 20.0
        This filter was formerly named ``VOICE_CHAT_ENDED``
    """

    class _VideoChatScheduled(MessageFilter):
        __slots__ = ()

        def filter(self, message: Message) -> bool:
            return bool(message.video_chat_scheduled)

    VIDEO_CHAT_SCHEDULED = _VideoChatScheduled(name="filters.StatusUpdate.VIDEO_CHAT_SCHEDULED")
    """Messages that contain :attr:`telegram.Message.video_chat_scheduled`.

    .. versionadded:: 13.5
    .. versionchanged:: 20.0
        This filter was formerly named ``VOICE_CHAT_SCHEDULED``
    """

    class _VideoChatStarted(MessageFilter):
        __slots__ = ()

        def filter(self, message: Message) -> bool:
            return bool(message.video_chat_started)

    VIDEO_CHAT_STARTED = _VideoChatStarted(name="filters.StatusUpdate.VIDEO_CHAT_STARTED")
    """Messages that contain :attr:`telegram.Message.video_chat_started`.

    .. versionadded:: 13.4
    .. versionchanged:: 20.0
        This filter was formerly named ``VOICE_CHAT_STARTED``
    """

    class _VideoChatParticipantsInvited(MessageFilter):
        __slots__ = ()

        def filter(self, message: Message) -> bool:
            return bool(message.video_chat_participants_invited)

    VIDEO_CHAT_PARTICIPANTS_INVITED = _VideoChatParticipantsInvited(
        "filters.StatusUpdate.VIDEO_CHAT_PARTICIPANTS_INVITED"
    )
    """Messages that contain :attr:`telegram.Message.video_chat_participants_invited`.

    .. versionadded:: 13.4
    .. versionchanged:: 20.0
        This filter was formerly named ``VOICE_CHAT_PARTICIPANTS_INVITED``
    """

    class _WebAppData(MessageFilter):
        __slots__ = ()

        def filter(self, message: Message) -> bool:
            return bool(message.web_app_data)

    WEB_APP_DATA = _WebAppData(name="filters.StatusUpdate.WEB_APP_DATA")
    """Messages that contain :attr:`telegram.Message.web_app_data`.

    .. versionadded:: 20.0
    """

    class _WriteAccessAllowed(MessageFilter):
        __slots__ = ()

        def filter(self, message: Message) -> bool:
            return bool(message.write_access_allowed)

    WRITE_ACCESS_ALLOWED = _WriteAccessAllowed(name="filters.StatusUpdate.WRITE_ACCESS_ALLOWED")
    """Messages that contain :attr:`telegram.Message.write_access_allowed`.

    .. versionadded:: 20.0
    """


class Sticker:
    """Filters messages which contain a sticker.

    Examples:
        Use this filter like: ``filters.Sticker.VIDEO``. Or, just use ``filters.Sticker.ALL`` for
        any type of sticker.

    Caution:
        ``filters.Sticker`` itself is *not* a filter, but just a convenience namespace.
    """

    __slots__ = ()

    class _All(MessageFilter):
        __slots__ = ()

        def filter(self, message: Message) -> bool:
            return bool(message.sticker)

    ALL = _All(name="filters.Sticker.ALL")
    """Messages that contain :attr:`telegram.Message.sticker`."""

    class _Animated(MessageFilter):
        __slots__ = ()

        def filter(self, message: Message) -> bool:
            return bool(message.sticker) and bool(message.sticker.is_animated)  # type: ignore

    ANIMATED = _Animated(name="filters.Sticker.ANIMATED")
    """Messages that contain :attr:`telegram.Message.sticker` and
    :attr:`is animated <telegram.Sticker.is_animated>`.

    .. versionadded:: 20.0
    """

    class _Static(MessageFilter):
        __slots__ = ()

        def filter(self, message: Message) -> bool:
            return bool(message.sticker) and (
                not bool(message.sticker.is_animated)  # type: ignore[union-attr]
                and not bool(message.sticker.is_video)  # type: ignore[union-attr]
            )

    STATIC = _Static(name="filters.Sticker.STATIC")
    """Messages that contain :attr:`telegram.Message.sticker` and is a static sticker, i.e. does
    not contain :attr:`telegram.Sticker.is_animated` or :attr:`telegram.Sticker.is_video`.

    .. versionadded:: 20.0
    """

    class _Video(MessageFilter):
        __slots__ = ()

        def filter(self, message: Message) -> bool:
            return bool(message.sticker) and bool(message.sticker.is_video)  # type: ignore

    VIDEO = _Video(name="filters.Sticker.VIDEO")
    """Messages that contain :attr:`telegram.Message.sticker` and is a
    :attr:`video sticker <telegram.Sticker.is_video>`.

    .. versionadded:: 20.0
    """

    class _Premium(MessageFilter):
        __slots__ = ()

        def filter(self, message: Message) -> bool:
            return bool(message.sticker) and bool(
                message.sticker.premium_animation  # type: ignore
            )

    PREMIUM = _Premium(name="filters.Sticker.PREMIUM")
    """Messages that contain :attr:`telegram.Message.sticker` and have a
    :attr:`premium animation <telegram.Sticker.premium_animation>`.

    .. versionadded:: 20.0
    """
    # neither mask nor emoji can be a message.sticker, so no filters for them


class _Story(MessageFilter):
    __slots__ = ()

    def filter(self, message: Message) -> bool:
        return bool(message.story)


STORY = _Story(name="filters.STORY")
"""Messages that contain :attr:`telegram.Message.story`.

.. versionadded:: 20.5
"""


class SuccessfulPayment(MessageFilter):
    """Successful Payment Messages. If a list of invoice payloads is passed, it filters
    messages to only allow those whose `invoice_payload` is appearing in the given list.

    Examples:
        `MessageHandler(filters.SuccessfulPayment(['Custom-Payload']), callback_method)`

    .. seealso::
        :attr:`telegram.ext.filters.SUCCESSFUL_PAYMENT`

    Args:
        invoice_payloads (list[:obj:`str`] | tuple[:obj:`str`], optional): Which
            invoice payloads to allow. Only exact matches are allowed. If not
            specified, will allow any invoice payload.

    .. versionadded:: 20.8
    """

    __slots__ = ("invoice_payloads",)

    def __init__(self, invoice_payloads: list[str] | tuple[str, ...] | None = None):
        self.invoice_payloads: Sequence[str] | None = invoice_payloads
        super().__init__(
            name=(
                f"filters.SuccessfulPayment({invoice_payloads})"
                if invoice_payloads
                else "filters.SUCCESSFUL_PAYMENT"
            )
        )

    def filter(self, message: Message) -> bool:
        if self.invoice_payloads is None:
            return bool(message.successful_payment)
        return (
            payment.invoice_payload in self.invoice_payloads
            if (payment := message.successful_payment)
            else False
        )


SUCCESSFUL_PAYMENT = SuccessfulPayment()
"""Messages that contain :attr:`telegram.Message.successful_payment`."""


class _SuggestedPostInfo(MessageFilter):
    __slots__ = ()

    def filter(self, message: Message) -> bool:
        return bool(message.suggested_post_info)


SUGGESTED_POST_INFO = _SuggestedPostInfo(name="filters.SUGGESTED_POST_INFO")
"""Messages that contain :attr:`telegram.Message.suggested_post_info`.

.. versionadded:: 22.4
"""


class Text(MessageFilter):
    """Text Messages. If a list of strings is passed, it filters messages to only allow those
    whose text is appearing in the given list.

    Examples:
        A simple use case for passing a list is to allow only messages that were sent by a
        custom :class:`telegram.ReplyKeyboardMarkup`::

            buttons = ['Start', 'Settings', 'Back']
            markup = ReplyKeyboardMarkup.from_column(buttons)
            ...
            MessageHandler(filters.Text(buttons), callback_method)

    .. seealso::
        :attr:`telegram.ext.filters.TEXT`


    Note:
        * Dice messages don't have text. If you want to filter either text or dice messages, use
          ``filters.TEXT | filters.Dice.ALL``.
        * Messages containing a command are accepted by this filter. Use
          ``filters.TEXT & (~filters.COMMAND)``, if you want to filter only text messages without
          commands.

    Args:
        strings (list[:obj:`str`] | tuple[:obj:`str`], optional): Which messages to allow. Only
            exact matches are allowed. If not specified, will allow any text message.
    """

    __slots__ = ("strings",)

    def __init__(self, strings: list[str] | tuple[str, ...] | None = None):
        self.strings: Sequence[str] | None = strings
        super().__init__(name=f"filters.Text({strings})" if strings else "filters.TEXT")

    def filter(self, message: Message) -> bool:
        if self.strings is None:
            return bool(message.text)
        return message.text in self.strings if message.text else False


TEXT = Text()  # pylint: disable=invalid-name
"""
Shortcut for :class:`telegram.ext.filters.Text()`.

Examples:
    To allow any text message, simply use ``MessageHandler(filters.TEXT, callback_method)``.
"""


class UpdateType:
    """
    Subset for filtering the type of update.

    Examples:
        Use these filters like: ``filters.UpdateType.MESSAGE`` or
        ``filters.UpdateType.CHANNEL_POSTS`` etc.

    Caution:
        ``filters.UpdateType`` itself is *not* a filter, but just a convenience namespace.
    """

    __slots__ = ()

    class _ChannelPost(UpdateFilter):
        __slots__ = ()

        def filter(self, update: Update) -> bool:
            return update.channel_post is not None

    CHANNEL_POST = _ChannelPost(name="filters.UpdateType.CHANNEL_POST")
    """Updates with :attr:`telegram.Update.channel_post`."""

    class _ChannelPosts(UpdateFilter):
        __slots__ = ()

        def filter(self, update: Update) -> bool:
            return update.channel_post is not None or update.edited_channel_post is not None

    CHANNEL_POSTS = _ChannelPosts(name="filters.UpdateType.CHANNEL_POSTS")
    """Updates with either :attr:`telegram.Update.channel_post` or
    :attr:`telegram.Update.edited_channel_post`."""

    class _Edited(UpdateFilter):
        __slots__ = ()

        def filter(self, update: Update) -> bool:
            return (
                update.edited_message is not None
                or update.edited_channel_post is not None
                or update.edited_business_message is not None
            )

    EDITED = _Edited(name="filters.UpdateType.EDITED")
    """Updates with :attr:`telegram.Update.edited_message`,
    :attr:`telegram.Update.edited_channel_post`, or
    :attr:`telegram.Update.edited_business_message`.

    .. versionadded:: 20.0

    .. versionchanged:: 21.1
        Added :attr:`telegram.Update.edited_business_message` to the filter.
    """

    class _EditedChannelPost(UpdateFilter):
        __slots__ = ()

        def filter(self, update: Update) -> bool:
            return update.edited_channel_post is not None

    EDITED_CHANNEL_POST = _EditedChannelPost(name="filters.UpdateType.EDITED_CHANNEL_POST")
    """Updates with :attr:`telegram.Update.edited_channel_post`."""

    class _EditedMessage(UpdateFilter):
        __slots__ = ()

        def filter(self, update: Update) -> bool:
            return update.edited_message is not None

    EDITED_MESSAGE = _EditedMessage(name="filters.UpdateType.EDITED_MESSAGE")
    """Updates with :attr:`telegram.Update.edited_message`."""

    class _Message(UpdateFilter):
        __slots__ = ()

        def filter(self, update: Update) -> bool:
            return update.message is not None

    MESSAGE = _Message(name="filters.UpdateType.MESSAGE")
    """Updates with :attr:`telegram.Update.message`."""

    class _Messages(UpdateFilter):
        __slots__ = ()

        def filter(self, update: Update) -> bool:
            return update.message is not None or update.edited_message is not None

    MESSAGES = _Messages(name="filters.UpdateType.MESSAGES")
    """Updates with either :attr:`telegram.Update.message` or
    :attr:`telegram.Update.edited_message`.
    """

    class _BusinessMessage(UpdateFilter):
        __slots__ = ()

        def filter(self, update: Update) -> bool:
            return update.business_message is not None

    BUSINESS_MESSAGE = _BusinessMessage(name="filters.UpdateType.BUSINESS_MESSAGE")
    """Updates with :attr:`telegram.Update.business_message`.

    .. versionadded:: 21.1"""

    class _EditedBusinessMessage(UpdateFilter):
        __slots__ = ()

        def filter(self, update: Update) -> bool:
            return update.edited_business_message is not None

    EDITED_BUSINESS_MESSAGE = _EditedBusinessMessage(
        name="filters.UpdateType.EDITED_BUSINESS_MESSAGE"
    )
    """Updates with :attr:`telegram.Update.edited_business_message`.

    .. versionadded:: 21.1
    """

    class _BusinessMessages(UpdateFilter):
        __slots__ = ()

        def filter(self, update: Update) -> bool:
            return (
                update.business_message is not None or update.edited_business_message is not None
            )

    BUSINESS_MESSAGES = _BusinessMessages(name="filters.UpdateType.BUSINESS_MESSAGES")
    """Updates with either :attr:`telegram.Update.business_message` or
    :attr:`telegram.Update.edited_business_message`.

    .. versionadded:: 21.1
    """


class User(_ChatUserBaseFilter):
    """Filters messages to allow only those which are from specified user ID(s) or
    username(s).

    Examples:
        ``MessageHandler(filters.User(1234), callback_method)``

    Args:
        user_id(:obj:`int` | Collection[:obj:`int`], optional): Which user ID(s) to
            allow through.
        username(:obj:`str` | Collection[:obj:`str`], optional):
            Which username(s) to allow through. Leading ``'@'`` s in usernames will be discarded.
        allow_empty(:obj:`bool`, optional): Whether updates should be processed, if no user is
            specified in :attr:`user_ids` and :attr:`usernames`. Defaults to :obj:`False`.

    Raises:
        RuntimeError: If ``user_id`` and ``username`` are both present.

    Attributes:
        allow_empty (:obj:`bool`): Whether updates should be processed, if no user is specified in
            :attr:`user_ids` and :attr:`usernames`.
    """

    __slots__ = ()

    def __init__(
        self,
        user_id: SCT[int] | None = None,
        username: SCT[str] | None = None,
        allow_empty: bool = False,
    ):
        super().__init__(chat_id=user_id, username=username, allow_empty=allow_empty)
        self._chat_id_name = "user_id"

    def _get_chat_or_user(self, message: Message) -> TGUser | None:
        return message.from_user

    @property
    def user_ids(self) -> frozenset[int]:
        """
        Which user ID(s) to allow through.

        Warning:
            :attr:`user_ids` will give a *copy* of the saved user ids as :obj:`frozenset`. This
            is to ensure thread safety. To add/remove a user, you should use :meth:`add_user_ids`,
            and :meth:`remove_user_ids`. Only update the entire set by
            ``filter.user_ids = new_set``, if you are entirely sure that it is not causing race
            conditions, as this will complete replace the current set of allowed users.

        Returns:
            frozenset(:obj:`int`)
        """
        return self.chat_ids

    @user_ids.setter
    def user_ids(self, user_id: SCT[int]) -> None:
        self.chat_ids = user_id

    def add_user_ids(self, user_id: SCT[int]) -> None:
        """
        Add one or more users to the allowed user ids.

        Args:
            user_id(:obj:`int` | Collection[:obj:`int`]): Which user ID(s) to allow
                through.
        """
        return super()._add_chat_ids(user_id)

    def remove_user_ids(self, user_id: SCT[int]) -> None:
        """
        Remove one or more users from allowed user ids.

        Args:
            user_id(:obj:`int` | Collection[:obj:`int`]): Which user ID(s) to
                disallow through.
        """
        return super()._remove_chat_ids(user_id)


class _User(MessageFilter):
    __slots__ = ()

    def filter(self, message: Message) -> bool:
        return bool(message.from_user)


USER = _User(name="filters.USER")
"""This filter filters *any* message that has a :attr:`telegram.Message.from_user`."""


class _UserAttachment(UpdateFilter):
    __slots__ = ()

    def filter(self, update: Update) -> bool:
        return bool(update.effective_user) and bool(
            update.effective_user.added_to_attachment_menu  # type: ignore
        )


USER_ATTACHMENT = _UserAttachment(name="filters.USER_ATTACHMENT")
"""This filter filters *any* message that have a user who added the bot to their
:attr:`attachment menu <telegram.User.added_to_attachment_menu>` as
:attr:`telegram.Update.effective_user`.

.. versionadded:: 20.0
"""


class _UserPremium(UpdateFilter):
    __slots__ = ()

    def filter(self, update: Update) -> bool:
        return bool(update.effective_user) and bool(
            update.effective_user.is_premium  # type: ignore
        )


PREMIUM_USER = _UserPremium(name="filters.PREMIUM_USER")
"""This filter filters *any* message from a
:attr:`Telegram Premium user <telegram.User.is_premium>` as :attr:`telegram.Update.effective_user`.

.. versionadded:: 20.0
"""


class _Venue(MessageFilter):
    __slots__ = ()

    def filter(self, message: Message) -> bool:
        return bool(message.venue)


VENUE = _Venue(name="filters.VENUE")
"""Messages that contain :attr:`telegram.Message.venue`."""


class ViaBot(_ChatUserBaseFilter):
    """Filters messages to allow only those which are from specified via_bot ID(s) or username(s).

    Examples:
        ``MessageHandler(filters.ViaBot(1234), callback_method)``

    .. seealso:: :attr:`~telegram.ext.filters.VIA_BOT`

    Args:
        bot_id(:obj:`int` | Collection[:obj:`int`], optional): Which bot ID(s) to
            allow through.
        username(:obj:`str` | Collection[:obj:`str`], optional):
            Which username(s) to allow through. Leading ``'@'`` s in usernames will be
            discarded.
        allow_empty(:obj:`bool`, optional): Whether updates should be processed, if no user
            is specified in :attr:`bot_ids` and :attr:`usernames`. Defaults to :obj:`False`.

    Raises:
        RuntimeError: If ``bot_id`` and ``username`` are both present.

    Attributes:
        allow_empty (:obj:`bool`): Whether updates should be processed, if no bot is specified in
            :attr:`bot_ids` and :attr:`usernames`.
    """

    __slots__ = ()

    def __init__(
        self,
        bot_id: SCT[int] | None = None,
        username: SCT[str] | None = None,
        allow_empty: bool = False,
    ):
        super().__init__(chat_id=bot_id, username=username, allow_empty=allow_empty)
        self._chat_id_name = "bot_id"

    def _get_chat_or_user(self, message: Message) -> TGUser | None:
        return message.via_bot

    @property
    def bot_ids(self) -> frozenset[int]:
        """
        Which bot ID(s) to allow through.

        Warning:
            :attr:`bot_ids` will give a *copy* of the saved bot ids as :obj:`frozenset`. This
            is to ensure thread safety. To add/remove a bot, you should use :meth:`add_bot_ids`,
            and :meth:`remove_bot_ids`. Only update the entire set by ``filter.bot_ids = new_set``,
            if you are entirely sure that it is not causing race conditions, as this will complete
            replace the current set of allowed bots.

        Returns:
            frozenset(:obj:`int`)
        """
        return self.chat_ids

    @bot_ids.setter
    def bot_ids(self, bot_id: SCT[int]) -> None:
        self.chat_ids = bot_id

    def add_bot_ids(self, bot_id: SCT[int]) -> None:
        """
        Add one or more bots to the allowed bot ids.

        Args:
            bot_id(:obj:`int` | Collection[:obj:`int`]): Which bot ID(s) to allow
                through.
        """
        return super()._add_chat_ids(bot_id)

    def remove_bot_ids(self, bot_id: SCT[int]) -> None:
        """
        Remove one or more bots from allowed bot ids.

        Args:
            bot_id(:obj:`int` | Collection[:obj:`int`], optional): Which bot ID(s) to
                disallow through.
        """
        return super()._remove_chat_ids(bot_id)


class _ViaBot(MessageFilter):
    __slots__ = ()

    def filter(self, message: Message) -> bool:
        return bool(message.via_bot)


VIA_BOT = _ViaBot(name="filters.VIA_BOT")
"""This filter filters for message that were sent via *any* bot.

.. seealso:: :class:`~telegram.ext.filters.ViaBot`"""


class _Video(MessageFilter):
    __slots__ = ()

    def filter(self, message: Message) -> bool:
        return bool(message.video)


VIDEO = _Video(name="filters.VIDEO")  # pylint: disable=invalid-name
"""Messages that contain :attr:`telegram.Message.video`."""


class _VideoNote(MessageFilter):
    __slots__ = ()

    def filter(self, message: Message) -> bool:
        return bool(message.video_note)


VIDEO_NOTE = _VideoNote(name="filters.VIDEO_NOTE")
"""Messages that contain :attr:`telegram.Message.video_note`."""


class _Voice(MessageFilter):
    __slots__ = ()

    def filter(self, message: Message) -> bool:
        return bool(message.voice)


VOICE = _Voice("filters.VOICE")
"""Messages that contain :attr:`telegram.Message.voice`."""


class _ReplyToStory(MessageFilter):
    __slots__ = ()

    def filter(self, message: Message) -> bool:
        return bool(message.reply_to_story)


REPLY_TO_STORY = _ReplyToStory(name="filters.REPLY_TO_STORY")
"""Messages that contain :attr:`telegram.Message.reply_to_story`."""


class _BoostAdded(MessageFilter):
    __slots__ = ()

    def filter(self, message: Message) -> bool:
        return bool(message.boost_added)


BOOST_ADDED = _BoostAdded(name="filters.BOOST_ADDED")
"""Messages that contain :attr:`telegram.Message.boost_added`."""


class _SenderBoostCount(MessageFilter):
    __slots__ = ()

    def filter(self, message: Message) -> bool:
        return bool(message.sender_boost_count)


SENDER_BOOST_COUNT = _SenderBoostCount(name="filters.SENDER_BOOST_COUNT")
"""Messages that contain :attr:`telegram.Message.sender_boost_count`."""
