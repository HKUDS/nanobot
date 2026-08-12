# 渠道包指南

使用本指南将一个自包含的渠道包添加到 nanobot 仓库。当渠道包位于 `nanobot/channels/<channel>/` 时，该渠道即为 nanobot 的一部分；不存在独立的外部渠道插件路径。

> **破坏性变更：** nanobot 不再发现 `nanobot.channels` Python 入口点组。请将入口点实现迁移到 `nanobot/channels/<channel>/`，其中包含由包拥有的清单、运行时、测试以及可选的 WebUI 贡献。

## 工作原理

当 `nanobot gateway` 启动时，nanobot 会扫描 `nanobot/channels/` 下的包，并从 `manifest.py` 加载每个无依赖的 `ChannelPlugin` 描述符。

如果匹配的配置节包含 `"enabled": true`，则会实例化并启动该渠道。

## 所有权与事实来源

| 关注点 | 所有者与事实来源 |
|---------|---------------------------|
| 运行时行为与平台 SDK 使用 | `runtime.py` 和包本地辅助模块 |
| Python 包依赖要求 | `manifest.py` 中的 `ChannelPlugin.dependencies` |
| 可写设置字段、类型、默认值、要求、密钥处理和验证 | `manifest.py` 中的 `ChannelPlugin.setup` |
| 持久化配置扩展、实例更新和运行时命名 | `ChannelPlugin.management`，由无依赖模块支持 |
| 交互式设置连接及其短期状态 | `ChannelPlugin.connector`，由包本地 `connect.py` 支持 |
| 可复用的本地登录状态检测 | `ChannelPlugin.management.local_state_present`，由包本地代码支持 |
| 发现元数据和延迟运行时目标 | `manifest.py` 中的 `PLUGIN` |
| WebUI 结构、组件、URL、字段键、操作和预设值 | `webui/index.ts` 或 `webui/index.tsx` |
| 渠道专属的面向用户文案 | `webui/locales/<locale>.json` |
| 每个渠道共享的通用设置外壳文案 | `webui/src/i18n/locales/<locale>/common.json` |

为每个关注点保留一个事实来源。特别是，后端设置契约决定哪些内容可以写入，TypeScript 贡献决定这些字段如何呈现，而区域设置 JSON 提供向用户展示的渠道专属文字。

## 快速开始

我们将构建一个最小化 webhook 渠道，它通过 HTTP POST 接收消息并发送回复。

### 项目结构

```text
nanobot/channels/webhook/
├── __init__.py          # lightweight package marker; do not import the runtime
├── manifest.py          # dependency-free ChannelPlugin descriptor
├── runtime.py           # channel implementation and optional SDK imports
├── tests/               # package-local tests
└── webui/               # optional settings UI and translations
```

### 1. 创建你的渠道

```python
# nanobot/channels/webhook/__init__.py
"""Webhook channel package."""
```

```python
# nanobot/channels/webhook/manifest.py
from nanobot.channels.contracts import ChannelFieldSpec, ChannelSetupSpec
from nanobot.channels.plugin import ChannelPlugin


PLUGIN = ChannelPlugin(
    name="webhook",
    display_name="Webhook",
    runtime=f"{__package__}.runtime:WebhookChannel",
    dependencies=("aiohttp>=3.9.0,<4.0.0",),
    setup=ChannelSetupSpec(
        fields={
            "port": ChannelFieldSpec(kind="int", default=9000),
            "allowFrom": ChannelFieldSpec(kind="list"),
        },
    ),
)
```

