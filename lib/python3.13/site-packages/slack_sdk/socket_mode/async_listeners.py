from typing import Optional, Callable

from slack_sdk.socket_mode.request import SocketModeRequest


class AsyncWebSocketMessageListener(Callable):  # type: ignore[misc]
    async def __call__(
        client: "AsyncBaseSocketModeClient",  # type: ignore[name-defined] # noqa: F821
        message: dict,
        raw_message: Optional[str] = None,
    ):  # noqa: F821
        raise NotImplementedError()


class AsyncSocketModeRequestListener(Callable):  # type: ignore[misc]
    async def __call__(
        client: "AsyncBaseSocketModeClient",  # type: ignore[name-defined] # noqa: F821
        request: SocketModeRequest,
    ):  # noqa: F821
        raise NotImplementedError()
