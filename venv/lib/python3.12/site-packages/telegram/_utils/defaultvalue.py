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
"""This module contains the DefaultValue class.

.. versionchanged:: 20.0
   Previously, the contents of this module were available through the (no longer existing)
   module ``telegram._utils.helpers``.

Warning:
    Contents of this module are intended to be used internally by the library and *not* by the
    user. Changes to this module are not considered breaking changes and may not be documented in
    the changelog.
"""

from typing import Generic, TypeVar, overload

DVType = TypeVar("DVType", bound=object)  # pylint: disable=invalid-name
OT = TypeVar("OT", bound=object)


class DefaultValue(Generic[DVType]):
    """Wrapper for immutable default arguments that allows to check, if the default value was set
    explicitly. Usage::

        default_one = DefaultValue(1)
        def f(arg=default_one):
            if arg is default_one:
                print('`arg` is the default')
                arg = arg.value
            else:
                print('`arg` was set explicitly')
            print(f'`arg` = {str(arg)}')

    This yields::

        >>> f()
        `arg` is the default
        `arg` = 1
        >>> f(1)
        `arg` was set explicitly
        `arg` = 1
        >>> f(2)
        `arg` was set explicitly
        `arg` = 2

    Also allows to evaluate truthiness::

        default = DefaultValue(value)
        if default:
            ...

    is equivalent to::

        default = DefaultValue(value)
        if value:
            ...

    ``repr(DefaultValue(value))`` returns ``repr(value)`` and ``str(DefaultValue(value))`` returns
    ``f'DefaultValue({value})'``.

    Args:
        value (:class:`object`): The value of the default argument
    Attributes:
        value (:class:`object`): The value of the default argument

    """

    __slots__ = ("value",)

    def __init__(self, value: DVType):
        self.value: DVType = value

    def __bool__(self) -> bool:
        return bool(self.value)

    # This is mostly here for readability during debugging
    def __str__(self) -> str:
        return f"DefaultValue({self.value})"

    # This is here to have the default instances nicely rendered in the docs
    def __repr__(self) -> str:
        return repr(self.value)

    @overload
    @staticmethod
    def get_value(obj: "DefaultValue[OT]") -> OT: ...

    @overload
    @staticmethod
    def get_value(obj: OT) -> OT: ...

    @staticmethod
    def get_value(obj: "OT | DefaultValue[OT]") -> OT:
        """Shortcut for::

            return obj.value if isinstance(obj, DefaultValue) else obj

        Args:
            obj (:obj:`object`): The object to process

        Returns:
            Same type as input, or the value of the input: The value
        """
        return obj.value if isinstance(obj, DefaultValue) else obj


DEFAULT_NONE: DefaultValue[None] = DefaultValue(None)
""":class:`DefaultValue`: Default :obj:`None`"""

DEFAULT_FALSE: DefaultValue[bool] = DefaultValue(False)
""":class:`DefaultValue`: Default :obj:`False`"""

DEFAULT_TRUE: DefaultValue[bool] = DefaultValue(True)
""":class:`DefaultValue`: Default :obj:`True`

.. versionadded:: 20.0
"""


DEFAULT_20: DefaultValue[int] = DefaultValue(20)
""":class:`DefaultValue`: Default :obj:`20`"""

DEFAULT_IP: DefaultValue[str] = DefaultValue("127.0.0.1")
""":class:`DefaultValue`: Default :obj:`127.0.0.1`

.. versionadded:: 20.8
"""

DEFAULT_80: DefaultValue[int] = DefaultValue(80)
""":class:`DefaultValue`: Default :obj:`80`

.. versionadded:: 20.8
"""