```python
# nanobot/channels/webhook/runtime.py
import asyncio
from typing import Any

from aiohttp import web
from loguru import logger
from pydantic import Field

from nanobot.channels.base import BaseChannel
from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.config.schema import Base


class WebhookConfig(Base):
    """Webhook channel configuration."""
    enabled: bool = False
    port: int = 9000
    allow_from: list[str] = Field(default_factory=list)


class WebhookChannel(BaseChannel):
    name = "webhook"
    display_name = "Webhook"

    def __init__(self, config: Any, bus: MessageBus):
        if isinstance(config, dict):
            config = WebhookConfig(**config)
        super().__init__(config, bus)

    @classmethod
    def default_config(cls) -> dict[str, Any]:
        return WebhookConfig().model_dump(by_alias=True)

    async def start(self) -> None:
        """Start an HTTP server that listens for incoming messages.

        IMPORTANT: start() must block forever (or until stop() is called).
        If it returns, the channel is considered dead.
        """
        self._running = True
        port = self.config.port

        app = web.Application()
        app.router.add_post("/message", self._on_request)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "0.0.0.0", port)
        await site.start()
        logger.info("Webhook listening on :{}", port)

        # Block until stopped
        while self._running:
            await asyncio.sleep(1)

        await runner.cleanup()

    async def stop(self) -> None:
        self._running = False

    async def send(self, msg: OutboundMessage) -> None:
        """Deliver an outbound message.

        msg.content  — markdown text (convert to platform format as needed)
        msg.media    — list of local file paths to attach
        msg.chat_id  — the recipient (same chat_id you passed to _handle_message)
        msg.metadata — channel routing context such as message/thread ids
        msg.event    — typed runtime event for progress/status messages
        """
        logger.info("[webhook] -> {}: {}", msg.chat_id, msg.content[:80])
        # In a real plugin: POST to a callback URL, send via SDK, etc.

    async def _on_request(self, request: web.Request) -> web.Response:
        """Handle an incoming HTTP POST."""
        body = await request.json()
        sender = body.get("sender", "unknown")
        chat_id = body.get("chat_id", sender)
        text = body.get("text", "")
        media = body.get("media", [])       # list of URLs

        # This is the key call: validates allowFrom, then puts the
        # message onto the bus for the agent to process.
        await self._handle_message(
            sender_id=sender,
            chat_id=chat_id,
            content=text,
            media=media,
        )

        return web.json_response({"ok": True})
```

包目录、`PLUGIN.name`、运行时类名和配置节都必须使用 `webhook`。渠道名称使用可移植的 ASCII 包标识符：以字母开头，并且只包含字母、数字或下划线。

直接在 `ChannelPlugin.dependencies` 中声明运行时依赖。不要将渠道依赖添加到根 `pyproject.toml`：包清单是 CLI、WebUI 和网关启动使用的事实来源。保持清单及其导入的所有内容不依赖可选 SDK 本身。

### 2. 配置

```bash
nanobot plugins list      # verify the channel package appears as "webhook"
nanobot onboard           # add default config for detected channels
```

编辑 `~/.nanobot/config.json`：

```json
{
  "channels": {
    "webhook": {
      "enabled": true,
      "port": 9000,
      "allowFrom": ["*"]
    }
  }
}
```

nanobot 在发现期间始终加载无依赖描述符。当 WebUI 网关启动时，会在导入已启用渠道的运行时之前安装缺失依赖。通过 CLI 或 WebUI 启用渠道时，也会安装这些依赖。状态、配置和禁用操作不需要运行时。单实例和多实例渠道使用相同的激活规则。

### 3. 运行与测试

```bash
nanobot gateway
```

在另一个终端中：

```bash
curl -X POST http://localhost:9000/message \
  -H "Content-Type: application/json" \
  -d '{"sender": "user1", "chat_id": "user1", "text": "Hello!"}'
```

代理会接收并处理该消息。回复会进入你的 `send()` 方法。

## 渠道包要求

每个渠道都是位于 `nanobot/channels/<channel>/` 的自包含包；渠道专属运行时代码、设置元数据、测试、WebUI 结构、组件和翻译均保留在该目录下。

### 包布局

```text
nanobot/channels/<channel>/
├── __init__.py                 # package marker only; no runtime or SDK imports
├── manifest.py                 # dependency-free ChannelPlugin and ChannelSetupSpec
├── config.py                   # optional dependency-free config model and defaults
├── connect.py                  # optional interactive setup connector
├── instances.py                # optional dependency-free multi-instance management adapter
├── state.py                    # optional persisted login-state detection
├── validation.py               # optional package-owned setup checks
├── runtime.py                  # BaseChannel implementation and platform SDK imports
├── tests/                      # channel-specific Python tests
└── webui/                      # optional, compiled into the shared WebUI
    ├── index.ts or index.tsx   # structure and optional React components
    └── locales/
        ├── en.json             # canonical locale shape
        └── <locale>.json       # one file for every supported WebUI locale
```

