from __future__ import annotations

import asyncio
import sys
from contextlib import asynccontextmanager
from types import ModuleType, SimpleNamespace

import pytest

import nanobot.agent.tools.mcp as mcp_mod
from nanobot.agent.tools.mcp import (
    MCPPromptWrapper,
    MCPResourceWrapper,
    MCPToolWrapper,
    _normalize_windows_stdio_command,
    _sanitize_name,
    connect_mcp_servers,
)
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.config.schema import MCPServerConfig


class _FakeTextContent:
    def __init__(self, text: str) -> None:
        self.text = text


class _FakeTextResourceContents:
    def __init__(self, text: str) -> None:
        self.text = text


class _FakeBlobResourceContents:
    def __init__(self, blob: bytes) -> None:
        self.blob = blob


@pytest.fixture
def fake_mcp_runtime() -> dict[str, object | None]:
    return {"session": None}


@pytest.fixture(autouse=True)
def _fake_mcp_module(
    monkeypatch: pytest.MonkeyPatch, fake_mcp_runtime: dict[str, object | None]
) -> None:
    mod = ModuleType("mcp")
    mod.types = SimpleNamespace(
        TextContent=_FakeTextContent,
        TextResourceContents=_FakeTextResourceContents,
        BlobResourceContents=_FakeBlobResourceContents,
    )

    class _FakeStdioServerParameters:
        def __init__(self, command: str, args: list[str], env: dict | None = None) -> None:
            self.command = command
            self.args = args
            self.env = env

    class _FakeClientSession:
        def __init__(self, _read: object, _write: object) -> None:
            self._session = fake_mcp_runtime["session"]

        async def __aenter__(self) -> object:
            return self._session

        async def __aexit__(self, exc_type, exc, tb) -> bool:
            return False

    @asynccontextmanager
    async def _fake_stdio_client(_params: object):
        yield object(), object()

    @asynccontextmanager
    async def _fake_sse_client(_url: str, httpx_client_factory=None):
        yield object(), object()

    @asynccontextmanager
    async def _fake_streamable_http_client(_url: str, http_client=None):
        yield object(), object(), object()

    mod.ClientSession = _FakeClientSession
    mod.StdioServerParameters = _FakeStdioServerParameters
    monkeypatch.setitem(sys.modules, "mcp", mod)

    client_mod = ModuleType("mcp.client")
    stdio_mod = ModuleType("mcp.client.stdio")
    stdio_mod.stdio_client = _fake_stdio_client
    sse_mod = ModuleType("mcp.client.sse")
    sse_mod.sse_client = _fake_sse_client
    streamable_http_mod = ModuleType("mcp.client.streamable_http")
    streamable_http_mod.streamable_http_client = _fake_streamable_http_client

    monkeypatch.setitem(sys.modules, "mcp.client", client_mod)
    monkeypatch.setitem(sys.modules, "mcp.client.stdio", stdio_mod)
    monkeypatch.setitem(sys.modules, "mcp.client.sse", sse_mod)
    monkeypatch.setitem(sys.modules, "mcp.client.streamable_http", streamable_http_mod)

    shared_mod = ModuleType("mcp.shared")
    exc_mod = ModuleType("mcp.shared.exceptions")

    class _FakeMcpError(Exception):
        def __init__(self, code: int = -1, message: str = "error"):
            self.error = SimpleNamespace(code=code, message=message)
            super().__init__(message)

    exc_mod.McpError = _FakeMcpError
    monkeypatch.setitem(sys.modules, "mcp.shared", shared_mod)
    monkeypatch.setitem(sys.modules, "mcp.shared.exceptions", exc_mod)


def _make_wrapper(session: object, *, timeout: float = 0.1) -> MCPToolWrapper:
    tool_def = SimpleNamespace(
        name="demo",
        description="demo tool",
        inputSchema={"type": "object", "properties": {}},
    )
    return MCPToolWrapper(session, "test", tool_def, tool_timeout=timeout)


def test_wrapper_preserves_non_nullable_unions() -> None:
    tool_def = SimpleNamespace(
        name="demo",
        description="demo tool",
        inputSchema={
            "type": "object",
            "properties": {
                "value": {
                    "anyOf": [{"type": "string"}, {"type": "integer"}],
                }
            },
        },
    )

    wrapper = MCPToolWrapper(SimpleNamespace(call_tool=None), "test", tool_def)

    assert wrapper.parameters["properties"]["value"]["anyOf"] == [
        {"type": "string"},
        {"type": "integer"},
    ]


