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
"""This module contains an object that represents a Telegram Poll."""

import datetime as dtm
from collections.abc import Sequence
from typing import TYPE_CHECKING, Final

from telegram import constants
from telegram._chat import Chat
from telegram._messageentity import MessageEntity
from telegram._telegramobject import TelegramObject
from telegram._user import User
from telegram._utils import enum
from telegram._utils.argumentparsing import (
    de_json_optional,
    de_list_optional,
    parse_sequence_arg,
    to_timedelta,
)
from telegram._utils.datetime import (
    extract_tzinfo_from_defaults,
    from_timestamp,
    get_timedelta_value,
)
from telegram._utils.defaultvalue import DEFAULT_NONE
from telegram._utils.entities import parse_message_entities, parse_message_entity
from telegram._utils.types import JSONDict, ODVInput, TimePeriod

if TYPE_CHECKING:
    from telegram import Bot


class InputPollOption(TelegramObject):
    """
    This object contains information about one answer option in a poll to be sent.

    Objects of this class are comparable in terms of equality. Two objects of this class are
    considered equal, if their :attr:`text` is equal.

    .. versionadded:: 21.2

    Args:
        text (:obj:`str`): Option text,
            :tg-const:`telegram.PollOption.MIN_LENGTH`-:tg-const:`telegram.PollOption.MAX_LENGTH`
            characters.
        text_parse_mode (:obj:`str`, optional): |parse_mode|
            Currently, only custom emoji entities are allowed.
        text_entities (Sequence[:class:`telegram.MessageEntity`], optional): Special entities
            that appear in the option :paramref:`text`. It can be specified instead of
            :paramref:`text_parse_mode`.
            Currently, only custom emoji entities are allowed.
            This list is empty if the text does not contain entities.

    Attributes:
        text (:obj:`str`): Option text,
            :tg-const:`telegram.PollOption.MIN_LENGTH`-:tg-const:`telegram.PollOption.MAX_LENGTH`
            characters.
        text_parse_mode (:obj:`str`): Optional. |parse_mode|
            Currently, only custom emoji entities are allowed.
        text_entities (Sequence[:class:`telegram.MessageEntity`]): Special entities
            that appear in the option :paramref:`text`. It can be specified instead of
            :paramref:`text_parse_mode`.
            Currently, only custom emoji entities are allowed.
            This list is empty if the text does not contain entities.
    """

    __slots__ = ("text", "text_entities", "text_parse_mode")

    def __init__(
        self,
        text: str,
        text_parse_mode: ODVInput[str] = DEFAULT_NONE,
        text_entities: Sequence[MessageEntity] | None = None,
        *,
        api_kwargs: JSONDict | None = None,
    ):
        super().__init__(api_kwargs=api_kwargs)
        self.text: str = text
        self.text_parse_mode: ODVInput[str] = text_parse_mode
        self.text_entities: tuple[MessageEntity, ...] = parse_sequence_arg(text_entities)

        self._id_attrs = (self.text,)

        self._freeze()

    @classmethod
    def de_json(cls, data: JSONDict, bot: "Bot | None" = None) -> "InputPollOption":
        """See :meth:`telegram.TelegramObject.de_json`."""
        data = cls._parse_data(data)

        data["text_entities"] = de_list_optional(data.get("text_entities"), MessageEntity, bot)

        return super().de_json(data=data, bot=bot)


