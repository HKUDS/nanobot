from typing import Optional

from slack_sdk.socket_mode.request import SocketModeRequest


class WebSocketMessageListener:
    def __call__(
        client: "BaseSocketModeClient",  # type: ignore[name-defined] # noqa: F821
        message: dict,
        raw_message: Optional[str] = None,
    ):  # noqa: F821
        raise NotImplementedError()


class SocketModeRequestListener:
    def __call__(client: "BaseSocketModeClient", request: SocketModeRequest):  # type: ignore[name-defined]  # noqa: F821, F821, E501
        raise NotImplementedError()