不要直接在 `nanobot/channels/` 下添加运行时模块、创建并行清单树，或添加中央的按渠道分类 UI 目录。如果移动现有渠道文件，请使用 `git mv`，以便历史记录保持可追溯。

### 清单与运行时边界

`manifest.py` 导出一个类型化的 `ChannelPlugin`，其 `runtime` 目标是绝对导入目标，例如 `nanobot.channels.telegram.runtime:TelegramChannel`；使用 `f"{__package__}.runtime:TelegramChannel"` 可保持其由包拥有，而无需重复包路径。发现机制会在知道可选平台依赖是否已安装之前导入清单，因此 `manifest.py` 不得导入 `runtime.py` 或任何平台 SDK。请从 `runtime.py` 显式导入运行时符号；`__init__.py` 应保持为惰性的包标记。

清单拥有渠道名称、显示名称、设置契约、管理适配器、可选连接器目标、依赖要求、能力、默认激活状态和可选 WebUI 入口路径。仅管理适配器决定渠道是单实例还是多实例。

交互式浏览器设置使用一个小型连接器契约。设置 `connector=f"{__package__}.connect:MyConnectStore"`；仅在调用 `/api/settings/channels/<name>/connect/{start,poll,cancel}` 时加载该目标。存储暴露一个异步 `handle(action, query)` 方法，并将平台专属解析、会话和错误保留在渠道包内。共享设置路由器仅负责身份验证、分发和应用成功的连接。

对于声明式字段和依赖要求定义，请使用 [`nanobot/channels/_manifest.py`](../nanobot/channels/_manifest.py) 中的小型构造函数。将 [`nanobot/channels/dingtalk/manifest.py`](../nanobot/channels/dingtalk/manifest.py) 用作紧凑的单实例示例，将 [`nanobot/channels/feishu/`](../nanobot/channels/feishu/) 用作多实例示例。

### 包拥有的 WebUI

在渠道清单中设置 `webui="webui/index.ts"` 或 `webui="webui/index.tsx"`。候选模块从渠道包中打包，但设置 UI 仅激活由后端功能载荷返回的确切路径。

入口模块导出一个默认的 `ChannelUiContribution`。渠道身份来自包目录，因此不要在 TypeScript 中重复 `channel` 字段。此模块中仅保留结构和可执行 UI 数据：呈现元数据、图标或 logo URL、文档 URL、配置字段键、操作载荷、预设值、别名，以及可选的 `Panel` 或 `ConnectFlow` 组件。

不要将静态描述、设置步骤、标签、占位符、帮助文本、操作标签或预设标签放在 TSX 中。这些字符串属于渠道的区域设置 JSON。TSX 仍适合用于动态渲染、插值、条件和丰富的组件组合。

### 渠道拥有的 i18n

为 [`webui/src/i18n/config.ts`](../webui/src/i18n/config.ts) 中声明的每个区域设置代码创建 `webui/locales/<locale>.json`。将 `en.json` 视为规范形状；每种其他区域设置都必须包含相同的消息键和相同的插值变量。当产品名称应保持不变时，可以省略 `displayName`。

```json
{
  "description": "Use nanobot from Example chats.",
  "requirements": "Example app credentials and gateway",
  "setup": {
    "docsLabel": "Open Example setup",
    "officialLabel": "Open Example console",
    "summary": "Example needs app credentials.",
    "tryIt": "Send a test message.",
    "steps": [
      "Create an Example app.",
      "Add the credentials.",
      "Save, enable, and test the channel."
    ],
    "fields": {
      "clientId": {
        "label": "Client ID",
        "placeholder": "Example client ID",
        "help": "Copy it from the Example console."
      }
    },
    "actions": {
      "copyManifest": "Copy manifest"
    },
    "presets": {
      "default": "Default"
    }
  },
  "custom": {
    "connected": "{{name}} is connected."
  }
}
```

字段消息以 `channels.<channel>.` 之后的配置路径作为键，并将剩余标点转换为下划线。例如，`channels.signal.dm.allowFrom` 映射到 `setup.fields.dm_allowFrom`。操作和预设消息使用 TypeScript 贡献中声明的 ID。

自定义渠道组件应通过 `channelTranslator(t, "<channel>")` 读取动态文案；将英文回退文本保留在调用旁边，以便不完整的翻译仍能呈现有用的文字。别名复用所属渠道的区域设置命名空间，而不是复制翻译。