class PollOption(TelegramObject):
    """
    This object contains information about one answer option in a poll.

    Objects of this class are comparable in terms of equality. Two objects of this class are
    considered equal, if their :attr:`text` and :attr:`voter_count` are equal.

    Args:
        text (:obj:`str`): Option text,
            :tg-const:`telegram.PollOption.MIN_LENGTH`-:tg-const:`telegram.PollOption.MAX_LENGTH`
            characters.
        voter_count (:obj:`int`): Number of users that voted for this option.
        text_entities (Sequence[:class:`telegram.MessageEntity`], optional): Special entities
            that appear in the option text. Currently, only custom emoji entities are allowed in
            poll option texts.

            .. versionadded:: 21.2

    Attributes:
        text (:obj:`str`): Option text,
            :tg-const:`telegram.PollOption.MIN_LENGTH`-:tg-const:`telegram.PollOption.MAX_LENGTH`
            characters.
        voter_count (:obj:`int`): Number of users that voted for this option.
        text_entities (tuple[:class:`telegram.MessageEntity`]): Special entities
            that appear in the option text. Currently, only custom emoji entities are allowed in
            poll option texts.
            This list is empty if the question does not contain entities.

            .. versionadded:: 21.2

    """

    __slots__ = ("text", "text_entities", "voter_count")

    def __init__(
        self,
        text: str,
        voter_count: int,
        text_entities: Sequence[MessageEntity] | None = None,
        *,
        api_kwargs: JSONDict | None = None,
    ):
        super().__init__(api_kwargs=api_kwargs)
        self.text: str = text
        self.voter_count: int = voter_count
        self.text_entities: tuple[MessageEntity, ...] = parse_sequence_arg(text_entities)

        self._id_attrs = (self.text, self.voter_count)

        self._freeze()

    @classmethod
    def de_json(cls, data: JSONDict, bot: "Bot | None" = None) -> "PollOption":
        """See :meth:`telegram.TelegramObject.de_json`."""
        data = cls._parse_data(data)

        data["text_entities"] = de_list_optional(data.get("text_entities"), MessageEntity, bot)

        return super().de_json(data=data, bot=bot)

    def parse_entity(self, entity: MessageEntity) -> str:
        """Returns the text in :attr:`text`
        from a given :class:`telegram.MessageEntity` of :attr:`text_entities`.

        Note:
            This method is present because Telegram calculates the offset and length in
            UTF-16 codepoint pairs, which some versions of Python don't handle automatically.
            (That is, you can't just slice ``Message.text`` with the offset and length.)

        .. versionadded:: 21.2

        Args:
            entity (:class:`telegram.MessageEntity`): The entity to extract the text from. It must
                be an entity that belongs to :attr:`text_entities`.

        Returns:
            :obj:`str`: The text of the given entity.
        """
        return parse_message_entity(self.text, entity)

    def parse_entities(self, types: list[str] | None = None) -> dict[MessageEntity, str]:
        """
        Returns a :obj:`dict` that maps :class:`telegram.MessageEntity` to :obj:`str`.
        It contains entities from this polls question filtered by their ``type`` attribute as
        the key, and the text that each entity belongs to as the value of the :obj:`dict`.

        Note:
            This method should always be used instead of the :attr:`text_entities`
            attribute, since it calculates the correct substring from the message text based on
            UTF-16 codepoints. See :attr:`parse_entity` for more info.

        .. versionadded:: 21.2

        Args:
            types (list[:obj:`str`], optional): List of ``MessageEntity`` types as strings. If the
                    ``type`` attribute of an entity is contained in this list, it will be returned.
                    Defaults to :attr:`telegram.MessageEntity.ALL_TYPES`.

        Returns:
            dict[:class:`telegram.MessageEntity`, :obj:`str`]: A dictionary of entities mapped to
            the text that belongs to them, calculated based on UTF-16 codepoints.
        """
        return parse_message_entities(self.text, self.text_entities, types)

    MIN_LENGTH: Final[int] = constants.PollLimit.MIN_OPTION_LENGTH
    """:const:`telegram.constants.PollLimit.MIN_OPTION_LENGTH`

    .. versionadded:: 20.0
    """
    MAX_LENGTH: Final[int] = constants.PollLimit.MAX_OPTION_LENGTH
    """:const:`telegram.constants.PollLimit.MAX_OPTION_LENGTH`

    .. versionadded:: 20.0
    """


