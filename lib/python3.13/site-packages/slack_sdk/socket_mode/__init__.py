"""Socket Mode is a method of connecting your app to Slack’s APIs using WebSockets instead of HTTP.
You can use slack_sdk.socket_mode.SocketModeClient for managing Socket Mode connections
and performing interactions with Slack.

https://docs.slack.dev/apis/events-api/using-socket-mode/
"""

from .builtin import SocketModeClient

__all__ = [
    "SocketModeClient",
]
