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
"""This module contains an objects related to Telegram checklists."""

import datetime as dtm
from collections.abc import Sequence
from typing import TYPE_CHECKING, Optional

from telegram._chat import Chat
from telegram._messageentity import MessageEntity
from telegram._telegramobject import TelegramObject
from telegram._user import User
from telegram._utils.argumentparsing import de_json_optional, de_list_optional, parse_sequence_arg
from telegram._utils.datetime import extract_tzinfo_from_defaults, from_timestamp
from telegram._utils.entities import parse_message_entities, parse_message_entity
from telegram._utils.types import JSONDict
from telegram.constants import ZERO_DATE

if TYPE_CHECKING:
    from telegram import Bot, Message


class ChecklistTask(TelegramObject):
    """
    Describes a task in a checklist.

    Objects of this class are comparable in terms of equality.
    Two objects of this class are considered equal, if their :attr:`id` is equal.

    .. versionadded:: 22.3

    Args:
        id (:obj:`int`): Unique identifier of the task.
        text (:obj:`str`): Text of the task.
        text_entities (Sequence[:class:`telegram.MessageEntity`], optional): Special
            entities that appear in the task text.
        completed_by_user (:class:`telegram.User`, optional): User that completed the task; omitted
            if the task wasn't completed
        completed_by_chat (:class:`telegram.Chat`, optional): Chat that completed the task; omitted
            if the task wasn't completed by a chat

            .. versionadded:: 22.6
        completion_date (:class:`datetime.datetime`, optional): Point in time when
            the task was completed; :attr:`~telegram.constants.ZERO_DATE` if the task wasn't
            completed

            |datetime_localization|

    Attributes:
        id (:obj:`int`): Unique identifier of the task.
        text (:obj:`str`): Text of the task.
        text_entities (Tuple[:class:`telegram.MessageEntity`]): Optional. Special
            entities that appear in the task text.
        completed_by_user (:class:`telegram.User`): Optional. User that completed the task; omitted
            if the task wasn't completed
        completed_by_chat (:class:`telegram.Chat`): Optional. Chat that completed the task; omitted
            if the task wasn't completed by a chat

            .. versionadded:: 22.6
        completion_date (:class:`datetime.datetime`): Optional. Point in time when
            the task was completed; :attr:`~telegram.constants.ZERO_DATE` if the task wasn't
            completed

            |datetime_localization|
    """

    __slots__ = (
        "completed_by_chat",
        "completed_by_user",
        "completion_date",
        "id",
        "text",
        "text_entities",
    )

    def __init__(
        self,
        id: int,  # pylint: disable=redefined-builtin
        text: str,
        text_entities: Sequence[MessageEntity] | None = None,
        completed_by_user: User | None = None,
        completion_date: dtm.datetime | None = None,
        completed_by_chat: Chat | None = None,
        *,
        api_kwargs: JSONDict | None = None,
    ):
        super().__init__(api_kwargs=api_kwargs)
        self.id: int = id
        self.text: str = text
        self.text_entities: tuple[MessageEntity, ...] = parse_sequence_arg(text_entities)
        self.completed_by_user: User | None = completed_by_user
        self.completed_by_chat: Chat | None = completed_by_chat
        self.completion_date: dtm.datetime | None = completion_date

        self._id_attrs = (self.id,)

        self._freeze()

    @classmethod
    def de_json(cls, data: JSONDict, bot: Optional["Bot"] = None) -> "ChecklistTask":
        """See :meth:`telegram.TelegramObject.de_json`."""
        data = cls._parse_data(data)

        # Get the local timezone from the bot if it has defaults
        loc_tzinfo = extract_tzinfo_from_defaults(bot)

        if (date := data.get("completion_date")) == 0:
            data["completion_date"] = ZERO_DATE
        else:
            data["completion_date"] = from_timestamp(date, tzinfo=loc_tzinfo)

        data["completed_by_user"] = de_json_optional(data.get("completed_by_user"), User, bot)
        data["completed_by_chat"] = de_json_optional(data.get("completed_by_chat"), Chat, bot)
        data["text_entities"] = de_list_optional(data.get("text_entities"), MessageEntity, bot)

        return super().de_json(data=data, bot=bot)

    def parse_entity(self, entity: MessageEntity) -> str:
        """Returns the text in :attr:`text`
        from a given :class:`telegram.MessageEntity` of :attr:`text_entities`.

        Note:
            This method is present because Telegram calculates the offset and length in
            UTF-16 codepoint pairs, which some versions of Python don't handle automatically.
            (That is, you can't just slice ``ChecklistTask.text`` with the offset and length.)

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
        It contains entities from this checklist task filtered by their ``type`` attribute as
        the key, and the text that each entity belongs to as the value of the :obj:`dict`.

        Note:
            This method should always be used instead of the :attr:`text_entities`
            attribute, since it calculates the correct substring from the message text based on
            UTF-16 codepoints. See :attr:`parse_entity` for more info.

        Args:
            types (list[:obj:`str`], optional): List of ``MessageEntity`` types as strings. If the
                    ``type`` attribute of an entity is contained in this list, it will be returned.
                    Defaults to :attr:`telegram.MessageEntity.ALL_TYPES`.

        Returns:
            dict[:class:`telegram.MessageEntity`, :obj:`str`]: A dictionary of entities mapped to
            the text that belongs to them, calculated based on UTF-16 codepoints.
        """
        return parse_message_entities(self.text, self.text_entities, types)