class PollAnswer(TelegramObject):
    """
    This object represents an answer of a user in a non-anonymous poll.

    Objects of this class are comparable in terms of equality. Two objects of this class are
    considered equal, if their :attr:`poll_id`, :attr:`user` and :attr:`option_ids` are equal.

    .. versionchanged:: 20.5
        The order of :paramref:`option_ids` and :paramref:`user` is changed in
        20.5 as the latter one became optional.

    .. versionchanged:: 20.6
       Backward compatiblity for changed order of :paramref:`option_ids` and :paramref:`user`
       was removed.

    Args:
        poll_id (:obj:`str`): Unique poll identifier.
        option_ids (Sequence[:obj:`int`]): Identifiers of answer options, chosen by the user. May
            be empty if the user retracted their vote.

            .. versionchanged:: 20.0
                |sequenceclassargs|
        user (:class:`telegram.User`, optional): The user that changed the answer to the poll,
            if the voter isn't anonymous. If the voter is anonymous, this field will contain the
            user :tg-const:`telegram.constants.ChatID.FAKE_CHANNEL` for backwards compatibility.

            .. versionchanged:: 20.5
                :paramref:`user` became optional.
        voter_chat (:class:`telegram.Chat`, optional): The chat that changed the answer to the
            poll, if the voter is anonymous.

            .. versionadded:: 20.5

    Attributes:
        poll_id (:obj:`str`): Unique poll identifier.
        option_ids (tuple[:obj:`int`]): Identifiers of answer options, chosen by the user. May
            be empty if the user retracted their vote.

            .. versionchanged:: 20.0
                |tupleclassattrs|
        user (:class:`telegram.User`): Optional. The user, who changed the answer to the
            poll, if the voter isn't anonymous. If the voter is anonymous, this field will contain
            the user :tg-const:`telegram.constants.ChatID.FAKE_CHANNEL` for backwards compatibility

            .. versionchanged:: 20.5
                :paramref:`user` became optional.
        voter_chat (:class:`telegram.Chat`): Optional. The chat that changed the answer to the
            poll, if the voter is anonymous.

            .. versionadded:: 20.5

    """

    __slots__ = ("option_ids", "poll_id", "user", "voter_chat")

    def __init__(
        self,
        poll_id: str,
        option_ids: Sequence[int],
        user: User | None = None,
        voter_chat: Chat | None = None,
        *,
        api_kwargs: JSONDict | None = None,
    ):
        super().__init__(api_kwargs=api_kwargs)
        self.poll_id: str = poll_id
        self.voter_chat: Chat | None = voter_chat
        self.option_ids: tuple[int, ...] = parse_sequence_arg(option_ids)
        self.user: User | None = user

        self._id_attrs = (
            self.poll_id,
            self.option_ids,
            self.user,
            self.voter_chat,
        )

        self._freeze()

    @classmethod
    def de_json(cls, data: JSONDict, bot: "Bot | None" = None) -> "PollAnswer":
        """See :meth:`telegram.TelegramObject.de_json`."""
        data = cls._parse_data(data)

        data["user"] = de_json_optional(data.get("user"), User, bot)
        data["voter_chat"] = de_json_optional(data.get("voter_chat"), Chat, bot)

        return super().de_json(data=data, bot=bot)