依赖方向是有意设计的：

- [`webui/src/i18n/index.ts`](../webui/src/i18n/index.ts) 导入纯 JSON [`channel-plugins/locale-registry.ts`](../webui/src/channel-plugins/locale-registry.ts)。
- 区域设置注册表仅发现 `nanobot/channels/*/webui/locales/*.json`，且不得导入 UI 注册表、React 或 TSX。
- 设置组件可以同时使用 UI 注册表和区域设置注册表。
- 渠道 UI 代码可以使用共享类型和通用设置组件，但核心设置代码不得为单个渠道添加 `if (feature.name === "...")` 分支。

这种分离可防止 i18n 初始化急切加载每个渠道 React 组件，并将渠道专属所有权保留在渠道包之下。

### 测试与完成定义

将渠道专属 Python 测试放在 `nanobot/channels/<channel>/tests/` 中。仅将共享注册表、管理器、基类和跨渠道契约测试保留在 `tests/channels/` 中。发布构建会排除包本地测试，而仓库测试配置会发现两棵目录树。

对于聚焦的渠道变更，运行最小的相关测试集：

```bash
uv run pytest nanobot/channels/<channel>/tests -q

cd webui
bun run test -- src/tests/channel-locale-registry.test.ts src/tests/channel-ui-registry.test.ts src/tests/channel-identity.test.ts
bun run lint
bun run build
```

在认为变更完成之前，请验证以下所有内容：

- 无需导入运行时或可选平台 SDK 即可发现清单。
- `ChannelSetupSpec` 包含每个可写字段，并拒绝未知字段。
- TypeScript 字段、操作和预设 ID 都具有匹配的英文区域设置消息。
- 每个受支持区域设置均匹配英文键形状和插值变量。
- 通用设置文案保留在核心 `common.json` 中；渠道专属文案保留在渠道包内。
- 面向用户的 WebUI 变更可通过由真实网关提供服务的已构建前端正常工作，包括语言切换和刷新持久化。
- Markdown 正文段落和单个列表项保持在同一源代码行；让渲染器处理视觉换行。

## BaseChannel API

### 必需（抽象）

| 方法 | 描述 |
|--------|-------------|
| `async start()` | **必须永久阻塞。** 连接到平台、监听消息，并对每条消息调用 `_handle_message()`。如果该方法返回，则渠道已失效。 |
| `async stop()` | 设置 `self._running = False` 并清理资源。在网关关闭时调用。 |
| `async send(msg: OutboundMessage)` | 向平台传递出站消息。当传输不接受消息时抛出异常。 |

#### 出站传递契约

`send()` 正常返回表示可见载荷已被平台传输/API 接受，或渠道有意没有内容需要传递，例如空的进度事件。当客户端断开连接、仍在启动中或平台拒绝请求时，不要仅记录日志然后返回。应抛出异常，以便 `ChannelManager` 应用共享重试策略。

`send()` 可以在 `is_running` 变为 true 后立即运行。如果渠道在其传输准备就绪之前设置了 `_running`，则必须持续抛出异常，直到可以安全地尝试传递。小范围的平台专属重试是可以的，但最终失败仍必须传递给管理器。
### 交互式登录

如果你的渠道需要交互式身份验证（例如扫描二维码），请重写 `login(force=False)`：

```python
async def login(self, force: bool = False) -> bool:
    """
    Perform channel-specific interactive login.

    Args:
        force: If True, ignore existing credentials and re-authenticate.

    Returns True if already authenticated or login succeeds.
    """
    # For QR-code-based login:
    # 1. If force, clear saved credentials
    # 2. Check if already authenticated (load from disk/state)
    # 3. If not, show QR code and poll for confirmation
    # 4. Save token on success
```

不需要交互式登录的渠道（例如使用机器人令牌的 Telegram、使用机器人令牌的 Discord）会继承默认的 `login()`，该方法仅返回 `True`。

用户通过以下方式触发交互式登录：
```bash
nanobot channels login <channel_name>
nanobot channels login <channel_name> --force  # re-authenticate
```

### Base 提供的功能