class Checklist(TelegramObject):
    """
    Describes a checklist.

    Objects of this class are comparable in terms of equality.
    Two objects of this class are considered equal, if all their :attr:`tasks` are equal.

    .. versionadded:: 22.3

    Args:
        title (:obj:`str`): Title of the checklist.
        title_entities (Sequence[:class:`telegram.MessageEntity`], optional): Special
            entities that appear in the checklist title.
        tasks (Sequence[:class:`telegram.ChecklistTask`]): List of tasks in the checklist.
        others_can_add_tasks (:obj:`bool`, optional): :obj:`True` if users other than the creator
            of the list can add tasks to the list
        others_can_mark_tasks_as_done (:obj:`bool`, optional): :obj:`True` if users other than the
            creator of the list can mark tasks as done or not done

    Attributes:
        title (:obj:`str`): Title of the checklist.
        title_entities (Tuple[:class:`telegram.MessageEntity`]): Optional. Special
            entities that appear in the checklist title.
        tasks (Tuple[:class:`telegram.ChecklistTask`]): List of tasks in the checklist.
        others_can_add_tasks (:obj:`bool`): Optional. :obj:`True` if users other than the creator
            of the list can add tasks to the list
        others_can_mark_tasks_as_done (:obj:`bool`): Optional. :obj:`True` if users other than the
            creator of the list can mark tasks as done or not done
    """

    __slots__ = (
        "others_can_add_tasks",
        "others_can_mark_tasks_as_done",
        "tasks",
        "title",
        "title_entities",
    )

    def __init__(
        self,
        title: str,
        tasks: Sequence[ChecklistTask],
        title_entities: Sequence[MessageEntity] | None = None,
        others_can_add_tasks: bool | None = None,
        others_can_mark_tasks_as_done: bool | None = None,
        *,
        api_kwargs: JSONDict | None = None,
    ):
        super().__init__(api_kwargs=api_kwargs)
        self.title: str = title
        self.title_entities: tuple[MessageEntity, ...] = parse_sequence_arg(title_entities)
        self.tasks: tuple[ChecklistTask, ...] = parse_sequence_arg(tasks)
        self.others_can_add_tasks: bool | None = others_can_add_tasks
        self.others_can_mark_tasks_as_done: bool | None = others_can_mark_tasks_as_done

        self._id_attrs = (self.tasks,)

        self._freeze()

    @classmethod
    def de_json(cls, data: JSONDict, bot: Optional["Bot"] = None) -> "Checklist":
        """See :meth:`telegram.TelegramObject.de_json`."""
        data = cls._parse_data(data)

        data["title_entities"] = de_list_optional(data.get("title_entities"), MessageEntity, bot)
        data["tasks"] = de_list_optional(data.get("tasks"), ChecklistTask, bot)

        return super().de_json(data=data, bot=bot)

    def parse_entity(self, entity: MessageEntity) -> str:
        """Returns the text in :attr:`title`
        from a given :class:`telegram.MessageEntity` of :attr:`title_entities`.

        Note:
            This method is present because Telegram calculates the offset and length in
            UTF-16 codepoint pairs, which some versions of Python don't handle automatically.
            (That is, you can't just slice :attr:`title` with the offset and length.)

        Args:
            entity (:class:`telegram.MessageEntity`): The entity to extract the text from. It must
                be an entity that belongs to :attr:`title_entities`.

        Returns:
            :obj:`str`: The text of the given entity.
        """
        return parse_message_entity(self.title, entity)

    def parse_entities(self, types: list[str] | None = None) -> dict[MessageEntity, str]:
        """
        Returns a :obj:`dict` that maps :class:`telegram.MessageEntity` to :obj:`str`.
        It contains entities from this checklist's title filtered by their ``type`` attribute as
        the key, and the text that each entity belongs to as the value of the :obj:`dict`.

        Note:
            This method should always be used instead of the :attr:`title_entities`
            attribute, since it calculates the correct substring from the message text based on
            UTF-16 codepoints. See :attr:`parse_entity` for more info.

        Args:
            types (list[:obj:`str`], optional): List of ``MessageEntity`` types as strings. If the
                    ``type`` attribute of an entity is contained in this list, it will be returned.
                    Defaults to :attr:`telegram.MessageEntity.ALL_TYPES`.

        Returns:
            dict[:class:`telegram.MessageEntity`, :obj:`str`]: A dictionary of entities mapped to
            the text that belongs to them, calculated based on UTF-16 codepoints.
        """
        return parse_message_entities(self.title, self.title_entities, types)


