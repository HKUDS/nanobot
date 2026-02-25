import inspect
from collections.abc import Callable
from typing import Any, TypeVar, get_type_hints

T = TypeVar("T")
R = TypeVar("R")


def create_call_wrapper(func: Callable[..., R], request_type: type[T]) -> Callable[[T], R]:
    """
    Create a wrapper function that knows how to call func with the request object.

    Returns a wrapper function that takes the request and calls func appropriately.

    The wrapper handles three calling patterns:
    1. Positional-only parameter typed as request_type (no default): func(req)
    2. Positional/keyword parameter typed as request_type (no default): func(**{param_name: req})
    3. No request parameter or parameter with default: func()
    """
    try:
        sig = inspect.signature(func)
        type_hints = get_type_hints(func)
    except (ValueError, TypeError, NameError):  # pragma: no cover
        return lambda _: func()

    # Check for positional-only parameter typed as request_type
    for param_name, param in sig.parameters.items():
        if param.kind == inspect.Parameter.POSITIONAL_ONLY:
            param_type = type_hints.get(param_name)
            if param_type == request_type:  # pragma: no branch
                # Check if it has a default - if so, treat as old style
                if param.default is not inspect.Parameter.empty:  # pragma: no cover
                    return lambda _: func()
                # Found positional-only parameter with correct type and no default
                return lambda req: func(req)

    # Check for any positional/keyword parameter typed as request_type
    for param_name, param in sig.parameters.items():
        if param.kind in (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY):  # pragma: no branch
            param_type = type_hints.get(param_name)
            if param_type == request_type:
                # Check if it has a default - if so, treat as old style
                if param.default is not inspect.Parameter.empty:  # pragma: no cover
                    return lambda _: func()

                # Found keyword parameter with correct type and no default
                # Need to capture param_name in closure properly
                def make_keyword_wrapper(name: str) -> Callable[[Any], Any]:
                    return lambda req: func(**{name: req})

                return make_keyword_wrapper(param_name)

    # No request parameter found - use old style
    return lambda _: func()