def test_wrapper_normalizes_nullable_property_type_union() -> None:
    tool_def = SimpleNamespace(
        name="demo",
        description="demo tool",
        inputSchema={
            "type": "object",
            "properties": {
                "name": {"type": ["string", "null"]},
            },
        },
    )

    wrapper = MCPToolWrapper(SimpleNamespace(call_tool=None), "test", tool_def)

    assert wrapper.parameters["properties"]["name"] == {"type": "string", "nullable": True}


def test_wrapper_normalizes_nullable_property_anyof() -> None:
    tool_def = SimpleNamespace(
        name="demo",
        description="demo tool",
        inputSchema={
            "type": "object",
            "properties": {
                "name": {
                    "anyOf": [{"type": "string"}, {"type": "null"}],
                    "description": "optional name",
                },
            },
        },
    )

    wrapper = MCPToolWrapper(SimpleNamespace(call_tool=None), "test", tool_def)

    assert wrapper.parameters["properties"]["name"] == {
        "type": "string",
        "description": "optional name",
        "nullable": True,
    }


def test_normalize_windows_stdio_command_is_noop_off_windows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(mcp_mod.os, "name", "posix", raising=False)

    command, args, env = _normalize_windows_stdio_command(
        "npx",
        ["-y", "chrome-devtools-mcp@latest"],
        {"FOO": "bar"},
    )

    assert command == "npx"
    assert args == ["-y", "chrome-devtools-mcp@latest"]
    assert env == {"FOO": "bar"}


def test_normalize_windows_stdio_command_wraps_npx_on_windows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(mcp_mod.os, "name", "nt", raising=False)
    monkeypatch.setattr(
        mcp_mod.shutil,
        "which",
        lambda command, path=None: r"C:\Program Files\nodejs\npx.cmd",
    )
    monkeypatch.setenv("COMSPEC", r"C:\Windows\System32\cmd.exe")

    command, args, env = _normalize_windows_stdio_command(
        "npx",
        ["-y", "chrome-devtools-mcp@latest"],
        None,
    )

    assert command == r"C:\Windows\System32\cmd.exe"
    assert args == ["/d", "/c", "npx", "-y", "chrome-devtools-mcp@latest"]
    assert env is None


