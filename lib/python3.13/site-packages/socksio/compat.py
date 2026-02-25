"""Backport of @functools.singledispatchmethod to Python <3.7.

Adapted from https://github.com/ikalnytskyi/singledispatchmethod
removing 2.7 specific code.
"""

import functools
import typing

if hasattr(functools, "singledispatchmethod"):  # pragma: nocover
    singledispatchmethod = functools.singledispatchmethod  # type: ignore
else:
    update_wrapper = functools.update_wrapper
    singledispatch = functools.singledispatch

    # The type: ignore below is to avoid mypy erroring due to a
    # "already defined" singledispatchmethod, oddly this does not
    # happen when using `if sys.version_info >= (3, 8)`

    class singledispatchmethod(object):  # type: ignore
        """Single-dispatch generic method descriptor.

        TODO: Figure out how to type this:

        `mypy --strict` returns errors like the following for all decorated methods:
        "Untyped decorator makes function "send" untyped."

        But this is not a normal function-base decorator, it's a class and it
        doesn't have a __call__ method. When decorating the "base" method
        __init__ is called, but of course its return type is None.
        """

        def __init__(self, func: typing.Callable[..., typing.Any]) -> None:
            if not callable(func) and not hasattr(func, "__get__"):
                raise TypeError("{!r} is not callable or a descriptor".format(func))

            self.dispatcher = singledispatch(func)
            self.func = func

        def register(
            self,
            cls: typing.Callable[..., typing.Any],
            method: typing.Optional[typing.Callable[..., typing.Any]] = None,
        ) -> typing.Callable[..., typing.Any]:
            """Register a method on a class for a particular type.

            Note in Python <= 3.6 this methods cannot infer the type from the
            argument's type annotation, users *must* supply it manually on
            decoration, i.e.

            @my_method.register(TypeToDispatch)
            def _(self, arg: TypeToDispatch) -> None:
                ...

            Versus in Python 3.7+:

            @my_method.register
            def _(self, arg: TypeToDispatch) -> None:
                ...

            """
            # mypy wants method to be non-optional, but it is required to be
            # for decoration to work correctly in our case.
            # https://github.com/python/cpython/blob/3.8/Lib/functools.py#L887-L920
            # is not type annotated either.
            return self.dispatcher.register(cls, func=method)  # type: ignore

        def __get__(
            self, obj: typing.Any, cls: typing.Callable[[typing.Any], typing.Any]
        ) -> typing.Callable[..., typing.Any]:
            def _method(*args: typing.Any, **kwargs: typing.Any) -> typing.Any:
                method = self.dispatcher.dispatch(args[0].__class__)  # type: typing.Any
                return method.__get__(obj, cls)(*args, **kwargs)

            # The type: ignore below is due to `_method` being given a strict
            # "Callable[[VarArg(Any), KwArg(Any)], Any]" which causes a
            # 'has no attribute "__isabstractmethod__" error'
            # felt safe enough to ignore
            _method.__isabstractmethod__ = self.__isabstractmethod__  # type: ignore
            _method.register = self.register  # type: ignore
            update_wrapper(_method, self.func)
            return _method

        @property
        def __isabstractmethod__(self) -> typing.Any:
            return getattr(self.func, "__isabstractmethod__", False)