| 方法 / 属性 | 说明 |
|-------------------|-------------|
| `_handle_message(sender_id, chat_id, content, media?, metadata?, session_key?)` | **收到消息时调用此方法。** 检查 `is_allowed()`，然后发布到总线。如果 `supports_streaming` 为 true，会自动设置 `_wants_stream`。 |
| `is_allowed(sender_id)` | 根据 `config.allow_from` 检查；`"*"` 允许所有人，`[]` 拒绝所有人。 |
| `default_config()` (classmethod) | 为直接构造类的调用方返回运行时本地默认值。发现和引导流程改为使用描述符。 |
| `refresh_feature_metadata(config_path, instance_id)` (classmethod) | 可在显式设置操作后选择性刷新已保存的显示元数据。只读功能 GET 永远不会调用它。 |
| `transcribe_audio(file_path)` | 通过共享的顶层 `transcription` 配置转录音频（如果已配置）。 |
| `supports_streaming` (property) | 当配置包含 `"streaming": true` **且**子类重写 `send_delta()` 时为 `True`。 |
| `is_running` | 返回 `self._running`。 |
| `login(force=False)` | 执行交互式登录（例如扫描二维码）。如果已完成身份验证或登录成功，则返回 `True`。在支持交互式登录的子类中重写。 |
| `send_reasoning_delta(chat_id, delta, metadata?, *, stream_id?)` | 用于流式模型推理/思考内容的可选钩子。默认为空操作。 |
| `send_reasoning_end(chat_id, metadata?, *, stream_id?)` | 标记推理块结束的可选钩子。默认为空操作。 |
| `send_reasoning(msg)` | 可选的一次性推理回退机制。默认会转换为 `send_reasoning_delta()` + `send_reasoning_end()`。 |

### 可选管理契约

持久化状态管理属于 `ChannelPlugin.management`，而非 `BaseChannel`。适配器及其导入的任何内容都不得依赖可选平台 SDK，这样即使无法导入运行时，状态、设置和禁用操作仍然可用。运行时类负责网络生命周期、消息投递、交互式登录、启用时可用性检查，以及元数据刷新等显式的仅运行时操作。

```python
from nanobot.channels.contracts import ChannelFieldSpec, ChannelSetupSpec, SetupRequirement
from nanobot.channels.plugin import ChannelPlugin

from .instances import MANAGEMENT

PLUGIN = ChannelPlugin(
    name="webhook",
    display_name="Webhook",
    runtime=f"{__package__}.channel:WebhookChannel",
    setup=ChannelSetupSpec(
        fields={
            "token": ChannelFieldSpec(kind="secret"),
            "region": ChannelFieldSpec(
                kind="enum",
                choices=frozenset({"us", "eu"}),
                default="us",
            ),
        },
        required=(SetupRequirement.field("token"),),
    ),
    management=MANAGEMENT,
)
```

随后，`instances.py` 会导出由渠道所有回调组装而成的无依赖适配器：

```python
from typing import Any

from nanobot.channels.contracts import ChannelInstanceSpec, ChannelManagementSpec

from .config import default_config


def instance_specs(section: Any, *, enabled_only: bool = True) -> list[ChannelInstanceSpec]:
    ...  # Expand the persisted channel-owned envelope.


def update_instance_config(
    section: Any,
    values: dict[str, Any],
    *,
    instance_id: str = "default",
) -> dict[str, Any]:
    ...  # Update one instance without discarding sibling data.


MANAGEMENT = ChannelManagementSpec(
    multi_instance=True,
    default_config=default_config,
    instance_specs=instance_specs,
    update_instance_config=update_instance_config,
)
```

`ChannelSetupSpec` 是可写字段名称、字段类型、选项、默认值、必需设置、密钥脱敏和可选后端验证的权威来源。设置 API 会拒绝此契约之外的字段。验证器接收 `(values, context)`；请使用 `context.allow_local_service_access` 处理主机网络策略，而不要从渠道包加载全局配置。

无依赖的 `MANAGEMENT` 值是一个 `ChannelManagementSpec`。多实例插件提供 `instance_specs(section, enabled_only=True)` 和 `update_instance_config(section, values, instance_id=...)`；它们还可以提供 `default_config`、`runtime_name`、仅用于展示的 `feature_instances` 和 `local_state_present`。单实例插件通常从 `ChannelSetupSpec` 派生引导默认值；仅当持久化默认值包含不属于通用设置的字段时才使用 `default_config`。

