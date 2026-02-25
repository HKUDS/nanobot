"""
* The SDK website: https://docs.slack.dev/tools/python-slack-sdk
* PyPI package: https://pypi.org/project/slack-sdk/

Here is the list of key modules in this SDK:

#### Web API Client

* Web API client: `slack_sdk.web.client`
* asyncio-based Web API client: `slack_sdk.web.async_client`

#### Webhook / response_url Client

* Webhook client: `slack_sdk.webhook.client`
* asyncio-based Webhook client: `slack_sdk.webhook.async_client`

#### Socket Mode Client

* The built-in Socket Mode client: `slack_sdk.socket_mode.builtin.client`
* [aiohttp](https://pypi.org/project/aiohttp/) based client: `slack_sdk.socket_mode.aiohttp`
* [websocket_client](https://pypi.org/project/websocket-client/) based client: `slack_sdk.socket_mode.websocket_client`
* [websockets](https://pypi.org/project/websockets/) based client: `slack_sdk.socket_mode.websockets`

#### OAuth

* `slack_sdk.oauth.installation_store.installation_store`
* `slack_sdk.oauth.state_store`

#### Audit Logs API Client

* `slack_sdk.audit_logs.v1.client`
* `slack_sdk.audit_logs.v1.async_client`

#### SCIM API Client

* `slack_sdk.scim.v1.client`
* `slack_sdk.scim.v1.async_client`

"""

import logging
from logging import NullHandler

# from .rtm import RTMClient
from .web import WebClient
from .webhook import WebhookClient

__all__ = [
    "WebClient",
    "WebhookClient",
]

# Set default logging handler to avoid "No handler found" warnings.
logging.getLogger(__name__).addHandler(NullHandler())