class ChecklistTasksDone(TelegramObject):
    """
    Describes a service message about checklist tasks marked as done or not done.

    Objects of this class are comparable in terms of equality.
    Two objects of this class are considered equal, if their :attr:`marked_as_done_task_ids` and
    :attr:`marked_as_not_done_task_ids` are equal.

    .. versionadded:: 22.3

    Args:
        checklist_message (:class:`telegram.Message`, optional): Message containing the checklist
            whose tasks were marked as done or not done. Note that the ~:class:`telegram.Message`
            object in this field will not contain the :attr:`~telegram.Message.reply_to_message`
            field even if it itself is a reply.
        marked_as_done_task_ids (Sequence[:obj:`int`], optional): Identifiers of the tasks that
            were marked as done
        marked_as_not_done_task_ids (Sequence[:obj:`int`], optional): Identifiers of the tasks that
            were marked as not done

    Attributes:
        checklist_message (:class:`telegram.Message`): Optional. Message containing the checklist
            whose tasks were marked as done or not done. Note that the ~:class:`telegram.Message`
            object in this field will not contain the :attr:`~telegram.Message.reply_to_message`
            field even if it itself is a reply.
        marked_as_done_task_ids (Tuple[:obj:`int`]): Optional. Identifiers of the tasks that were
            marked as done
        marked_as_not_done_task_ids (Tuple[:obj:`int`]): Optional. Identifiers of the tasks that
            were marked as not done
    """

    __slots__ = (
        "checklist_message",
        "marked_as_done_task_ids",
        "marked_as_not_done_task_ids",
    )

    def __init__(
        self,
        checklist_message: Optional["Message"] = None,
        marked_as_done_task_ids: Sequence[int] | None = None,
        marked_as_not_done_task_ids: Sequence[int] | None = None,
        *,
        api_kwargs: JSONDict | None = None,
    ):
        super().__init__(api_kwargs=api_kwargs)
        self.checklist_message: Message | None = checklist_message
        self.marked_as_done_task_ids: tuple[int, ...] = parse_sequence_arg(marked_as_done_task_ids)
        self.marked_as_not_done_task_ids: tuple[int, ...] = parse_sequence_arg(
            marked_as_not_done_task_ids
        )

        self._id_attrs = (self.marked_as_done_task_ids, self.marked_as_not_done_task_ids)

        self._freeze()

    @classmethod
    def de_json(cls, data: JSONDict, bot: Optional["Bot"] = None) -> "ChecklistTasksDone":
        """See :meth:`telegram.TelegramObject.de_json`."""
        data = cls._parse_data(data)

        # needs to be imported here to avoid circular import issues
        from telegram import Message  # pylint: disable=import-outside-toplevel  # noqa: PLC0415

        data["checklist_message"] = de_json_optional(data.get("checklist_message"), Message, bot)

        return super().de_json(data=data, bot=bot)


class ChecklistTasksAdded(TelegramObject):
    """
    Describes a service message about tasks added to a checklist.

    Objects of this class are comparable in terms of equality.
    Two objects of this class are considered equal, if their :attr:`tasks` are equal.

    .. versionadded:: 22.3

    Args:
        checklist_message (:class:`telegram.Message`, optional): Message containing the checklist
            to which tasks were added. Note that the ~:class:`telegram.Message`
            object in this field will not contain the :attr:`~telegram.Message.reply_to_message`
            field even if it itself is a reply.
        tasks (Sequence[:class:`telegram.ChecklistTask`]): List of tasks added to the checklist

    Attributes:
        checklist_message (:class:`telegram.Message`): Optional. Message containing the checklist
            to which tasks were added. Note that the ~:class:`telegram.Message`
            object in this field will not contain the :attr:`~telegram.Message.reply_to_message`
            field even if it itself is a reply.
        tasks (Tuple[:class:`telegram.ChecklistTask`]): List of tasks added to the checklist
    """

    __slots__ = ("checklist_message", "tasks")

    def __init__(
        self,
        tasks: Sequence[ChecklistTask],
        checklist_message: Optional["Message"] = None,
        *,
        api_kwargs: JSONDict | None = None,
    ):
        super().__init__(api_kwargs=api_kwargs)
        self.checklist_message: Message | None = checklist_message
        self.tasks: tuple[ChecklistTask, ...] = parse_sequence_arg(tasks)

        self._id_attrs = (self.tasks,)

        self._freeze()

    @classmethod
    def de_json(cls, data: JSONDict, bot: Optional["Bot"] = None) -> "ChecklistTasksAdded":
        """See :meth:`telegram.TelegramObject.de_json`."""
        data = cls._parse_data(data)

        # needs to be imported here to avoid circular import issues
        from telegram import Message  # pylint: disable=import-outside-toplevel  # noqa: PLC0415

        data["checklist_message"] = de_json_optional(data.get("checklist_message"), Message, bot)
        data["tasks"] = ChecklistTask.de_list(data.get("tasks", []), bot)

        return super().de_json(data=data, bot=bot)