class Poll(TelegramObject):
    """
    This object contains information about a poll.

    Objects of this class are comparable in terms of equality. Two objects of this class are
    considered equal, if their :attr:`id` is equal.

    Examples:
        :any:`Poll Bot <examples.pollbot>`

    Args:
        id (:obj:`str`): Unique poll identifier.
        question (:obj:`str`): Poll question, :tg-const:`telegram.Poll.MIN_QUESTION_LENGTH`-
            :tg-const:`telegram.Poll.MAX_QUESTION_LENGTH` characters.
        options (Sequence[:class:`~telegram.PollOption`]): List of poll options.

            .. versionchanged:: 20.0
                |sequenceclassargs|
        is_closed (:obj:`bool`): :obj:`True`, if the poll is closed.
        is_anonymous (:obj:`bool`): :obj:`True`, if the poll is anonymous.
        type (:obj:`str`): Poll type, currently can be :attr:`REGULAR` or :attr:`QUIZ`.
        allows_multiple_answers (:obj:`bool`): :obj:`True`, if the poll allows multiple answers.
        correct_option_id (:obj:`int`, optional): A zero based identifier of the correct answer
            option. Available only for closed polls in the quiz mode, which were sent
            (not forwarded), by the bot or to a private chat with the bot.
        explanation (:obj:`str`, optional): Text that is shown when a user chooses an incorrect
            answer or taps on the lamp icon in a quiz-style poll,
            0-:tg-const:`telegram.Poll.MAX_EXPLANATION_LENGTH` characters.
        explanation_entities (Sequence[:class:`telegram.MessageEntity`], optional): Special
            entities like usernames, URLs, bot commands, etc. that appear in the
            :attr:`explanation`. This list is empty if the message does not contain explanation
            entities.

            .. versionchanged:: 20.0

               * This attribute is now always a (possibly empty) list and never :obj:`None`.
               * |sequenceclassargs|
        open_period (:obj:`int` | :class:`datetime.timedelta`, optional): Amount of time in seconds
            the poll will be active after creation.

            .. versionchanged:: v22.2
                |time-period-input|
        close_date (:obj:`datetime.datetime`, optional): Point in time (Unix timestamp) when the
            poll will be automatically closed. Converted to :obj:`datetime.datetime`.

            .. versionchanged:: 20.3
                |datetime_localization|
        question_entities (Sequence[:class:`telegram.MessageEntity`], optional): Special entities
            that appear in the :attr:`question`. Currently, only custom emoji entities are allowed
            in poll questions.

            .. versionadded:: 21.2

    Attributes:
        id (:obj:`str`): Unique poll identifier.
        question (:obj:`str`): Poll question, :tg-const:`telegram.Poll.MIN_QUESTION_LENGTH`-
            :tg-const:`telegram.Poll.MAX_QUESTION_LENGTH` characters.
        options (tuple[:class:`~telegram.PollOption`]): List of poll options.

            .. versionchanged:: 20.0
                |tupleclassattrs|
        total_voter_count (:obj:`int`): Total number of users that voted in the poll.
        is_closed (:obj:`bool`): :obj:`True`, if the poll is closed.
        is_anonymous (:obj:`bool`): :obj:`True`, if the poll is anonymous.
        type (:obj:`str`): Poll type, currently can be :attr:`REGULAR` or :attr:`QUIZ`.
        allows_multiple_answers (:obj:`bool`): :obj:`True`, if the poll allows multiple answers.
        correct_option_id (:obj:`int`): Optional. A zero based identifier of the correct answer
            option. Available only for closed polls in the quiz mode, which were sent
            (not forwarded), by the bot or to a private chat with the bot.
        explanation (:obj:`str`): Optional. Text that is shown when a user chooses an incorrect
            answer or taps on the lamp icon in a quiz-style poll,
            0-:tg-const:`telegram.Poll.MAX_EXPLANATION_LENGTH` characters.
        explanation_entities (tuple[:class:`telegram.MessageEntity`]): Special entities
            like usernames, URLs, bot commands, etc. that appear in the :attr:`explanation`.
            This list is empty if the message does not contain explanation entities.

            .. versionchanged:: 20.0
                |tupleclassattrs|

            .. versionchanged:: 20.0
               This attribute is now always a (possibly empty) list and never :obj:`None`.
        open_period (:obj:`int` | :class:`datetime.timedelta`): Optional. Amount of time in seconds
            the poll will be active after creation.

            .. deprecated:: v22.2
                |time-period-int-deprecated|
        close_date (:obj:`datetime.datetime`): Optional. Point in time when the poll will be
            automatically closed.

            .. versionchanged:: 20.3
                |datetime_localization|
        question_entities (tuple[:class:`telegram.MessageEntity`]): Special entities
            that appear in the :attr:`question`. Currently, only custom emoji entities are allowed
            in poll questions.
            This list is empty if the question does not contain entities.

            .. versionadded:: 21.2

    """

    __slots__ = (
        "_open_period",
        "allows_multiple_answers",
        "close_date",
        "correct_option_id",
        "explanation",
        "explanation_entities",
        "id",
        "is_anonymous",
        "is_closed",
        "options",
        "question",
        "question_entities",
        "total_voter_count",
        "type",
    )

    def __init__(
        self,
        id: str,  # pylint: disable=redefined-builtin
        question: str,
        options: Sequence[PollOption],
        total_voter_count: int,
        is_closed: bool,
        is_anonymous: bool,
        type: str,  # pylint: disable=redefined-builtin
        allows_multiple_answers: bool,
        correct_option_id: int | None = None,
        explanation: str | None = None,
        explanation_entities: Sequence[MessageEntity] | None = None,
        open_period: TimePeriod | None = None,
        close_date: dtm.datetime | None = None,
        question_entities: Sequence[MessageEntity] | None = None,
        *,
        api_kwargs: JSONDict | None = None,
    ):
        super().__init__(api_kwargs=api_kwargs)
        self.id: str = id
        self.question: str = question
        self.options: tuple[PollOption, ...] = parse_sequence_arg(options)
        self.total_voter_count: int = total_voter_count
        self.is_closed: bool = is_closed
        self.is_anonymous: bool = is_anonymous
        self.type: str = enum.get_member(constants.PollType, type, type)
        self.allows_multiple_answers: bool = allows_multiple_answers
        self.correct_option_id: int | None = correct_option_id
        self.explanation: str | None = explanation
        self.explanation_entities: tuple[MessageEntity, ...] = parse_sequence_arg(
            explanation_entities
        )
        self._open_period: dtm.timedelta | None = to_timedelta(open_period)
        self.close_date: dtm.datetime | None = close_date
        self.question_entities: tuple[MessageEntity, ...] = parse_sequence_arg(question_entities)

        self._id_attrs = (self.id,)

        self._freeze()

    @property
    def open_period(self) -> int | dtm.timedelta | None:
        return get_timedelta_value(self._open_period, attribute="open_period")

    @classmethod
    def de_json(cls, data: JSONDict, bot: "Bot | None" = None) -> "Poll":
        """See :meth:`telegram.TelegramObject.de_json`."""
        data = cls._parse_data(data)

        # Get the local timezone from the bot if it has defaults
        loc_tzinfo = extract_tzinfo_from_defaults(bot)

        data["options"] = de_list_optional(data.get("options"), PollOption, bot)
        data["explanation_entities"] = de_list_optional(
            data.get("explanation_entities"), MessageEntity, bot
        )
        data["close_date"] = from_timestamp(data.get("close_date"), tzinfo=loc_tzinfo)
        data["question_entities"] = de_list_optional(
            data.get("question_entities"), MessageEntity, bot
        )

        return super().de_json(data=data, bot=bot)

    def parse_explanation_entity(self, entity: MessageEntity) -> str:
        """Returns the text in :attr:`explanation` from a given :class:`telegram.MessageEntity` of
        :attr:`explanation_entities`.

        Note:
            This method is present because Telegram calculates the offset and length in
            UTF-16 codepoint pairs, which some versions of Python don't handle automatically.
            (That is, you can't just slice ``Message.text`` with the offset and length.)

        Args:
            entity (:class:`telegram.MessageEntity`): The entity to extract the text from. It must
                be an entity that belongs to :attr:`explanation_entities`.

        Returns:
            :obj:`str`: The text of the given entity.

        Raises:
            RuntimeError: If the poll has no explanation.

        """
        if not self.explanation:
            raise RuntimeError("This Poll has no 'explanation'.")

        return parse_message_entity(self.explanation, entity)

    def parse_explanation_entities(
        self, types: list[str] | None = None
    ) -> dict[MessageEntity, str]:
        """
        Returns a :obj:`dict` that maps :class:`telegram.MessageEntity` to :obj:`str`.
        It contains entities from this polls explanation filtered by their ``type`` attribute as
        the key, and the text that each entity belongs to as the value of the :obj:`dict`.

        Note:
            This method should always be used instead of the :attr:`explanation_entities`
            attribute, since it calculates the correct substring from the message text based on
            UTF-16 codepoints. See :attr:`parse_explanation_entity` for more info.

        Args:
            types (list[:obj:`str`], optional): List of ``MessageEntity`` types as strings. If the
                    ``type`` attribute of an entity is contained in this list, it will be returned.
                    Defaults to :attr:`telegram.MessageEntity.ALL_TYPES`.

        Returns:
            dict[:class:`telegram.MessageEntity`, :obj:`str`]: A dictionary of entities mapped to
            the text that belongs to them, calculated based on UTF-16 codepoints.

        Raises:
            RuntimeError: If the poll has no explanation.

        """
        if not self.explanation:
            raise RuntimeError("This Poll has no 'explanation'.")

        return parse_message_entities(self.explanation, self.explanation_entities, types)

    def parse_question_entity(self, entity: MessageEntity) -> str:
        """Returns the text in :attr:`question` from a given :class:`telegram.MessageEntity` of
        :attr:`question_entities`.

        .. versionadded:: 21.2

        Note:
            This method is present because Telegram calculates the offset and length in
            UTF-16 codepoint pairs, which some versions of Python don't handle automatically.
            (That is, you can't just slice ``Message.text`` with the offset and length.)

        Args:
            entity (:class:`telegram.MessageEntity`): The entity to extract the text from. It must
                be an entity that belongs to :attr:`question_entities`.

        Returns:
            :obj:`str`: The text of the given entity.
        """
        return parse_message_entity(self.question, entity)

    def parse_question_entities(self, types: list[str] | None = None) -> dict[MessageEntity, str]:
        """
        Returns a :obj:`dict` that maps :class:`telegram.MessageEntity` to :obj:`str`.
        It contains entities from this polls question filtered by their ``type`` attribute as
        the key, and the text that each entity belongs to as the value of the :obj:`dict`.

        .. versionadded:: 21.2

        Note:
            This method should always be used instead of the :attr:`question_entities`
            attribute, since it calculates the correct substring from the message text based on
            UTF-16 codepoints. See :attr:`parse_question_entity` for more info.

        Args:
            types (list[:obj:`str`], optional): List of ``MessageEntity`` types as strings. If the
                    ``type`` attribute of an entity is contained in this list, it will be returned.
                    Defaults to :attr:`telegram.MessageEntity.ALL_TYPES`.

        Returns:
            dict[:class:`telegram.MessageEntity`, :obj:`str`]: A dictionary of entities mapped to
            the text that belongs to them, calculated based on UTF-16 codepoints.

        """
        return parse_message_entities(self.question, self.question_entities, types)

    REGULAR: Final[str] = constants.PollType.REGULAR
    """:const:`telegram.constants.PollType.REGULAR`"""
    QUIZ: Final[str] = constants.PollType.QUIZ
    """:const:`telegram.constants.PollType.QUIZ`"""
    MAX_EXPLANATION_LENGTH: Final[int] = constants.PollLimit.MAX_EXPLANATION_LENGTH
    """:const:`telegram.constants.PollLimit.MAX_EXPLANATION_LENGTH`

    .. versionadded:: 20.0
    """
    MAX_EXPLANATION_LINE_FEEDS: Final[int] = constants.PollLimit.MAX_EXPLANATION_LINE_FEEDS
    """:const:`telegram.constants.PollLimit.MAX_EXPLANATION_LINE_FEEDS`

    .. versionadded:: 20.0
    """
    MIN_OPEN_PERIOD: Final[int] = constants.PollLimit.MIN_OPEN_PERIOD
    """:const:`telegram.constants.PollLimit.MIN_OPEN_PERIOD`

    .. versionadded:: 20.0
    """
    MAX_OPEN_PERIOD: Final[int] = constants.PollLimit.MAX_OPEN_PERIOD
    """:const:`telegram.constants.PollLimit.MAX_OPEN_PERIOD`

    .. versionadded:: 20.0
    """
    MIN_QUESTION_LENGTH: Final[int] = constants.PollLimit.MIN_QUESTION_LENGTH
    """:const:`telegram.constants.PollLimit.MIN_QUESTION_LENGTH`

    .. versionadded:: 20.0
    """
    MAX_QUESTION_LENGTH: Final[int] = constants.PollLimit.MAX_QUESTION_LENGTH
    """:const:`telegram.constants.PollLimit.MAX_QUESTION_LENGTH`

    .. versionadded:: 20.0
    """
    MIN_OPTION_LENGTH: Final[int] = constants.PollLimit.MIN_OPTION_LENGTH
    """:const:`telegram.constants.PollLimit.MIN_OPTION_LENGTH`

    .. versionadded:: 20.0
    """
    MAX_OPTION_LENGTH: Final[int] = constants.PollLimit.MAX_OPTION_LENGTH
    """:const:`telegram.constants.PollLimit.MAX_OPTION_LENGTH`

    .. versionadded:: 20.0
    """
    MIN_OPTION_NUMBER: Final[int] = constants.PollLimit.MIN_OPTION_NUMBER
    """:const:`telegram.constants.PollLimit.MIN_OPTION_NUMBER`

    .. versionadded:: 20.0
    """
    MAX_OPTION_NUMBER: Final[int] = constants.PollLimit.MAX_OPTION_NUMBER
    """:const:`telegram.constants.PollLimit.MAX_OPTION_NUMBER`

    .. versionadded:: 20.0
    """