多实例适配器返回 `ChannelInstanceSpec` 对象，并在更新一个实例时保留其持久化封装。其描述符设置 `ChannelManagementSpec(multi_instance=True)`。共享契约强制执行以下不变条件：

- 每个 `instance_id` 都非空且唯一；
- 管理适配器的 `runtime_name(channel_name, instance_id)` 是路由名称的唯一来源，每个派生名称都唯一，并且要么是渠道名称，要么以 `<channel-name>.` 开头；
- 运行时名称不能覆盖已由另一个渠道拥有的运行时；
- 设置实例摘要由 `instance_specs()` 和 `ChannelPlugin.setup` 生成。它们包含权威的 `enabled` 和 `configured` 状态，以及供通用实例编辑器使用的、对密钥安全的 `config_values` 和 `configured_fields`；
- 管理适配器的 `feature_instances()` 可以返回 `None`，或包含 `id` 以及 `name`、`display_name` 或 `avatar_url` 的展示覆盖。它不能覆盖运行时状态或配置快照。

`ChannelInstanceSpec` 仅包含 `instance_id` 和实例配置；nanobot 通过适配器派生其运行时名称。单实例插件保留其完整配置的所有权，包括名为 `instances` 的字段。只有管理规格将 `multi_instance=True` 的插件才会选择加入实例展开。

包/配置节名称拥有从该节生成的每个运行时。类继承不会将运行时所有权转移给另一个包。

从适配器的 `instance_specs()` 返回具体的可迭代对象或生成器；nanobot 会在构造任何运行时之前将其具体化并验证。对于格式错误的持久化数据，应抛出异常，而不是静默更改实例标识。将网络支持的元数据刷新保留在运行时的 `refresh_feature_metadata()` 之后，以便功能 GET 请求保持无依赖且只读。