def test_normalize_windows_stdio_command_wraps_resolved_cmd_launcher(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(mcp_mod.os, "name", "nt", raising=False)

    def _fake_which(command: str, path: str | None = None) -> str:
        assert command == "custom-launcher"
        assert path == r"C:\Tools"
        return r"C:\Tools\custom-launcher.cmd"

    monkeypatch.setattr(mcp_mod.shutil, "which", _fake_which)
    monkeypatch.setenv("COMSPEC", r"C:\Windows\System32\cmd.exe")

    command, args, _env = _normalize_windows_stdio_command(
        "custom-launcher",
        ["serve"],
        {"PATH": r"C:\Tools"},
    )

    assert command == r"C:\Windows\System32\cmd.exe"
    assert args == ["/d", "/c", "custom-launcher", "serve"]


def test_normalize_windows_stdio_command_keeps_real_executables_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(mcp_mod.os, "name", "nt", raising=False)

    command, args, env = _normalize_windows_stdio_command(
        "python.exe",
        ["-m", "http.server"],
        {"FOO": "bar"},
    )

    assert command == "python.exe"
    assert args == ["-m", "http.server"]
    assert env == {"FOO": "bar"}


def test_normalize_windows_stdio_command_skips_existing_shells(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(mcp_mod.os, "name", "nt", raising=False)

    command, args, env = _normalize_windows_stdio_command(
        "cmd.exe",
        ["/c", "echo", "hello"],
        None,
    )

    assert command == "cmd.exe"
    assert args == ["/c", "echo", "hello"]
    assert env is None


@pytest.mark.asyncio
async def test_execute_returns_text_blocks() -> None:
    async def call_tool(_name: str, arguments: dict) -> object:
        assert arguments == {"value": 1}
        return SimpleNamespace(content=[_FakeTextContent("hello"), 42])

    wrapper = _make_wrapper(SimpleNamespace(call_tool=call_tool))

    result = await wrapper.execute(value=1)

    assert result == "hello\n42"


@pytest.mark.asyncio
async def test_execute_returns_timeout_message() -> None:
    async def call_tool(_name: str, arguments: dict) -> object:
        await asyncio.sleep(1)
        return SimpleNamespace(content=[])

    wrapper = _make_wrapper(SimpleNamespace(call_tool=call_tool), timeout=0.01)

    result = await wrapper.execute()

    assert result == "(MCP tool call timed out after 0.01s)"


@pytest.mark.asyncio
async def test_execute_handles_server_cancelled_error() -> None:
    async def call_tool(_name: str, arguments: dict) -> object:
        raise asyncio.CancelledError()

    wrapper = _make_wrapper(SimpleNamespace(call_tool=call_tool))

    result = await wrapper.execute()

    assert result == "(MCP tool call was cancelled)"


@pytest.mark.asyncio
async def test_execute_re_raises_external_cancellation() -> None:
    started = asyncio.Event()

    async def call_tool(_name: str, arguments: dict) -> object:
        started.set()
        await asyncio.sleep(60)
        return SimpleNamespace(content=[])

    wrapper = _make_wrapper(SimpleNamespace(call_tool=call_tool), timeout=10)
    task = asyncio.create_task(wrapper.execute())
    await asyncio.wait_for(started.wait(), timeout=1.0)

    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_execute_handles_generic_exception() -> None:
    async def call_tool(_name: str, arguments: dict) -> object:
        raise RuntimeError("boom")

    wrapper = _make_wrapper(SimpleNamespace(call_tool=call_tool))

    result = await wrapper.execute()

    assert result == "(MCP tool call failed: RuntimeError)"


def _make_tool_def(name: str) -> SimpleNamespace:
    return SimpleNamespace(
        name=name,
        description=f"{name} tool",
        inputSchema={"type": "object", "properties": {}},
    )


def _make_fake_session(tool_names: list[str]) -> SimpleNamespace:
    async def initialize() -> None:
        return None

    async def list_tools() -> SimpleNamespace:
        return SimpleNamespace(tools=[_make_tool_def(name) for name in tool_names])

    return SimpleNamespace(initialize=initialize, list_tools=list_tools)


@pytest.mark.asyncio
async def test_connect_mcp_servers_enabled_tools_supports_raw_names(
    fake_mcp_runtime: dict[str, object | None],
) -> None:
    fake_mcp_runtime["session"] = _make_fake_session(["demo", "other"])
    registry = ToolRegistry()
    stacks = await connect_mcp_servers(
        {"test": MCPServerConfig(command="fake", enabled_tools=["demo"])},
        registry,
    )
    for stack in stacks.values():
        await stack.aclose()

    assert registry.tool_names == ["mcp_test_demo"]


@pytest.mark.asyncio
async def test_connect_mcp_servers_enabled_tools_defaults_to_all(
    fake_mcp_runtime: dict[str, object | None],
) -> None:
    fake_mcp_runtime["session"] = _make_fake_session(["demo", "other"])
    registry = ToolRegistry()
    stacks = await connect_mcp_servers(
        {"test": MCPServerConfig(command="fake")},
        registry,
    )
    for stack in stacks.values():
        await stack.aclose()

    assert registry.tool_names == ["mcp_test_demo", "mcp_test_other"]


@pytest.mark.asyncio
async def test_connect_mcp_servers_enabled_tools_supports_wrapped_names(
    fake_mcp_runtime: dict[str, object | None],
) -> None:
    fake_mcp_runtime["session"] = _make_fake_session(["demo", "other"])
    registry = ToolRegistry()
    stacks = await connect_mcp_servers(
        {"test": MCPServerConfig(command="fake", enabled_tools=["mcp_test_demo"])},
        registry,
    )
    for stack in stacks.values():
        await stack.aclose()

    assert registry.tool_names == ["mcp_test_demo"]


@pytest.mark.asyncio
async def test_connect_mcp_servers_enabled_tools_empty_list_registers_none(
    fake_mcp_runtime: dict[str, object | None],
) -> None:
    fake_mcp_runtime["session"] = _make_fake_session(["demo", "other"])
    registry = ToolRegistry()
    stacks = await connect_mcp_servers(
        {"test": MCPServerConfig(command="fake", enabled_tools=[])},
        registry,
    )
    for stack in stacks.values():
        await stack.aclose()

    assert registry.tool_names == []


@pytest.mark.asyncio
async def test_connect_mcp_servers_enabled_tools_warns_on_unknown_entries(
    fake_mcp_runtime: dict[str, object | None], monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_mcp_runtime["session"] = _make_fake_session(["demo"])
    registry = ToolRegistry()
    warnings: list[str] = []

    def _warning(message: str, *args: object) -> None:
        warnings.append(message.format(*args))

    monkeypatch.setattr("nanobot.agent.tools.mcp.logger.warning", _warning)

    stacks = await connect_mcp_servers(
        {"test": MCPServerConfig(command="fake", enabled_tools=["unknown"])},
        registry,
    )
    for stack in stacks.values():
        await stack.aclose()

    assert registry.tool_names == []
    assert warnings
    assert "enabledTools entries not found: unknown" in warnings[-1]
    assert "Available raw names: demo" in warnings[-1]
    assert "Available wrapped names: mcp_test_demo" in warnings[-1]


@pytest.mark.asyncio
async def test_connect_mcp_servers_logs_stdio_pollution_hint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    messages: list[str] = []

    def _error(message: str, *args: object) -> None:
        messages.append(message.format(*args))

    @asynccontextmanager
    async def _broken_stdio_client(_params: object):
        raise RuntimeError("Parse error: Unexpected token 'INFO' before JSON-RPC headers")
        yield  # pragma: no cover

    monkeypatch.setattr(sys.modules["mcp.client.stdio"], "stdio_client", _broken_stdio_client)
    monkeypatch.setattr("nanobot.agent.tools.mcp.logger.exception", _error)

    registry = ToolRegistry()
    stacks = await connect_mcp_servers({"gh": MCPServerConfig(command="github-mcp")}, registry)

    assert stacks == {}
    assert messages
    assert "stdio protocol pollution" in messages[-1]
    assert "stdout" in messages[-1]
    assert "stderr" in messages[-1]


@pytest.mark.asyncio
async def test_connect_mcp_servers_one_failure_does_not_block_others(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sessions = {"good": _make_fake_session(["demo"])}

    class _SelectiveClientSession:
        def __init__(self, read: object, _write: object) -> None:
            self._session = sessions[read]

        async def __aenter__(self) -> object:
            return self._session

        async def __aexit__(self, exc_type, exc, tb) -> bool:
            return False

    @asynccontextmanager
    async def _selective_stdio_client(params: object):
        if params.command == "bad":
            raise RuntimeError("boom")
        yield params.command, object()

    monkeypatch.setattr(sys.modules["mcp"], "ClientSession", _SelectiveClientSession)
    monkeypatch.setattr(sys.modules["mcp.client.stdio"], "stdio_client", _selective_stdio_client)

    registry = ToolRegistry()
    stacks = await connect_mcp_servers(
        {
            "good": MCPServerConfig(command="good"),
            "bad": MCPServerConfig(command="bad"),
        },
        registry,
    )
    for stack in stacks.values():
        await stack.aclose()

    assert registry.tool_names == ["mcp_good_demo"]
    assert set(stacks) == {"good"}


@pytest.mark.asyncio
async def test_connect_mcp_servers_wraps_windows_stdio_launchers(
    fake_mcp_runtime: dict[str, object | None],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_mcp_runtime["session"] = _make_fake_session(["demo"])
    captured: dict[str, object] = {}

    @asynccontextmanager
    async def _capturing_stdio_client(params: object):
        captured["command"] = params.command
        captured["args"] = params.args
        captured["env"] = params.env
        yield object(), object()

    monkeypatch.setattr(mcp_mod.os, "name", "nt", raising=False)
    monkeypatch.setattr(
        mcp_mod.shutil,
        "which",
        lambda command, path=None: r"C:\Program Files\nodejs\npx.cmd",
    )
    monkeypatch.setenv("COMSPEC", r"C:\Windows\System32\cmd.exe")
    monkeypatch.setattr(sys.modules["mcp.client.stdio"], "stdio_client", _capturing_stdio_client)

    registry = ToolRegistry()
    stacks = await connect_mcp_servers(
        {
            "test": MCPServerConfig(
                command="npx",
                args=["-y", "chrome-devtools-mcp@latest"],
            )
        },
        registry,
    )
    for stack in stacks.values():
        await stack.aclose()

    assert captured["command"] == r"C:\Windows\System32\cmd.exe"
    assert captured["args"] == ["/d", "/c", "npx", "-y", "chrome-devtools-mcp@latest"]
    assert captured["env"] is None


# ---------------------------------------------------------------------------
# MCPResourceWrapper tests
# ---------------------------------------------------------------------------


def _make_resource_def(
    name: str = "myres",
    uri: str = "file:///tmp/data.txt",
    description: str = "A test resource",
) -> SimpleNamespace:
    return SimpleNamespace(name=name, uri=uri, description=description)


def _make_resource_wrapper(session: object, *, timeout: float = 0.1) -> MCPResourceWrapper:
    return MCPResourceWrapper(session, "srv", _make_resource_def(), resource_timeout=timeout)


def test_resource_wrapper_properties() -> None:
    wrapper = MCPResourceWrapper(None, "myserver", _make_resource_def())
    assert wrapper.name == "mcp_myserver_resource_myres"
    assert "[MCP Resource]" in wrapper.description
    assert "A test resource" in wrapper.description
    assert "file:///tmp/data.txt" in wrapper.description
    assert wrapper.parameters == {"type": "object", "properties": {}, "required": []}
    assert wrapper.read_only is True


@pytest.mark.asyncio
async def test_resource_wrapper_execute_returns_text() -> None:
    async def read_resource(uri: str) -> object:
        assert uri == "file:///tmp/data.txt"
        return SimpleNamespace(
            contents=[_FakeTextResourceContents("line1"), _FakeTextResourceContents("line2")]
        )

    wrapper = _make_resource_wrapper(SimpleNamespace(read_resource=read_resource))
    result = await wrapper.execute()
    assert result == "line1\nline2"


@pytest.mark.asyncio
async def test_resource_wrapper_execute_handles_blob() -> None:
    async def read_resource(uri: str) -> object:
        return SimpleNamespace(contents=[_FakeBlobResourceContents(b"\x00\x01\x02")])

    wrapper = _make_resource_wrapper(SimpleNamespace(read_resource=read_resource))
    result = await wrapper.execute()
    assert "[Binary resource: 3 bytes]" in result


@pytest.mark.asyncio
async def test_resource_wrapper_execute_handles_timeout() -> None:
    async def read_resource(uri: str) -> object:
        await asyncio.sleep(1)
        return SimpleNamespace(contents=[])

    wrapper = _make_resource_wrapper(SimpleNamespace(read_resource=read_resource), timeout=0.01)
    result = await wrapper.execute()
    assert result == "(MCP resource read timed out after 0.01s)"


@pytest.mark.asyncio
async def test_resource_wrapper_execute_handles_error() -> None:
    async def read_resource(uri: str) -> object:
        raise RuntimeError("boom")

    wrapper = _make_resource_wrapper(SimpleNamespace(read_resource=read_resource))
    result = await wrapper.execute()
    assert result == "(MCP resource read failed: RuntimeError)"


# ---------------------------------------------------------------------------
# MCPPromptWrapper tests
# ---------------------------------------------------------------------------


def _make_prompt_def(
    name: str = "myprompt",
    description: str = "A test prompt",
    arguments: list | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(name=name, description=description, arguments=arguments)


def _make_prompt_wrapper(session: object, *, timeout: float = 0.1) -> MCPPromptWrapper:
    return MCPPromptWrapper(session, "srv", _make_prompt_def(), prompt_timeout=timeout)


def test_prompt_wrapper_properties() -> None:
    arg1 = SimpleNamespace(name="topic", required=True)
    arg2 = SimpleNamespace(name="style", required=False)
    wrapper = MCPPromptWrapper(None, "myserver", _make_prompt_def(arguments=[arg1, arg2]))
    assert wrapper.name == "mcp_myserver_prompt_myprompt"
    assert "[MCP Prompt]" in wrapper.description
    assert "A test prompt" in wrapper.description
    assert "workflow guide" in wrapper.description
    assert wrapper.parameters["properties"]["topic"] == {"type": "string"}
    assert wrapper.parameters["properties"]["style"] == {"type": "string"}
    assert wrapper.parameters["required"] == ["topic"]
    assert wrapper.read_only is True


def test_prompt_wrapper_no_arguments() -> None:
    wrapper = MCPPromptWrapper(None, "myserver", _make_prompt_def())
    assert wrapper.parameters == {"type": "object", "properties": {}, "required": []}


def test_prompt_wrapper_preserves_argument_descriptions() -> None:
    arg = SimpleNamespace(name="topic", required=True, description="The subject to discuss")
    wrapper = MCPPromptWrapper(None, "srv", _make_prompt_def(arguments=[arg]))
    assert wrapper.parameters["properties"]["topic"] == {
        "type": "string",
        "description": "The subject to discuss",
    }


@pytest.mark.asyncio
async def test_prompt_wrapper_execute_returns_text() -> None:
    async def get_prompt(name: str, arguments: dict | None = None) -> object:
        assert name == "myprompt"
        msg1 = SimpleNamespace(
            role="user",
            content=[_FakeTextContent("You are an expert on {{topic}}.")],
        )
        msg2 = SimpleNamespace(
            role="assistant",
            content=[_FakeTextContent("Understood. Ask me anything.")],
        )
        return SimpleNamespace(messages=[msg1, msg2])

    wrapper = _make_prompt_wrapper(SimpleNamespace(get_prompt=get_prompt))
    result = await wrapper.execute(topic="AI")
    assert "You are an expert on {{topic}}." in result
    assert "Understood. Ask me anything." in result


@pytest.mark.asyncio
async def test_prompt_wrapper_execute_handles_timeout() -> None:
    async def get_prompt(name: str, arguments: dict | None = None) -> object:
        await asyncio.sleep(1)
        return SimpleNamespace(messages=[])

    wrapper = _make_prompt_wrapper(SimpleNamespace(get_prompt=get_prompt), timeout=0.01)
    result = await wrapper.execute()
    assert result == "(MCP prompt call timed out after 0.01s)"


@pytest.mark.asyncio
async def test_prompt_wrapper_execute_handles_mcp_error() -> None:
    from mcp.shared.exceptions import McpError

    async def get_prompt(name: str, arguments: dict | None = None) -> object:
        raise McpError(code=42, message="invalid argument")

    wrapper = _make_prompt_wrapper(SimpleNamespace(get_prompt=get_prompt))
    result = await wrapper.execute()
    assert "invalid argument" in result
    assert "code 42" in result


@pytest.mark.asyncio
async def test_prompt_wrapper_execute_handles_error() -> None:
    async def get_prompt(name: str, arguments: dict | None = None) -> object:
        raise RuntimeError("boom")

    wrapper = _make_prompt_wrapper(SimpleNamespace(get_prompt=get_prompt))
    result = await wrapper.execute()
    assert result == "(MCP prompt call failed: RuntimeError)"


# ---------------------------------------------------------------------------
# connect_mcp_servers: resources + prompts integration
# ---------------------------------------------------------------------------


def _make_fake_session_with_capabilities(
    tool_names: list[str],
    resource_names: list[str] | None = None,
    prompt_names: list[str] | None = None,
) -> SimpleNamespace:
    async def initialize() -> None:
        return None

    async def list_tools() -> SimpleNamespace:
        return SimpleNamespace(tools=[_make_tool_def(name) for name in tool_names])

    async def list_resources() -> SimpleNamespace:
        resources = []
        for rname in resource_names or []:
            resources.append(
                SimpleNamespace(
                    name=rname,
                    uri=f"file:///{rname}",
                    description=f"{rname} resource",
                )
            )
        return SimpleNamespace(resources=resources)

    async def list_prompts() -> SimpleNamespace:
        prompts = []
        for pname in prompt_names or []:
            prompts.append(
                SimpleNamespace(
                    name=pname,
                    description=f"{pname} prompt",
                    arguments=None,
                )
            )
        return SimpleNamespace(prompts=prompts)

    return SimpleNamespace(
        initialize=initialize,
        list_tools=list_tools,
        list_resources=list_resources,
        list_prompts=list_prompts,
    )


@pytest.mark.asyncio
async def test_connect_registers_resources_and_prompts(
    fake_mcp_runtime: dict[str, object | None],
) -> None:
    fake_mcp_runtime["session"] = _make_fake_session_with_capabilities(
        tool_names=["tool_a"],
        resource_names=["res_b"],
        prompt_names=["prompt_c"],
    )
    registry = ToolRegistry()
    stacks = await connect_mcp_servers(
        {"test": MCPServerConfig(command="fake")},
        registry,
    )
    for stack in stacks.values():
        await stack.aclose()

    assert "mcp_test_tool_a" in registry.tool_names
    assert "mcp_test_resource_res_b" in registry.tool_names
    assert "mcp_test_prompt_prompt_c" in registry.tool_names


# ---------------------------------------------------------------------------
# _sanitize_name tests
# ---------------------------------------------------------------------------


def test_sanitize_name_replaces_spaces() -> None:
    assert _sanitize_name("PostgreSQL System Information") == "PostgreSQL_System_Information"


def test_sanitize_name_replaces_special_characters() -> None:
    assert _sanitize_name("foo.bar@baz!") == "foo_bar_baz_"


def test_sanitize_name_collapses_consecutive_underscores() -> None:
    assert _sanitize_name("a   b") == "a_b"


def test_sanitize_name_preserves_valid_characters() -> None:
    assert _sanitize_name("my-tool_v2") == "my-tool_v2"


def test_sanitize_name_noop_for_already_clean_names() -> None:
    assert _sanitize_name("mcp_server_tool") == "mcp_server_tool"


# ---------------------------------------------------------------------------
# Wrapper sanitization tests
# ---------------------------------------------------------------------------


def test_tool_wrapper_sanitizes_name() -> None:
    tool_def = SimpleNamespace(
        name="My Tool",
        description="tool with spaces",
        inputSchema={"type": "object", "properties": {}},
    )
    wrapper = MCPToolWrapper(SimpleNamespace(call_tool=None), "srv", tool_def)
    assert wrapper.name == "mcp_srv_My_Tool"


def test_resource_wrapper_sanitizes_name() -> None:
    resource_def = SimpleNamespace(
        name="PostgreSQL System Information",
        uri="file:///pg/info",
        description="PG info",
    )
    wrapper = MCPResourceWrapper(None, "srv", resource_def)
    assert wrapper.name == "mcp_srv_resource_PostgreSQL_System_Information"


def test_prompt_wrapper_sanitizes_name() -> None:
    prompt_def = SimpleNamespace(
        name="design-schema",
        description="Design schema",
        arguments=None,
    )
    # Hyphens are allowed, so this should pass through unchanged
    wrapper = MCPPromptWrapper(None, "my server", prompt_def)
    assert wrapper.name == "mcp_my_server_prompt_design-schema"


def test_tool_wrapper_preserves_original_name_for_mcp_call() -> None:
    tool_def = SimpleNamespace(
        name="My Tool",
        description="tool with spaces",
        inputSchema={"type": "object", "properties": {}},
    )
    wrapper = MCPToolWrapper(SimpleNamespace(call_tool=None), "srv", tool_def)
    # The sanitized API-facing name differs from the original MCP name
    assert wrapper.name == "mcp_srv_My_Tool"
    assert wrapper._original_name == "My Tool"


@pytest.mark.asyncio
async def test_connect_mcp_servers_sanitizes_resource_names(
    fake_mcp_runtime: dict[str, object | None],
) -> None:
    fake_mcp_runtime["session"] = _make_fake_session_with_capabilities(
        tool_names=[],
        resource_names=["PostgreSQL System Information"],
        prompt_names=[],
    )
    registry = ToolRegistry()
    stacks = await connect_mcp_servers(
        {"test": MCPServerConfig(command="fake")},
        registry,
    )
    for stack in stacks.values():
        await stack.aclose()

    assert "mcp_test_resource_PostgreSQL_System_Information" in registry.tool_names


@pytest.mark.asyncio
async def test_connect_mcp_servers_enabled_tools_matches_sanitized_name(
    fake_mcp_runtime: dict[str, object | None],
) -> None:
    fake_mcp_runtime["session"] = _make_fake_session_with_capabilities(
        tool_names=["My Tool", "other"],
    )
    registry = ToolRegistry()
    stacks = await connect_mcp_servers(
        {"test": MCPServerConfig(command="fake", enabled_tools=["mcp_test_My_Tool"])},
        registry,
    )
    for stack in stacks.values():
        await stack.aclose()

    assert registry.tool_names == ["mcp_test_My_Tool"]
