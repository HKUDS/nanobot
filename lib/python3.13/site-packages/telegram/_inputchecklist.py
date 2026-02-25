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
"""This module contains an objects that are related to Telegram input checklists."""

from collections.abc import Sequence

from telegram._messageentity import MessageEntity
from telegram._telegramobject import TelegramObject
from telegram._utils.argumentparsing import parse_sequence_arg
from telegram._utils.defaultvalue import DEFAULT_NONE
from telegram._utils.types import JSONDict, ODVInput


class InputChecklistTask(TelegramObject):
    """
    Describes a task to add to a checklist.

    Objects of this class are comparable in terms of equality.
    Two objects of this class are considered equal if their :attr:`id` is equal.

    .. versionadded:: 22.3

    Args:
        id (:obj:`int`):
            Unique identifier of the task; must be positive and unique among all task identifiers
            currently present in the checklist.
        text (:obj:`str`):
            Text of the task;
            :tg-const:`telegram.constants.InputChecklistLimit.MIN_TEXT_LENGTH`\
-:tg-const:`telegram.constants.InputChecklistLimit.MAX_TEXT_LENGTH` characters after
            entities parsing.
        parse_mode (:obj:`str`, optional):
            |parse_mode|
        text_entities (Sequence[:class:`telegram.MessageEntity`], optional):
            List of special entities that appear in the text, which can be specified instead of
            parse_mode. Currently, only bold, italic, underline, strikethrough, spoiler, and
            custom_emoji entities are allowed.

    Attributes:
        id (:obj:`int`):
            Unique identifier of the task; must be positive and unique among all task identifiers
            currently present in the checklist.
        text (:obj:`str`):
            Text of the task;
            :tg-const:`telegram.constants.InputChecklistLimit.MIN_TEXT_LENGTH`\
-:tg-const:`telegram.constants.InputChecklistLimit.MAX_TEXT_LENGTH` characters after
            entities parsing.
        parse_mode (:obj:`str`):
            Optional. |parse_mode|
        text_entities (Sequence[:class:`telegram.MessageEntity`]):
            Optional. List of special entities that appear in the text, which can be specified
            instead of parse_mode. Currently, only bold, italic, underline, strikethrough, spoiler,
            and custom_emoji entities are allowed.

    """

    __slots__ = (
        "id",
        "parse_mode",
        "text",
        "text_entities",
    )

    def __init__(
        self,
        id: int,  # pylint: disable=redefined-builtin
        text: str,
        parse_mode: ODVInput[str] = DEFAULT_NONE,
        text_entities: Sequence[MessageEntity] | None = None,
        *,
        api_kwargs: JSONDict | None = None,
    ):
        super().__init__(api_kwargs=api_kwargs)
        self.id: int = id
        self.text: str = text
        self.parse_mode: ODVInput[str] = parse_mode
        self.text_entities: tuple[MessageEntity, ...] = parse_sequence_arg(text_entities)

        self._id_attrs = (self.id,)

        self._freeze()


class InputChecklist(TelegramObject):
    """
    Describes a checklist to create.

    Objects of this class are comparable in terms of equality.
    Two objects of this class are considered equal if their :attr:`tasks` is equal.

    .. versionadded:: 22.3

    Args:
        title (:obj:`str`):
            Title of the checklist;
            :tg-const:`telegram.constants.InputChecklistLimit.MIN_TITLE_LENGTH`\
-:tg-const:`telegram.constants.InputChecklistLimit.MAX_TITLE_LENGTH` characters after
            entities parsing.
        parse_mode (:obj:`str`, optional):
            |parse_mode|
        title_entities (Sequence[:class:`telegram.MessageEntity`], optional):
            List of special entities that appear in the title, which
            can be specified instead of :paramref:`parse_mode`. Currently, only bold, italic,
            underline, strikethrough, spoiler, and custom_emoji entities are allowed.
        tasks (Sequence[:class:`telegram.InputChecklistTask`]):
            List of
            :tg-const:`telegram.constants.InputChecklistLimit.MIN_TASK_NUMBER`\
-:tg-const:`telegram.constants.InputChecklistLimit.MAX_TASK_NUMBER` tasks in
            the checklist.
        others_can_add_tasks (:obj:`bool`, optional):
            Pass :obj:`True` if other users can add tasks to the checklist.
        others_can_mark_tasks_as_done (:obj:`bool`, optional):
            Pass :obj:`True` if other users can mark tasks as done or not done in the checklist.

    Attributes:
        title (:obj:`str`):
            Title of the checklist;
            :tg-const:`telegram.constants.InputChecklistLimit.MIN_TITLE_LENGTH`\
-:tg-const:`telegram.constants.InputChecklistLimit.MAX_TITLE_LENGTH` characters after
            entities parsing.
        parse_mode (:obj:`str`):
            Optional. |parse_mode|
        title_entities (Sequence[:class:`telegram.MessageEntity`]):
            Optional. List of special entities that appear in the title, which
            can be specified instead of :paramref:`parse_mode`. Currently, only bold, italic,
            underline, strikethrough, spoiler, and custom_emoji entities are allowed.
        tasks (Sequence[:class:`telegram.InputChecklistTask`]):
            List of
            :tg-const:`telegram.constants.InputChecklistLimit.MIN_TASK_NUMBER`\
-:tg-const:`telegram.constants.InputChecklistLimit.MAX_TASK_NUMBER` tasks in
            the checklist.
        others_can_add_tasks (:obj:`bool`):
            Optional. Pass :obj:`True` if other users can add tasks to the checklist.
        others_can_mark_tasks_as_done (:obj:`bool`):
            Optional. Pass :obj:`True` if other users can mark tasks as done or not done in
            the checklist.

    """

    __slots__ = (
        "others_can_add_tasks",
        "others_can_mark_tasks_as_done",
        "parse_mode",
        "tasks",
        "title",
        "title_entities",
    )

    def __init__(
        self,
        title: str,
        tasks: Sequence[InputChecklistTask],
        parse_mode: ODVInput[str] = DEFAULT_NONE,
        title_entities: Sequence[MessageEntity] | None = None,
        others_can_add_tasks: bool | None = None,
        others_can_mark_tasks_as_done: bool | None = None,
        *,
        api_kwargs: JSONDict | None = None,
    ):
        super().__init__(api_kwargs=api_kwargs)
        self.title: str = title
        self.tasks: tuple[InputChecklistTask, ...] = parse_sequence_arg(tasks)
        self.parse_mode: ODVInput[str] = parse_mode
        self.title_entities: tuple[MessageEntity, ...] = parse_sequence_arg(title_entities)
        self.others_can_add_tasks: bool | None = others_can_add_tasks
        self.others_can_mark_tasks_as_done: bool | None = others_can_mark_tasks_as_done

        self._id_attrs = (self.tasks,)

        self._freeze()