有关包布局、WebUI 所有权和本地化规则，请参阅[渠道包要求](#channel-package-requirements)。

### 可选（流式传输）

| 方法 | 说明 |
|--------|-------------|
| `async send_delta(chat_id, delta, metadata?, *, stream_id?, stream_end=False, resuming=False)` | 重写以接收流式数据块。详见[流式传输支持](#streaming-support)。 |

### 消息类型

```python
@dataclass
class OutboundMessage:
    channel: str        # your channel name
    chat_id: str        # recipient (same value you passed to _handle_message)
    content: str        # markdown text — convert to platform format as needed
    media: list[str]    # local file paths to attach (images, audio, docs)
    metadata: dict      # channel routing context, e.g. "message_id" for threading
    event: object | None # typed runtime/UI event; usually inspect with isinstance()
```

运行时/UI 语义位于 `msg.event`。插件编写的出站消息应使用类型化事件，而非 `_progress`、`_stream_delta`、`_stream_end`、`_reasoning_delta`、`_turn_end` 或 `_goal_status` 等旧版元数据标志。nanobot 仍接受这些旧标志，作为现有进程内扩展的兼容桥梁，但新插件代码不应新增对它们的依赖。

## 流式传输支持

渠道可以选择启用实时流式传输，代理会逐个 token 发送内容，而不是仅发送一条最终消息。这完全是可选的；无需它渠道也能正常工作。

### 工作原理

当**同时**满足以下两个条件时，代理会通过你的渠道流式发送内容：

1. 配置包含 `"streaming": true`
2. 你的子类重写了 `send_delta()`

如果缺少任一条件，代理会回退到普通的一次性 `send()` 路径。

### 实现 `send_delta`

重写 `send_delta` 以处理两类调用：

```python
async def send_delta(
    self,
    chat_id: str,
    delta: str,
    metadata: dict[str, Any] | None = None,
    *,
    stream_id: str | None = None,
    stream_end: bool = False,
    resuming: bool = False,
) -> None:
    buffer_key = stream_id or chat_id
    if stream_end:
        # Streaming finished — do final formatting, cleanup, etc.
        return

    # Regular delta — append text, update the message on screen
    # delta contains a small chunk of text (a few tokens)
```

流式传输状态通过仅关键字参数传递，而不是通过 `_stream_delta` 或 `_stream_end` 元数据标志。使用 `stream_id` 作为每个流缓冲区的键；缺失时回退使用 `chat_id`。

### 示例：带流式传输的 Webhook

```python
class WebhookChannel(BaseChannel):
    name = "webhook"
    display_name = "Webhook"

    def __init__(self, config: Any, bus: MessageBus):
        if isinstance(config, dict):
            config = WebhookConfig(**config)
        super().__init__(config, bus)
        self._buffers: dict[str, str] = {}

    async def send_delta(
        self,
        chat_id: str,
        delta: str,
        metadata: dict[str, Any] | None = None,
        *,
        stream_id: str | None = None,
        stream_end: bool = False,
        resuming: bool = False,
    ) -> None:
        buffer_key = stream_id or chat_id
        if stream_end:
            text = self._buffers.pop(buffer_key, "")
            # Final delivery — format and send the complete message
            await self._deliver(chat_id, text, final=True)
            return

        self._buffers.setdefault(buffer_key, "")
        self._buffers[buffer_key] += delta
        # Incremental update — push partial text to the client
        await self._deliver(chat_id, self._buffers[buffer_key], final=False)

    async def send(self, msg: OutboundMessage) -> None:
        # Non-streaming path — unchanged
        await self._deliver(msg.chat_id, msg.content, final=True)
```

### 配置

按渠道启用流式传输：

```json
{
  "channels": {
    "webhook": {
      "enabled": true,
      "streaming": true,
      "allowFrom": ["*"]
    }
  }
}
```

当 `streaming` 为 `false`（默认值）或被省略时，仅调用 `send()`，没有流式传输开销。

### BaseChannel 流式传输 API

| 方法 / 属性 | 说明 |
|-------------------|-------------|
| `async send_delta(chat_id, delta, metadata?, *, stream_id?, stream_end=False, resuming=False)` | 重写以处理流式数据块。默认为空操作。 |
| `supports_streaming` (property) | 当配置包含 `streaming: true` **且**子类重写 `send_delta` 时返回 `True`。 |

## 进度、工具提示和推理

除普通助手文本外，nanobot 还可以发出低强调度的追踪块。这些内容旨在用于状态行、可折叠的“已使用工具”分组或推理/思考块等 UI 交互元素。没有合适显示位置的平台可以安全地忽略它们。

### 进度和工具提示

进度和工具提示通过普通 `send(msg)` 路径到达。渲染前请检查 `msg.event`：

```python
from nanobot.bus.outbound_events import ProgressEvent

async def send(self, msg: OutboundMessage) -> None:
    event = msg.event

    if isinstance(event, ProgressEvent) and event.tool_hint:
        # A short tool breadcrumb, e.g. read_file("config.json")
        await self._send_trace(msg.chat_id, msg.content, kind="tool")
        return

    if isinstance(event, ProgressEvent):
        # Generic non-final status, e.g. "Thinking..." or "Running command..."
        await self._send_trace(msg.chat_id, msg.content, kind="progress")
        return

    await self._send_message(msg.chat_id, msg.content, media=msg.media)
```

工具提示默认开启。用户可以全局禁用，也可以按渠道禁用：

```json
{
  "channels": {
    "sendToolHints": true,
    "webhook": {
      "enabled": true,
      "sendToolHints": false
    }
  }
}
```

### 推理块

推理通过专用的可选钩子交付，而不是 `send()`。如果你的平台能够将模型推理显示为低强调度/可折叠的块，请重写 `send_reasoning_delta()` 和 `send_reasoning_end()`。默认实现为空操作，因此不支持的渠道会直接丢弃推理内容。

```python
class WebhookChannel(BaseChannel):
    name = "webhook"
    display_name = "Webhook"

    def __init__(self, config: Any, bus: MessageBus):
        if isinstance(config, dict):
            config = WebhookConfig(**config)
        super().__init__(config, bus)
        self._reasoning_buffers: dict[str, str] = {}

    async def send_reasoning_delta(
        self,
        chat_id: str,
        delta: str,
        metadata: dict[str, Any] | None = None,
        *,
        stream_id: str | None = None,
    ) -> None:
        buffer_key = stream_id or chat_id
        self._reasoning_buffers[buffer_key] = self._reasoning_buffers.get(buffer_key, "") + delta
        await self._update_reasoning_block(chat_id, self._reasoning_buffers[buffer_key], final=False)

    async def send_reasoning_end(
        self,
        chat_id: str,
        metadata: dict[str, Any] | None = None,
        *,
        stream_id: str | None = None,
    ) -> None:
        buffer_key = stream_id or chat_id
        text = self._reasoning_buffers.pop(buffer_key, "")
        if text:
            await self._update_reasoning_block(chat_id, text, final=True)
```

**推理参数：**

| 参数 | 含义 |
|------|---------|
| `delta` | `send_reasoning_delta()` 的一个推理/思考数据块。 |
| `stream_id` | 此助手轮次/片段的稳定 ID。使用它作为缓冲区的键，而非仅使用 `chat_id`。 |
| `send_reasoning_end()` | 当前推理块已完成。 |

推理可见性可通过全局或按渠道的 `showReasoning` 控制：

```json
{
  "channels": {
    "showReasoning": true,
    "webhook": {
      "enabled": true,
      "showReasoning": true
    }
  }
}
```

建议的渲染方式：

- 将工具提示和进度渲染为追踪/状态 UI，而不是普通助手回复。
- 使用较低的视觉强调度渲染推理；当平台支持时，在完成后将其折叠。
- 将推理与最终答案文本分开。最终答案仍通过 `send()` 或 `send_delta()` 到达。

## 配置

### 为什么需要 Pydantic 模型

`BaseChannel.is_allowed()` 通过 `getattr(self.config, "allow_from", [])` 读取权限列表。这对于 `allow_from` 是真实 Python 属性的 Pydantic 模型有效，但对普通 `dict` **会静默失败**，因为 `dict` 没有 `allow_from` 属性，所以 `getattr` 始终返回默认值 `[]`，导致所有消息都被拒绝。

渠道运行时通过继承 `nanobot.config.schema` 中的 `Base` 来使用 Pydantic 配置模型。

### 模式

1. 定义一个继承自 `nanobot.config.schema.Base` 的 Pydantic 模型：

```python
from pydantic import Field
from nanobot.config.schema import Base

class WebhookConfig(Base):
    """Webhook channel configuration."""
    enabled: bool = False
    port: int = 9000
    allow_from: list[str] = Field(default_factory=list)
```

`Base` 配置了 `alias_generator=to_camel` 和 `populate_by_name=True`，因此 `"allowFrom"` 和 `"allow_from"` 等 JSON 键都可以接受。

2. 在 `__init__` 中将 `dict` 转换为模型：

```python
from typing import Any
from nanobot.bus.queue import MessageBus

class WebhookChannel(BaseChannel):
    def __init__(self, config: Any, bus: MessageBus):
        if isinstance(config, dict):
            config = WebhookConfig(**config)
        super().__init__(config, bus)
```

3. 以属性方式访问配置（而非 `.get()`）：

```python
async def start(self) -> None:
    port = self.config.port
    token = self.config.token
```

`allowFrom` 会由 `_handle_message()` 自动处理，无需自行检查。

`nanobot onboard` 会在不导入运行时的情况下读取描述符。请将可写默认值放入 `ChannelSetupSpec`：

```python
setup=ChannelSetupSpec(
    fields={
        "port": ChannelFieldSpec(kind="int", default=9000),
        "allowFrom": ChannelFieldSpec(kind="list"),
    },
)
```

未声明显式默认值时，字符串和密钥字段默认为 `""`，列表字段默认为 `[]`，布尔字段默认为 `false`。对于非设置或多实例持久化默认值，请从无依赖的包本地模块提供 `ChannelManagementSpec.default_config`。
## 命名约定

| 内容 | 格式 | 示例 |
|------|--------|---------|
| 包目录 | `nanobot/channels/{name}` | `nanobot/channels/webhook` |
| 清单名称 | `{name}` | `webhook` |
| 配置段 | `channels.{name}` | `channels.webhook` |
| 运行时导入 | `nanobot.channels.{name}.runtime` | `nanobot.channels.webhook.runtime` |

## 本地开发

```bash
git clone https://github.com/HKUDS/nanobot.git
cd nanobot
python -m pip install -e .
nanobot plugins list    # 应将该包显示为 "webhook"
nanobot plugins enable webhook
nanobot gateway         # 端到端测试
```

## 验证

```bash
$ nanobot plugins list

  Name       Type      Enabled
  discord    channel   no
  telegram   channel   yes
  webhook    channel   yes
```
