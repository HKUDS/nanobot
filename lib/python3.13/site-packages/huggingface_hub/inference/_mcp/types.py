from typing import Literal, TypedDict, Union

from typing_extensions import NotRequired


class InputConfig(TypedDict, total=False):
    id: str
    description: str
    type: str
    password: bool


class StdioServerConfig(TypedDict):
    type: Literal["stdio"]
    command: str
    args: list[str]
    env: dict[str, str]
    cwd: str
    allowed_tools: NotRequired[list[str]]


class HTTPServerConfig(TypedDict):
    type: Literal["http"]
    url: str
    headers: dict[str, str]
    allowed_tools: NotRequired[list[str]]


class SSEServerConfig(TypedDict):
    type: Literal["sse"]
    url: str
    headers: dict[str, str]
    allowed_tools: NotRequired[list[str]]


ServerConfig = Union[StdioServerConfig, HTTPServerConfig, SSEServerConfig]


# AgentConfig root object
class AgentConfig(TypedDict):
    model: str
    provider: str
    apiKey: NotRequired[str]
    inputs: list[InputConfig]
    servers: list[ServerConfig]
