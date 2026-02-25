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
"""This module contains the base class for handlers as used by the Application."""

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, Generic, TypeVar

from telegram._utils.defaultvalue import DEFAULT_TRUE
from telegram._utils.repr import build_repr_with_selected_attrs
from telegram._utils.types import DVType
from telegram.ext._utils.types import CCT, HandlerCallback

if TYPE_CHECKING:
    from telegram.ext import Application

RT = TypeVar("RT")
UT = TypeVar("UT")


class BaseHandler(ABC, Generic[UT, CCT, RT]):
    """The base class for all update handlers. Create custom handlers by inheriting from it.

    Warning:
        When setting :paramref:`block` to :obj:`False`, you cannot rely on adding custom
        attributes to :class:`telegram.ext.CallbackContext`. See its docs for more info.

    This class is a :class:`~typing.Generic` class and accepts three type variables:

    1. The type of the updates that this handler will handle. Must coincide with the type of the
       first argument of :paramref:`callback`. :meth:`check_update` must only accept
       updates of this type.
    2. The type of the second argument of :paramref:`callback`. Must coincide with the type of the
       parameters :paramref:`handle_update.context` and
       :paramref:`collect_additional_context.context` as well as the second argument of
       :paramref:`callback`. Must be either :class:`~telegram.ext.CallbackContext` or a subclass
       of that class.

       .. tip::
           For this type variable, one should usually provide a :class:`~typing.TypeVar` that is
           also used for the mentioned method arguments. That way, a type checker can check whether
           this handler fits the definition of the :class:`~Application`.
    3. The return type of the :paramref:`callback` function accepted by this handler.

    .. seealso:: :wiki:`Types of Handlers <Types-of-Handlers>`

    .. versionchanged:: 20.0

        * The attribute ``run_async`` is now :paramref:`block`.
        * This class was previously named ``Handler``.

    Args:
        callback (:term:`coroutine function`): The callback function for this handler. Will be
            called when :meth:`check_update` has determined that an update should be processed by
            this handler. Callback signature::

                async def callback(update: Update, context: CallbackContext)

            The return value of the callback is usually ignored except for the special case of
            :class:`telegram.ext.ConversationHandler`.
        block (:obj:`bool`, optional): Determines whether the return value of the callback should
            be awaited before processing the next handler in
            :meth:`telegram.ext.Application.process_update`. Defaults to :obj:`True`.

            .. seealso:: :wiki:`Concurrency`

    Attributes:
        callback (:term:`coroutine function`): The callback function for this handler.
        block (:obj:`bool`): Determines whether the callback will run in a blocking way.

    """

    __slots__ = (
        "block",
        "callback",
    )

    def __init__(
        self: "BaseHandler[UT, CCT, RT]",
        callback: HandlerCallback[UT, CCT, RT],
        block: DVType[bool] = DEFAULT_TRUE,
    ):
        self.callback: HandlerCallback[UT, CCT, RT] = callback
        self.block: DVType[bool] = block

    def __repr__(self) -> str:
        """Give a string representation of the handler in the form ``ClassName[callback=...]``.

        As this class doesn't implement :meth:`object.__str__`, the default implementation
        will be used, which is equivalent to :meth:`__repr__`.

        Returns:
            :obj:`str`
        """
        try:
            callback_name = self.callback.__qualname__
        except AttributeError:
            callback_name = repr(self.callback)
        return build_repr_with_selected_attrs(self, callback=callback_name)

    @abstractmethod
    def check_update(self, update: object) -> bool | object | None:
        """
        This method is called to determine if an update should be handled by
        this handler instance. It should always be overridden.

        Note:
            Custom updates types can be handled by the application. Therefore, an implementation of
            this method should always check the type of :paramref:`update`.

        Args:
            update (:obj:`object` | :class:`telegram.Update`): The update to be tested.

        Returns:
            Either :obj:`None` or :obj:`False` if the update should not be handled. Otherwise an
            object that will be passed to :meth:`handle_update` and
            :meth:`collect_additional_context` when the update gets handled.

        """

    async def handle_update(
        self,
        update: UT,
        application: "Application[Any, CCT, Any, Any, Any, Any]",
        check_result: object,
        context: CCT,
    ) -> RT:
        """
        This method is called if it was determined that an update should indeed
        be handled by this instance. Calls :attr:`callback` along with its respectful
        arguments. To work with the :class:`telegram.ext.ConversationHandler`, this method
        returns the value returned from :attr:`callback`.
        Note that it can be overridden if needed by the subclassing handler.

        Args:
            update (:obj:`str` | :class:`telegram.Update`): The update to be handled.
            application (:class:`telegram.ext.Application`): The calling application.
            check_result (:class:`object`): The result from :meth:`check_update`.
            context (:class:`telegram.ext.CallbackContext`): The context as provided by
                the application.

        """
        self.collect_additional_context(context, update, application, check_result)
        return await self.callback(update, context)

    def collect_additional_context(
        self,
        context: CCT,
        update: UT,
        application: "Application[Any, CCT, Any, Any, Any, Any]",
        check_result: Any,
    ) -> None:
        """Prepares additional arguments for the context. Override if needed.

        Args:
            context (:class:`telegram.ext.CallbackContext`): The context object.
            update (:class:`telegram.Update`): The update to gather chat/user id from.
            application (:class:`telegram.ext.Application`): The calling application.
            check_result: The result (return value) from :meth:`check_update`.

        """
