# Project Documentation

- **Generated at:** 2026-03-16 23:10:51
- **Root Dir:** `nanobot/cli`
- **File Count:** 2
- **Total Size:** 42.00 KB
 claude 解读：

 *Thinking...*

> The user wants a detailed explanation of the code in the attached document, which is the CLI module for a project called "nanobot" - a personal AI assistant. Let me go through the code systematically and explain it in Chinese since the user's request is in Chinese ("详细解释代码含义").
> 
> Let me break down the code structure and explain each part thoroughly.

# nanobot CLI 模块详细解析

这份代码是 **nanobot**（一个个人 AI 助手项目）的命令行界面（CLI）模块，由两个文件组成。下面按模块结构逐层展开分析。

---

## 一、`__init__.py`

仅一行文档字符串，声明这是 nanobot 的 CLI 子包，使 Python 将该目录识别为一个可导入的包。

---

## 二、`commands.py`（核心文件）

这是整个 CLI 的实现，约 1175 行，基于 **Typer** 框架构建命令行应用。整体可以分为以下几大块：

---

### 1. 导入与环境初始化（第 1–43 行）

```python
if sys.platform == "win32":
    ...
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
```

代码首先处理 **Windows 控制台的 UTF-8 编码问题**。Windows 的默认控制台编码通常不是 UTF-8，这会导致中文、emoji 等字符输出乱码或崩溃。这段代码强制将标准输出和标准错误流切换为 UTF-8 编码，`errors="replace"` 表示遇到无法编码的字符时用替代符号代替而非抛出异常。

随后导入了几大类依赖：

- **Typer**：用于构建 CLI 命令和参数解析，是 Click 的类型注解封装。
- **prompt_toolkit**：提供交互式输入体验，包括行编辑、历史记录、粘贴处理、ANSI 着色输出等。
- **Rich**：用于终端的富文本渲染，包括 Markdown 渲染、表格显示、彩色文字等。
- 项目内部模块：配置加载、工作区路径、模板同步等。

最后创建了 Typer 应用实例和 Rich Console 实例，并定义了退出命令集合 `EXIT_COMMANDS`。

---

### 2. 终端输入与输出处理（第 45–175 行）

这部分封装了交互式会话所需的全部终端 I/O 逻辑。

**`_flush_pending_tty_input()`** 的作用是：当 AI 模型正在生成回复时，用户可能不小心按了几个键，这些击键会残留在输入缓冲区中。这个函数在每次等待用户输入前，先把缓冲区中残留的字符全部丢弃。它优先使用 POSIX 的 `termios.tcflush()`，如果不可用（比如在 Windows 上），就退化为用 `select` + `os.read` 循环读空缓冲区。

**`_restore_terminal()`** 用于恢复终端的原始状态。prompt_toolkit 在运行时会修改终端属性（比如关闭回显、启用 raw 模式），如果程序异常退出，终端可能停留在异常状态（比如不显示用户输入）。这个函数通过 `termios.tcsetattr` 把之前保存的终端属性恢复回去。

**`_init_prompt_session()`** 初始化 prompt_toolkit 的会话对象。它做了两件事：第一，保存当前终端属性（`tcgetattr`）以便日后恢复；第二，创建一个 `PromptSession`，挂载了基于文件的历史记录（`FileHistory`），这样用户可以用上下箭头浏览之前的输入。`multiline=False` 表示按 Enter 直接提交，而不是换行。

**`_render_interactive_ansi()`** 是一个桥接函数。Rich 和 prompt_toolkit 各有自己的输出系统，直接混用会产生显示冲突。这个函数让 Rich 先把内容渲染成 ANSI 转义序列字符串（通过 `Console.capture()`），然后交给 prompt_toolkit 的 `print_formatted_text(ANSI(...))` 来输出，从而保证两个库的输出不会互相干扰。

**`_print_agent_response()`** 用于非交互模式下打印 AI 的回复。它创建新的 Console 实例，可选地将回复内容渲染为 Markdown（带语法高亮、列表格式化等），然后加上 nanobot 的 logo 前缀输出。

**`_print_interactive_line()`** 和 **`_print_interactive_response()`** 是交互模式下的异步版本。它们使用 `run_in_terminal` 来确保输出操作在 prompt_toolkit 的事件循环中安全执行，避免打断正在进行的用户输入。

**`_read_interactive_input_async()`** 是异步的用户输入读取函数。`patch_stdout()` 上下文管理器确保在 prompt_toolkit 等待输入期间，任何对 stdout 的写入都会被正确重绘，不会破坏提示符的显示。`prompt_async` 返回用户输入的字符串，HTML 格式的提示符显示为蓝色粗体的 "You:"。当用户按 Ctrl+D（EOF）时，将其转换为 `KeyboardInterrupt` 以统一退出处理逻辑。

---

### 3. `onboard` 命令（第 189–248 行）

这是 nanobot 的**首次设置/初始化命令**，相当于 `git init` 之于 Git。

执行流程如下：首先检查配置文件是否已存在。如果存在，给用户两个选择——完全重置为默认值，或者保留现有配置同时补充新版本新增的字段。后者通过 `_merge_missing_defaults()` 递归合并实现：遍历默认配置的每个键，只在用户配置中缺失时才补充，不覆盖用户已修改的值。

接着调用 `_onboard_plugins()` 来发现所有已安装的 channel 插件（比如 Telegram、WhatsApp），并把每个插件的默认配置注入到主配置文件的 `channels` 段中。这种设计使得用户安装新的 channel 插件后，只需重新运行 `nanobot onboard` 就能自动生成该插件的配置模板。

最后创建工作区目录并同步模板文件，然后打印下一步操作指引。

---

### 4. `_make_provider()` 工厂函数（第 260–315 行）

这个函数根据配置创建 LLM 提供者实例，是整个系统的**模型接入层**。它支持多种后端：

**OpenAI Codex** 分支处理 OAuth 认证的 OpenAI Codex 模型。**Custom** 分支用于用户自建的 OpenAI 兼容端点（比如本地部署的 vLLM 或 Ollama），直接走 HTTP 调用而不经过 LiteLLM。**Azure OpenAI** 分支处理 Azure 部署的 OpenAI 模型，需要 api_key 和 api_base（Azure 的端点 URL 格式与 OpenAI 不同）。**默认分支**通过 **LiteLLM**——一个统一了几十种 LLM API 的代理库——来路由请求。LiteLLM 支持的模型通过 `providers.registry` 中的注册信息来判断是否需要 API key（OAuth 提供者和本地模型不需要）。

最后，无论使用哪种 provider，都统一设置生成参数（temperature、max_tokens、reasoning_effort），确保所有 provider 的行为一致。

---

### 5. `gateway` 命令（第 325–535 行）

这是 nanobot 最复杂的命令，启动一个**长驻服务进程**，集成了消息总线、多 channel 接入、定时任务、心跳服务和 HTTP API。

**架构概览：** 整个 gateway 采用事件驱动架构。核心是一个 `MessageBus`（消息总线），所有组件通过它进行异步通信。`AgentLoop`（智能体主循环）从总线消费入站消息，调用 LLM 处理，再将结果发布为出站消息。`ChannelManager` 管理所有启用的通信渠道（Telegram、WhatsApp 等），每个渠道将用户消息转为入站事件，将出站事件转为渠道特定的回复。

**定时任务（CronService）：** 这是一个持久化的调度器，支持用户通过自然语言设置定时提醒。`on_cron_job` 回调定义了任务触发时的处理逻辑：构造一条"定时任务提醒"消息，通过 agent 的 `process_direct` 处理，然后根据配置决定是否将结果投递到用户的聊天渠道。这里有个巧妙的设计——它通过 `evaluate_response` 函数让 LLM 判断回复是否值得发送给用户，避免无意义的通知打扰。

**心跳服务（HeartbeatService）：** 定期唤醒 agent，让它检查是否有需要主动执行的任务。`_pick_heartbeat_target()` 选择一个真实的用户聊天会话作为投递目标，优先选最近活跃的非内部会话，确保 agent 的主动消息能到达用户。

**HTTP API：** 在 gateway 端口上启动了一个 aiohttp 服务器，暴露 `/api/message` 和 `/api/health` 两个端点。`/api/message` 接收 JSON 格式的消息，通过 agent 处理后返回回复，支持超时控制。这为外部系统（如微信桥接）提供了简单的 HTTP 集成接口。

**未知渠道的出站消息捕获：** `capture_unknown_channel_outbound()` 是一个后台协程，监听总线上的出站消息。如果消息的目标渠道不在已启用的渠道列表中（比如来自 HTTP API 的 wechat 请求），就把消息暂存到 `pending_outbound` 字典中，等 HTTP 请求处理完成时一起返回。这解决了"HTTP 请求期间 agent 使用 message 工具发送消息"的场景。

**启动流程：** `run()` 协程依次启动 cron、heartbeat、HTTP 服务器，然后并发运行 agent 主循环、所有 channel 和出站消息捕获。`finally` 块确保退出时所有组件都被正确清理。

---

### 6. `agent` 命令（第 541–710 行）

这是用户直接与 AI 对话的命令，支持两种模式。

**单次消息模式**（`nanobot agent -m "Hello"`）：最简单的使用方式。创建 AgentLoop 但不启动总线消费循环，直接调用 `process_direct()` 处理消息并打印结果。如果日志关闭，会显示一个旋转动画（spinner）让用户知道系统在工作。

**交互模式**（不带 `-m` 参数）：进入一个类似 REPL 的循环。这里的实现值得仔细看：

信号处理：注册了 SIGINT、SIGTERM、SIGHUP 处理器，确保在任何中断情况下都能恢复终端状态后优雅退出。SIGPIPE 被忽略，防止向已关闭的管道写入时进程被静默杀死（这在 Unix 管道操作中很常见）。

`run_interactive()` 的核心设计用了**事件驱动 + 同步等待**的混合模式。`agent_loop.run()` 作为后台任务持续运行，消费总线上的入站消息。用户输入被发布为 `InboundMessage` 到总线，然后通过 `turn_done` 事件等待回复。`_consume_outbound()` 协程持续监听出站消息——带 `_progress` 标记的是中间状态更新（比如"正在搜索网页..."），直接显示为缩进的灰色提示；不带标记的是最终回复，触发 `turn_done` 事件。

`_cli_progress` 回调函数检查 channels_config 中的配置来决定是否显示进度提示和工具提示，这使得 CLI 的行为可以通过配置文件控制。

`_thinking_ctx()` 根据日志开关决定是否显示 spinner——开启日志时 spinner 会和日志输出冲突，所以用 `nullcontext()` 跳过。

---

### 7. `channels` 子命令组（第 716–830 行）

**`channels status`** 命令展示所有已注册渠道的启用状态，用 Rich Table 渲染为美观的表格。

**`_get_bridge_dir()`** 是 WhatsApp 桥接的构建管理函数。nanobot 通过一个 Node.js 桥接程序与 WhatsApp Web 通信。这个函数检查桥接是否已构建，如果没有就自动执行完整的构建流程：定位源码（优先从安装包查找，退化到开发目录）、复制到用户目录、运行 `npm install` 和 `npm run build`。这种设计让用户不需要手动处理 Node.js 构建。

**`channels login`** 启动 WhatsApp 桥接进程，让用户扫描 QR 码完成设备关联。它从配置中读取桥接令牌和认证目录，通过环境变量传递给 Node.js 进程。

---

### 8. `plugins` 子命令组（第 836–878 行）

**`plugins list`** 列出所有已发现的渠道插件，区分"内置"（builtin）和"第三方插件"（plugin），并显示启用状态。它通过比较 `discover_channel_names()`（内置名称列表）和 `discover_all()`（包含插件的完整列表）来判断来源。

---

### 9. `status` 命令（第 884–920 行）

全局状态检查命令。它检查并报告配置文件是否存在、工作区是否创建、当前使用的模型名称，以及各个 provider 的 API key 配置情况。对于 OAuth 类 provider 显示 "(OAuth)"，对于本地 provider 显示端点地址，对于其他 provider 显示 key 是否已设置。

---

### 10. `provider login` 子命令组（第 926–1000 行）

处理需要 OAuth 认证的 LLM 提供者的登录流程。采用了**注册表模式**：`_LOGIN_HANDLERS` 字典存储各 provider 名称到登录函数的映射，`@_register_login` 装饰器用于注册。

**OpenAI Codex 登录**：使用 `oauth_cli_kit` 库，先尝试获取缓存的 token，如果没有则启动交互式 OAuth 流程（通常涉及打开浏览器授权）。

**GitHub Copilot 登录**：利用 LiteLLM 内置的 device flow 支持——直接尝试发送一个请求，LiteLLM 会自动触发 GitHub 的设备授权流程（让用户在浏览器中输入验证码）。这是一种巧妙的"懒初始化"方式。

---

## 三、整体架构总结

这个 CLI 模块体现了几个核心设计理念：

**事件驱动解耦**。所有组件通过 MessageBus 通信，agent 不直接知道消息来自 CLI 还是 Telegram，channel 也不知道 agent 的内部实现。这使得添加新渠道只需实现入站/出站的消息转换。

**渐进式复杂度**。`agent -m "hello"` 是最简单的同步调用；交互模式增加了异步输入输出；`gateway` 则是完整的服务进程。三种模式共享同一套 agent 和 provider 代码。

**终端体验的精细打磨**。从 Windows UTF-8 修复、终端状态保存恢复、输入缓冲区清理、prompt_toolkit 与 Rich 的 ANSI 桥接，到 SIGPIPE 忽略，每一处都在解决实际使用中会遇到的终端问题。

**插件化扩展**。channel 通过 registry 自动发现，provider 通过注册表管理，配置通过递归合并保持向后兼容。新增功能不需要修改核心代码。

<a name="toc"></a>
## 📂 扫描目录
- [__init__.py](#📄-__init__py) (1 lines, 0.03 KB)
- [commands.py](#📄-commandspy) (1175 lines, 41.97 KB)

---

## 📄 __init__.py

````python
"""CLI module for nanobot."""

````

[⬆ 回到目录](#toc)

## 📄 commands.py

````python
"""CLI commands for nanobot."""

import asyncio
import os
import select
import signal
import sys
from pathlib import Path
from typing import Any
import json
import time

# Force UTF-8 encoding for Windows console
if sys.platform == "win32":
    if sys.stdout.encoding != "utf-8":
        os.environ["PYTHONIOENCODING"] = "utf-8"
        # Re-open stdout/stderr with UTF-8 encoding
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

import typer
from prompt_toolkit import print_formatted_text
from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import ANSI, HTML
from prompt_toolkit.history import FileHistory
from prompt_toolkit.patch_stdout import patch_stdout
from prompt_toolkit.application import run_in_terminal
from rich.console import Console
from rich.markdown import Markdown
from rich.table import Table
from rich.text import Text

from nanobot import __logo__, __version__
from nanobot.config.paths import get_workspace_path
from nanobot.config.schema import Config
from nanobot.utils.helpers import sync_workspace_templates

app = typer.Typer(
    name="nanobot",
    help=f"{__logo__} nanobot - Personal AI Assistant",
    no_args_is_help=True,
)

console = Console()
EXIT_COMMANDS = {"exit", "quit", "/exit", "/quit", ":q"}

# ---------------------------------------------------------------------------
# CLI input: prompt_toolkit for editing, paste, history, and display
# ---------------------------------------------------------------------------

_PROMPT_SESSION: PromptSession | None = None
_SAVED_TERM_ATTRS = None  # original termios settings, restored on exit


def _flush_pending_tty_input() -> None:
    """Drop unread keypresses typed while the model was generating output."""
    try:
        fd = sys.stdin.fileno()
        if not os.isatty(fd):
            return
    except Exception:
        return

    try:
        import termios
        termios.tcflush(fd, termios.TCIFLUSH)
        return
    except Exception:
        pass

    try:
        while True:
            ready, _, _ = select.select([fd], [], [], 0)
            if not ready:
                break
            if not os.read(fd, 4096):
                break
    except Exception:
        return


def _restore_terminal() -> None:
    """Restore terminal to its original state (echo, line buffering, etc.)."""
    if _SAVED_TERM_ATTRS is None:
        return
    try:
        import termios
        termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, _SAVED_TERM_ATTRS)
    except Exception:
        pass


def _init_prompt_session() -> None:
    """Create the prompt_toolkit session with persistent file history."""
    global _PROMPT_SESSION, _SAVED_TERM_ATTRS

    # Save terminal state so we can restore it on exit
    try:
        import termios
        _SAVED_TERM_ATTRS = termios.tcgetattr(sys.stdin.fileno())
    except Exception:
        pass

    from nanobot.config.paths import get_cli_history_path

    history_file = get_cli_history_path()
    history_file.parent.mkdir(parents=True, exist_ok=True)

    _PROMPT_SESSION = PromptSession(
        history=FileHistory(str(history_file)),
        enable_open_in_editor=False,
        multiline=False,   # Enter submits (single line mode)
    )


def _make_console() -> Console:
    return Console(file=sys.stdout)


def _render_interactive_ansi(render_fn) -> str:
    """Render Rich output to ANSI so prompt_toolkit can print it safely."""
    ansi_console = Console(
        force_terminal=True,
        color_system=console.color_system or "standard",
        width=console.width,
    )
    with ansi_console.capture() as capture:
        render_fn(ansi_console)
    return capture.get()


def _print_agent_response(response: str, render_markdown: bool) -> None:
    """Render assistant response with consistent terminal styling."""
    console = _make_console()
    content = response or ""
    body = Markdown(content) if render_markdown else Text(content)
    console.print()
    console.print(f"[cyan]{__logo__} nanobot[/cyan]")
    console.print(body)
    console.print()


async def _print_interactive_line(text: str) -> None:
    """Print async interactive updates with prompt_toolkit-safe Rich styling."""
    def _write() -> None:
        ansi = _render_interactive_ansi(
            lambda c: c.print(f"  [dim]↳ {text}[/dim]")
        )
        print_formatted_text(ANSI(ansi), end="")

    await run_in_terminal(_write)


async def _print_interactive_response(response: str, render_markdown: bool) -> None:
    """Print async interactive replies with prompt_toolkit-safe Rich styling."""
    def _write() -> None:
        content = response or ""
        ansi = _render_interactive_ansi(
            lambda c: (
                c.print(),
                c.print(f"[cyan]{__logo__} nanobot[/cyan]"),
                c.print(Markdown(content) if render_markdown else Text(content)),
                c.print(),
            )
        )
        print_formatted_text(ANSI(ansi), end="")

    await run_in_terminal(_write)


def _is_exit_command(command: str) -> bool:
    """Return True when input should end interactive chat."""
    return command.lower() in EXIT_COMMANDS


async def _read_interactive_input_async() -> str:
    """Read user input using prompt_toolkit (handles paste, history, display).

    prompt_toolkit natively handles:
    - Multiline paste (bracketed paste mode)
    - History navigation (up/down arrows)
    - Clean display (no ghost characters or artifacts)
    """
    if _PROMPT_SESSION is None:
        raise RuntimeError("Call _init_prompt_session() first")
    try:
        with patch_stdout():
            return await _PROMPT_SESSION.prompt_async(
                HTML("<b fg='ansiblue'>You:</b> "),
            )
    except EOFError as exc:
        raise KeyboardInterrupt from exc



def version_callback(value: bool):
    if value:
        console.print(f"{__logo__} nanobot v{__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        None, "--version", "-v", callback=version_callback, is_eager=True
    ),
):
    """nanobot - Personal AI Assistant."""
    pass


# ============================================================================
# Onboard / Setup
# ============================================================================


@app.command()
def onboard():
    """Initialize nanobot configuration and workspace."""
    from nanobot.config.loader import get_config_path, load_config, save_config
    from nanobot.config.schema import Config

    config_path = get_config_path()

    if config_path.exists():
        console.print(f"[yellow]Config already exists at {config_path}[/yellow]")
        console.print("  [bold]y[/bold] = overwrite with defaults (existing values will be lost)")
        console.print("  [bold]N[/bold] = refresh config, keeping existing values and adding new fields")
        if typer.confirm("Overwrite?"):
            config = Config()
            save_config(config)
            console.print(f"[green]✓[/green] Config reset to defaults at {config_path}")
        else:
            config = load_config()
            save_config(config)
            console.print(f"[green]✓[/green] Config refreshed at {config_path} (existing values preserved)")
    else:
        save_config(Config())
        console.print(f"[green]✓[/green] Created config at {config_path}")

    console.print("[dim]Config template now uses `maxTokens` + `contextWindowTokens`; `memoryWindow` is no longer a runtime setting.[/dim]")

    _onboard_plugins(config_path)

    # Create workspace
    workspace = get_workspace_path()

    if not workspace.exists():
        workspace.mkdir(parents=True, exist_ok=True)
        console.print(f"[green]✓[/green] Created workspace at {workspace}")

    sync_workspace_templates(workspace)

    console.print(f"\n{__logo__} nanobot is ready!")
    console.print("\nNext steps:")
    console.print("  1. Add your API key to [cyan]~/.nanobot/config.json[/cyan]")
    console.print("     Get one at: https://openrouter.ai/keys")
    console.print("  2. Chat: [cyan]nanobot agent -m \"Hello!\"[/cyan]")
    console.print("\n[dim]Want Telegram/WhatsApp? See: https://github.com/HKUDS/nanobot#-chat-apps[/dim]")


def _merge_missing_defaults(existing: Any, defaults: Any) -> Any:
    """Recursively fill in missing values from defaults without overwriting user config."""
    if not isinstance(existing, dict) or not isinstance(defaults, dict):
        return existing

    merged = dict(existing)
    for key, value in defaults.items():
        if key not in merged:
            merged[key] = value
        else:
            merged[key] = _merge_missing_defaults(merged[key], value)
    return merged


def _onboard_plugins(config_path: Path) -> None:
    """Inject default config for all discovered channels (built-in + plugins)."""
    import json

    from nanobot.channels.registry import discover_all

    all_channels = discover_all()
    if not all_channels:
        return

    with open(config_path, encoding="utf-8") as f:
        data = json.load(f)

    channels = data.setdefault("channels", {})
    for name, cls in all_channels.items():
        if name not in channels:
            channels[name] = cls.default_config()
        else:
            channels[name] = _merge_missing_defaults(channels[name], cls.default_config())

    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def _make_provider(config: Config):
    """Create the appropriate LLM provider from config."""
    from nanobot.providers.base import GenerationSettings
    from nanobot.providers.openai_codex_provider import OpenAICodexProvider
    from nanobot.providers.azure_openai_provider import AzureOpenAIProvider

    model = config.agents.defaults.model
    provider_name = config.get_provider_name(model)
    p = config.get_provider(model)

    # OpenAI Codex (OAuth)
    if provider_name == "openai_codex" or model.startswith("openai-codex/"):
        provider = OpenAICodexProvider(default_model=model)
    # Custom: direct OpenAI-compatible endpoint, bypasses LiteLLM
    elif provider_name == "custom":
        from nanobot.providers.custom_provider import CustomProvider
        provider = CustomProvider(
            api_key=p.api_key if p else "no-key",
            api_base=config.get_api_base(model) or "http://localhost:8000/v1",
            default_model=model,
        )
    # Azure OpenAI: direct Azure OpenAI endpoint with deployment name
    elif provider_name == "azure_openai":
        if not p or not p.api_key or not p.api_base:
            console.print("[red]Error: Azure OpenAI requires api_key and api_base.[/red]")
            console.print("Set them in ~/.nanobot/config.json under providers.azure_openai section")
            console.print("Use the model field to specify the deployment name.")
            raise typer.Exit(1)
        provider = AzureOpenAIProvider(
            api_key=p.api_key,
            api_base=p.api_base,
            default_model=model,
        )
    else:
        from nanobot.providers.litellm_provider import LiteLLMProvider
        from nanobot.providers.registry import find_by_name
        spec = find_by_name(provider_name)
        if not model.startswith("bedrock/") and not (p and p.api_key) and not (spec and (spec.is_oauth or spec.is_local)):
            console.print("[red]Error: No API key configured.[/red]")
            console.print("Set one in ~/.nanobot/config.json under providers section")
            raise typer.Exit(1)
        provider = LiteLLMProvider(
            api_key=p.api_key if p else None,
            api_base=config.get_api_base(model),
            default_model=model,
            extra_headers=p.extra_headers if p else None,
            provider_name=provider_name,
        )

    defaults = config.agents.defaults
    provider.generation = GenerationSettings(
        temperature=defaults.temperature,
        max_tokens=defaults.max_tokens,
        reasoning_effort=defaults.reasoning_effort,
    )
    return provider


def _load_runtime_config(config: str | None = None, workspace: str | None = None) -> Config:
    """Load config and optionally override the active workspace."""
    from nanobot.config.loader import load_config, set_config_path

    config_path = None
    if config:
        config_path = Path(config).expanduser().resolve()
        if not config_path.exists():
            console.print(f"[red]Error: Config file not found: {config_path}[/red]")
            raise typer.Exit(1)
        set_config_path(config_path)
        console.print(f"[dim]Using config: {config_path}[/dim]")

    loaded = load_config(config_path)
    if workspace:
        loaded.agents.defaults.workspace = workspace
    return loaded


def _print_deprecated_memory_window_notice(config: Config) -> None:
    """Warn when running with old memoryWindow-only config."""
    if config.agents.defaults.should_warn_deprecated_memory_window:
        console.print(
            "[yellow]Hint:[/yellow] Detected deprecated `memoryWindow` without "
            "`contextWindowTokens`. `memoryWindow` is ignored; run "
            "[cyan]nanobot onboard[/cyan] to refresh your config template."
        )


# ============================================================================
# Gateway / Server
# ============================================================================


@app.command()
def gateway(
    port: int | None = typer.Option(None, "--port", "-p", help="Gateway port"),
    workspace: str | None = typer.Option(None, "--workspace", "-w", help="Workspace directory"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose output"),
    config: str | None = typer.Option(None, "--config", "-c", help="Path to config file"),
):
    """Start the nanobot gateway."""
    from nanobot.agent.loop import AgentLoop
    from nanobot.bus.queue import MessageBus
    from nanobot.channels.manager import ChannelManager
    from nanobot.config.paths import get_cron_dir
    from nanobot.cron.service import CronService
    from nanobot.cron.types import CronJob
    from nanobot.heartbeat.service import HeartbeatService
    from nanobot.session.manager import SessionManager

    if verbose:
        import logging
        logging.basicConfig(level=logging.DEBUG)

    config = _load_runtime_config(config, workspace)
    _print_deprecated_memory_window_notice(config)
    port = port if port is not None else config.gateway.port

    console.print(f"{__logo__} Starting nanobot gateway on port {port}...")
    sync_workspace_templates(config.workspace_path)
    bus = MessageBus()
    provider = _make_provider(config)
    session_manager = SessionManager(config.workspace_path)

    # Create cron service first (callback set after agent creation)
    cron_store_path = get_cron_dir() / "jobs.json"
    cron = CronService(cron_store_path)

    # Create agent with cron service
    agent = AgentLoop(
        bus=bus,
        provider=provider,
        workspace=config.workspace_path,
        model=config.agents.defaults.model,
        max_iterations=config.agents.defaults.max_tool_iterations,
        context_window_tokens=config.agents.defaults.context_window_tokens,
        web_search_config=config.tools.web.search,
        web_proxy=config.tools.web.proxy or None,
        exec_config=config.tools.exec,
        cron_service=cron,
        restrict_to_workspace=config.tools.restrict_to_workspace,
        session_manager=session_manager,
        mcp_servers=config.tools.mcp_servers,
        channels_config=config.channels,
    )

    # Set cron callback (needs agent)
    async def on_cron_job(job: CronJob) -> str | None:
        """Execute a cron job through the agent."""
        from nanobot.agent.tools.cron import CronTool
        from nanobot.agent.tools.message import MessageTool
        from nanobot.utils.evaluator import evaluate_response

        reminder_note = (
            "[Scheduled Task] Timer finished.\n\n"
            f"Task '{job.name}' has been triggered.\n"
            f"Scheduled instruction: {job.payload.message}"
        )

        cron_tool = agent.tools.get("cron")
        cron_token = None
        if isinstance(cron_tool, CronTool):
            cron_token = cron_tool.set_cron_context(True)
        try:
            response = await agent.process_direct(
                reminder_note,
                session_key=f"cron:{job.id}",
                channel=job.payload.channel or "cli",
                chat_id=job.payload.to or "direct",
            )
        finally:
            if isinstance(cron_tool, CronTool) and cron_token is not None:
                cron_tool.reset_cron_context(cron_token)

        message_tool = agent.tools.get("message")
        if isinstance(message_tool, MessageTool) and message_tool._sent_in_turn:
            return response

        if job.payload.deliver and job.payload.to and response:
            should_notify = await evaluate_response(
                response, job.payload.message, provider, agent.model,
            )
            if should_notify:
                from nanobot.bus.events import OutboundMessage
                await bus.publish_outbound(OutboundMessage(
                    channel=job.payload.channel or "cli",
                    chat_id=job.payload.to,
                    content=response,
                ))
        return response
    cron.on_job = on_cron_job

    # Create channel manager
    channels = ChannelManager(config, bus)

    def _pick_heartbeat_target() -> tuple[str, str]:
        """Pick a routable channel/chat target for heartbeat-triggered messages."""
        enabled = set(channels.enabled_channels)
        # Prefer the most recently updated non-internal session on an enabled channel.
        for item in session_manager.list_sessions():
            key = item.get("key") or ""
            if ":" not in key:
                continue
            channel, chat_id = key.split(":", 1)
            if channel in {"cli", "system"}:
                continue
            if channel in enabled and chat_id:
                return channel, chat_id
        # Fallback keeps prior behavior but remains explicit.
        return "cli", "direct"

    # Create heartbeat service
    async def on_heartbeat_execute(tasks: str) -> str:
        """Phase 2: execute heartbeat tasks through the full agent loop."""
        channel, chat_id = _pick_heartbeat_target()

        async def _silent(*_args, **_kwargs):
            pass

        return await agent.process_direct(
            tasks,
            session_key="heartbeat",
            channel=channel,
            chat_id=chat_id,
            on_progress=_silent,
        )

    async def on_heartbeat_notify(response: str) -> None:
        """Deliver a heartbeat response to the user's channel."""
        from nanobot.bus.events import OutboundMessage
        channel, chat_id = _pick_heartbeat_target()
        if channel == "cli":
            return  # No external channel available to deliver to
        await bus.publish_outbound(OutboundMessage(channel=channel, chat_id=chat_id, content=response))

    hb_cfg = config.gateway.heartbeat
    heartbeat = HeartbeatService(
        workspace=config.workspace_path,
        provider=provider,
        model=agent.model,
        on_execute=on_heartbeat_execute,
        on_notify=on_heartbeat_notify,
        interval_s=hb_cfg.interval_s,
        enabled=hb_cfg.enabled,
    )

    if channels.enabled_channels:
        console.print(f"[green]✓[/green] Channels enabled: {', '.join(channels.enabled_channels)}")
    else:
        console.print("[yellow]Warning: No channels enabled[/yellow]")

    cron_status = cron.status()
    if cron_status["jobs"] > 0:
        console.print(f"[green]✓[/green] Cron: {cron_status['jobs']} scheduled jobs")

    console.print(f"[green]✓[/green] Heartbeat: every {hb_cfg.interval_s}s")

    # Create HTTP API server for external integrations
    from aiohttp import web

    # Track outbound messages for unknown channels (used by HTTP API)
    pending_outbound: dict[str, list[dict]] = {}

    async def handle_message(request: web.Request) -> web.Response:
        """Handle incoming messages from external sources (e.g., wechat_bridge)."""
        try:
            data = await request.json()
            message = data.get("message", "").strip()
            user_id = data.get("user_id", "unknown")
            channel = data.get("channel", "wechat")
            timeout = data.get("timeout", 60)

            if not message:
                return web.json_response({"error": "message is required"}, status=400)

            # Clear pending outbound for this session
            session_key = f"{channel}:{user_id}"
            pending_outbound[session_key] = []

            # Process message through agent
            response = await asyncio.wait_for(
                agent.process_direct(
                    message,
                    session_key=session_key,
                    channel=channel,
                    chat_id=user_id,
                ),
                timeout=timeout
            )

            # Collect any pending outbound messages for unknown channels
            outbound_messages = pending_outbound.pop(session_key, [])
            media_paths = []
            for msg in outbound_messages:
                if msg.get("media"):
                    media_paths.extend(msg.get("media", []))
                # If no text response but there's outbound content, use it
                if not response and msg.get("content"):
                    response = msg["content"]

            return web.json_response({
                "response": response or "",
                "media": media_paths
            })

        except asyncio.TimeoutError:
            return web.json_response({"error": "timeout"}, status=504)
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    # Subscribe to outbound messages to capture those for unknown channels
    async def capture_unknown_channel_outbound():
        """Capture outbound messages for unknown channels."""
        while True:
            try:
                msg = await asyncio.wait_for(
                    bus.consume_outbound(),
                    timeout=1.0
                )
                # Only capture messages for channels not handled by channel manager
                if msg.channel not in channels.enabled_channels:
                    session_key = f"{msg.channel}:{msg.chat_id}"
                    if session_key in pending_outbound:
                        pending_outbound[session_key].append({
                            "content": msg.content,
                            "media": msg.media,
                        })
                    else:
                        # Also try with just the channel (for messages sent to different users)
                        for key in list(pending_outbound.keys()):
                            if key.startswith(f"{msg.channel}:"):
                                pending_outbound[key].append({
                                    "content": msg.content,
                                    "media": msg.media,
                                })
                                break
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            except Exception:
                continue

    async def handle_health(request: web.Request) -> web.Response:
        """Health check endpoint."""
        return web.json_response({"status": "ok", "channels": list(channels.enabled_channels)})

    # Create aiohttp app
    http_app = web.Application()
    http_app.router.add_post("/api/message", handle_message)
    http_app.router.add_get("/api/health", handle_health)

    # Reuse the gateway port for HTTP API
    http_runner = web.AppRunner(http_app)

    async def run():
        try:
            await cron.start()
            await heartbeat.start()
            await http_runner.setup()
            http_site = web.TCPSite(http_runner, "0.0.0.0", port)
            await http_site.start()
            console.print(f"[green]✓[/green] HTTP API: http://0.0.0.0:{port}/api/message")

            await asyncio.gather(
                agent.run(),
                channels.start_all(),
                capture_unknown_channel_outbound(),
            )
        except KeyboardInterrupt:
            console.print("\nShutting down...")
        except Exception:
            import traceback
            console.print("\n[red]Error: Gateway crashed unexpectedly[/red]")
            console.print(traceback.format_exc())
        finally:
            await http_runner.cleanup()
            await agent.close_mcp()
            heartbeat.stop()
            cron.stop()
            agent.stop()
            await channels.stop_all()

    asyncio.run(run())




# ============================================================================
# Agent Commands
# ============================================================================


@app.command()
def agent(
    message: str = typer.Option(None, "--message", "-m", help="Message to send to the agent"),
    session_id: str = typer.Option("cli:direct", "--session", "-s", help="Session ID"),
    workspace: str | None = typer.Option(None, "--workspace", "-w", help="Workspace directory"),
    config: str | None = typer.Option(None, "--config", "-c", help="Config file path"),
    markdown: bool = typer.Option(True, "--markdown/--no-markdown", help="Render assistant output as Markdown"),
    logs: bool = typer.Option(False, "--logs/--no-logs", help="Show nanobot runtime logs during chat"),
):
    """Interact with the agent directly."""
    from loguru import logger

    from nanobot.agent.loop import AgentLoop
    from nanobot.bus.queue import MessageBus
    from nanobot.config.paths import get_cron_dir
    from nanobot.cron.service import CronService

    config = _load_runtime_config(config, workspace)
    _print_deprecated_memory_window_notice(config)
    sync_workspace_templates(config.workspace_path)

    bus = MessageBus()
    provider = _make_provider(config)

    # Create cron service for tool usage (no callback needed for CLI unless running)
    cron_store_path = get_cron_dir() / "jobs.json"
    cron = CronService(cron_store_path)

    if logs:
        logger.enable("nanobot")
    else:
        logger.disable("nanobot")

    agent_loop = AgentLoop(
        bus=bus,
        provider=provider,
        workspace=config.workspace_path,
        model=config.agents.defaults.model,
        max_iterations=config.agents.defaults.max_tool_iterations,
        context_window_tokens=config.agents.defaults.context_window_tokens,
        web_search_config=config.tools.web.search,
        web_proxy=config.tools.web.proxy or None,
        exec_config=config.tools.exec,
        cron_service=cron,
        restrict_to_workspace=config.tools.restrict_to_workspace,
        mcp_servers=config.tools.mcp_servers,
        channels_config=config.channels,
    )

    # Show spinner when logs are off (no output to miss); skip when logs are on
    def _thinking_ctx():
        if logs:
            from contextlib import nullcontext
            return nullcontext()
        # Animated spinner is safe to use with prompt_toolkit input handling
        return console.status("[dim]nanobot is thinking...[/dim]", spinner="dots")

    async def _cli_progress(content: str, *, tool_hint: bool = False) -> None:
        ch = agent_loop.channels_config
        if ch and tool_hint and not ch.send_tool_hints:
            return
        if ch and not tool_hint and not ch.send_progress:
            return
        console.print(f"  [dim]↳ {content}[/dim]")

    if message:
        # Single message mode — direct call, no bus needed
        async def run_once():
            with _thinking_ctx():
                response = await agent_loop.process_direct(message, session_id, on_progress=_cli_progress)
            _print_agent_response(response, render_markdown=markdown)
            await agent_loop.close_mcp()

        asyncio.run(run_once())
    else:
        # Interactive mode — route through bus like other channels
        from nanobot.bus.events import InboundMessage
        _init_prompt_session()
        console.print(f"{__logo__} Interactive mode (type [bold]exit[/bold] or [bold]Ctrl+C[/bold] to quit)\n")

        if ":" in session_id:
            cli_channel, cli_chat_id = session_id.split(":", 1)
        else:
            cli_channel, cli_chat_id = "cli", session_id

        def _handle_signal(signum, frame):
            sig_name = signal.Signals(signum).name
            _restore_terminal()
            console.print(f"\nReceived {sig_name}, goodbye!")
            sys.exit(0)

        signal.signal(signal.SIGINT, _handle_signal)
        signal.signal(signal.SIGTERM, _handle_signal)
        # SIGHUP is not available on Windows
        if hasattr(signal, 'SIGHUP'):
            signal.signal(signal.SIGHUP, _handle_signal)
        # Ignore SIGPIPE to prevent silent process termination when writing to closed pipes
        # SIGPIPE is not available on Windows
        if hasattr(signal, 'SIGPIPE'):
            signal.signal(signal.SIGPIPE, signal.SIG_IGN)

        async def run_interactive():
            bus_task = asyncio.create_task(agent_loop.run())
            turn_done = asyncio.Event()
            turn_done.set()
            turn_response: list[str] = []

            async def _consume_outbound():
                while True:
                    try:
                        msg = await asyncio.wait_for(bus.consume_outbound(), timeout=1.0)
                        if msg.metadata.get("_progress"):
                            is_tool_hint = msg.metadata.get("_tool_hint", False)
                            ch = agent_loop.channels_config
                            if ch and is_tool_hint and not ch.send_tool_hints:
                                pass
                            elif ch and not is_tool_hint and not ch.send_progress:
                                pass
                            else:
                                await _print_interactive_line(msg.content)

                        elif not turn_done.is_set():
                            if msg.content:
                                turn_response.append(msg.content)
                            turn_done.set()
                        elif msg.content:
                            await _print_interactive_response(msg.content, render_markdown=markdown)

                    except asyncio.TimeoutError:
                        continue
                    except asyncio.CancelledError:
                        break

            outbound_task = asyncio.create_task(_consume_outbound())

            try:
                while True:
                    try:
                        _flush_pending_tty_input()
                        user_input = await _read_interactive_input_async()
                        command = user_input.strip()
                        if not command:
                            continue

                        if _is_exit_command(command):
                            _restore_terminal()
                            console.print("\nGoodbye!")
                            break

                        turn_done.clear()
                        turn_response.clear()

                        await bus.publish_inbound(InboundMessage(
                            channel=cli_channel,
                            sender_id="user",
                            chat_id=cli_chat_id,
                            content=user_input,
                        ))

                        with _thinking_ctx():
                            await turn_done.wait()

                        if turn_response:
                            _print_agent_response(turn_response[0], render_markdown=markdown)
                    except KeyboardInterrupt:
                        _restore_terminal()
                        console.print("\nGoodbye!")
                        break
                    except EOFError:
                        _restore_terminal()
                        console.print("\nGoodbye!")
                        break
            finally:
                agent_loop.stop()
                outbound_task.cancel()
                await asyncio.gather(bus_task, outbound_task, return_exceptions=True)
                await agent_loop.close_mcp()

        asyncio.run(run_interactive())


# ============================================================================
# Channel Commands
# ============================================================================


channels_app = typer.Typer(help="Manage channels")
app.add_typer(channels_app, name="channels")


@channels_app.command("status")
def channels_status():
    """Show channel status."""
    from nanobot.channels.registry import discover_all
    from nanobot.config.loader import load_config

    config = load_config()

    table = Table(title="Channel Status")
    table.add_column("Channel", style="cyan")
    table.add_column("Enabled", style="green")

    for name, cls in sorted(discover_all().items()):
        section = getattr(config.channels, name, None)
        if section is None:
            enabled = False
        elif isinstance(section, dict):
            enabled = section.get("enabled", False)
        else:
            enabled = getattr(section, "enabled", False)
        table.add_row(
            cls.display_name,
            "[green]\u2713[/green]" if enabled else "[dim]\u2717[/dim]",
        )

    console.print(table)


def _get_bridge_dir() -> Path:
    """Get the bridge directory, setting it up if needed."""
    import shutil
    import subprocess

    # User's bridge location
    from nanobot.config.paths import get_bridge_install_dir

    user_bridge = get_bridge_install_dir()

    # Check if already built
    if (user_bridge / "dist" / "index.js").exists():
        return user_bridge

    # Check for npm
    npm_path = shutil.which("npm")
    if not npm_path:
        console.print("[red]npm not found. Please install Node.js >= 18.[/red]")
        raise typer.Exit(1)

    # Find source bridge: first check package data, then source dir
    pkg_bridge = Path(__file__).parent.parent / "bridge"  # nanobot/bridge (installed)
    src_bridge = Path(__file__).parent.parent.parent / "bridge"  # repo root/bridge (dev)

    source = None
    if (pkg_bridge / "package.json").exists():
        source = pkg_bridge
    elif (src_bridge / "package.json").exists():
        source = src_bridge

    if not source:
        console.print("[red]Bridge source not found.[/red]")
        console.print("Try reinstalling: pip install --force-reinstall nanobot")
        raise typer.Exit(1)

    console.print(f"{__logo__} Setting up bridge...")

    # Copy to user directory
    user_bridge.parent.mkdir(parents=True, exist_ok=True)
    if user_bridge.exists():
        shutil.rmtree(user_bridge)
    shutil.copytree(source, user_bridge, ignore=shutil.ignore_patterns("node_modules", "dist"))

    # Install and build
    try:
        console.print("  Installing dependencies...")
        subprocess.run([npm_path, "install"], cwd=user_bridge, check=True, capture_output=True)

        console.print("  Building...")
        subprocess.run([npm_path, "run", "build"], cwd=user_bridge, check=True, capture_output=True)

        console.print("[green]✓[/green] Bridge ready\n")
    except subprocess.CalledProcessError as e:
        console.print(f"[red]Build failed: {e}[/red]")
        if e.stderr:
            console.print(f"[dim]{e.stderr.decode()[:500]}[/dim]")
        raise typer.Exit(1)

    return user_bridge


@channels_app.command("login")
def channels_login():
    """Link device via QR code."""
    import shutil
    import subprocess

    from nanobot.config.loader import load_config
    from nanobot.config.paths import get_runtime_subdir

    config = load_config()
    bridge_dir = _get_bridge_dir()

    console.print(f"{__logo__} Starting bridge...")
    console.print("Scan the QR code to connect.\n")

    env = {**os.environ}
    wa_cfg = getattr(config.channels, "whatsapp", None) or {}
    bridge_token = wa_cfg.get("bridgeToken", "") if isinstance(wa_cfg, dict) else getattr(wa_cfg, "bridge_token", "")
    if bridge_token:
        env["BRIDGE_TOKEN"] = bridge_token
    env["AUTH_DIR"] = str(get_runtime_subdir("whatsapp-auth"))

    npm_path = shutil.which("npm")
    if not npm_path:
        console.print("[red]npm not found. Please install Node.js.[/red]")
        raise typer.Exit(1)

    try:
        subprocess.run([npm_path, "start"], cwd=bridge_dir, check=True, env=env)
    except subprocess.CalledProcessError as e:
        console.print(f"[red]Bridge failed: {e}[/red]")


# ============================================================================
# Plugin Commands
# ============================================================================

plugins_app = typer.Typer(help="Manage channel plugins")
app.add_typer(plugins_app, name="plugins")


@plugins_app.command("list")
def plugins_list():
    """List all discovered channels (built-in and plugins)."""
    from nanobot.channels.registry import discover_all, discover_channel_names
    from nanobot.config.loader import load_config

    config = load_config()
    builtin_names = set(discover_channel_names())
    all_channels = discover_all()

    table = Table(title="Channel Plugins")
    table.add_column("Name", style="cyan")
    table.add_column("Source", style="magenta")
    table.add_column("Enabled", style="green")

    for name in sorted(all_channels):
        cls = all_channels[name]
        source = "builtin" if name in builtin_names else "plugin"
        section = getattr(config.channels, name, None)
        if section is None:
            enabled = False
        elif isinstance(section, dict):
            enabled = section.get("enabled", False)
        else:
            enabled = getattr(section, "enabled", False)
        table.add_row(
            cls.display_name,
            source,
            "[green]yes[/green]" if enabled else "[dim]no[/dim]",
        )

    console.print(table)


# ============================================================================
# Status Commands
# ============================================================================


@app.command()
def status():
    """Show nanobot status."""
    from nanobot.config.loader import get_config_path, load_config

    config_path = get_config_path()
    config = load_config()
    workspace = config.workspace_path

    console.print(f"{__logo__} nanobot Status\n")

    console.print(f"Config: {config_path} {'[green]✓[/green]' if config_path.exists() else '[red]✗[/red]'}")
    console.print(f"Workspace: {workspace} {'[green]✓[/green]' if workspace.exists() else '[red]✗[/red]'}")

    if config_path.exists():
        from nanobot.providers.registry import PROVIDERS

        console.print(f"Model: {config.agents.defaults.model}")

        # Check API keys from registry
        for spec in PROVIDERS:
            p = getattr(config.providers, spec.name, None)
            if p is None:
                continue
            if spec.is_oauth:
                console.print(f"{spec.label}: [green]✓ (OAuth)[/green]")
            elif spec.is_local:
                # Local deployments show api_base instead of api_key
                if p.api_base:
                    console.print(f"{spec.label}: [green]✓ {p.api_base}[/green]")
                else:
                    console.print(f"{spec.label}: [dim]not set[/dim]")
            else:
                has_key = bool(p.api_key)
                console.print(f"{spec.label}: {'[green]✓[/green]' if has_key else '[dim]not set[/dim]'}")


# ============================================================================
# OAuth Login
# ============================================================================

provider_app = typer.Typer(help="Manage providers")
app.add_typer(provider_app, name="provider")


_LOGIN_HANDLERS: dict[str, callable] = {}


def _register_login(name: str):
    def decorator(fn):
        _LOGIN_HANDLERS[name] = fn
        return fn
    return decorator


@provider_app.command("login")
def provider_login(
    provider: str = typer.Argument(..., help="OAuth provider (e.g. 'openai-codex', 'github-copilot')"),
):
    """Authenticate with an OAuth provider."""
    from nanobot.providers.registry import PROVIDERS

    key = provider.replace("-", "_")
    spec = next((s for s in PROVIDERS if s.name == key and s.is_oauth), None)
    if not spec:
        names = ", ".join(s.name.replace("_", "-") for s in PROVIDERS if s.is_oauth)
        console.print(f"[red]Unknown OAuth provider: {provider}[/red]  Supported: {names}")
        raise typer.Exit(1)

    handler = _LOGIN_HANDLERS.get(spec.name)
    if not handler:
        console.print(f"[red]Login not implemented for {spec.label}[/red]")
        raise typer.Exit(1)

    console.print(f"{__logo__} OAuth Login - {spec.label}\n")
    handler()


@_register_login("openai_codex")
def _login_openai_codex() -> None:
    try:
        from oauth_cli_kit import get_token, login_oauth_interactive
        token = None
        try:
            token = get_token()
        except Exception:
            pass
        if not (token and token.access):
            console.print("[cyan]Starting interactive OAuth login...[/cyan]\n")
            token = login_oauth_interactive(
                print_fn=lambda s: console.print(s),
                prompt_fn=lambda s: typer.prompt(s),
            )
        if not (token and token.access):
            console.print("[red]✗ Authentication failed[/red]")
            raise typer.Exit(1)
        console.print(f"[green]✓ Authenticated with OpenAI Codex[/green]  [dim]{token.account_id}[/dim]")
    except ImportError:
        console.print("[red]oauth_cli_kit not installed. Run: pip install oauth-cli-kit[/red]")
        raise typer.Exit(1)


@_register_login("github_copilot")
def _login_github_copilot() -> None:
    import asyncio

    console.print("[cyan]Starting GitHub Copilot device flow...[/cyan]\n")

    async def _trigger():
        from litellm import acompletion
        await acompletion(model="github_copilot/gpt-4o", messages=[{"role": "user", "content": "hi"}], max_tokens=1)

    try:
        asyncio.run(_trigger())
        console.print("[green]✓ Authenticated with GitHub Copilot[/green]")
    except Exception as e:
        console.print(f"[red]Authentication error: {e}[/red]")
        raise typer.Exit(1)


if __name__ == "__main__":
    app()

````

[⬆ 回到目录](#toc)

---
### 📊 最终统计汇总
- **文件总数:** 2
- **代码总行数:** 1176
- **物理总大小:** 42.00 KB


# `commands.py` 代码详解

这是 **nanobot**（个人 AI 助手）的 **CLI 命令行界面** 模块，基于 `typer` 框架构建。代码量很大，我将按模块逐层解析。

---

## 一、文件总体架构

```
commands.py
├── 1. 导入与初始化（编码修复、库导入）
├── 2. 终端输入/输出工具函数（prompt_toolkit 相关）
├── 3. 命令：onboard（初始化配置）
├── 4. 命令：gateway（启动网关服务器）
├── 5. 命令：agent（与 AI 对话）
├── 6. 命令：channels（频道管理）
├── 7. 命令：plugins（插件管理）
├── 8. 命令：status（状态查看）
├── 9. 命令：provider login（OAuth 登录）
└── 10. 入口点
```

---

## 二、导入与初始化

```python
import asyncio
import os
import select
import signal
import sys
from pathlib import Path
from typing import Any
import json
import time
```

### Windows UTF-8 编码修复

```python
if sys.platform == "win32":
    if sys.stdout.encoding != "utf-8":
        os.environ["PYTHONIOENCODING"] = "utf-8"
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
```

> **目的**：Windows 控制台默认编码可能不是 UTF-8，这会导致中文/emoji 等字符输出乱码。这里**强制将 stdout/stderr 设为 UTF-8**。

### 关键第三方库

```python
import typer                    # CLI 框架（类似 argparse 但更现代）
from prompt_toolkit import ...  # 高级终端输入库（支持历史、粘贴、语法高亮）
from rich.console import Console # 终端美化输出库
from rich.markdown import Markdown
```

### 全局对象

```python
app = typer.Typer(
    name="nanobot",
    help=f"{__logo__} nanobot - Personal AI Assistant",
    no_args_is_help=True,  # 无参数时显示帮助
)

console = Console()
EXIT_COMMANDS = {"exit", "quit", "/exit", "/quit", ":q"}  # 退出命令集合
```

---

## 三、终端输入/输出工具函数

这部分解决的是**交互式终端的复杂问题**：

### 3.1 清空残留输入

```python
def _flush_pending_tty_input() -> None:
    """丢弃模型生成输出期间用户意外敲击的按键"""
```

> **场景**：AI 在思考时，用户可能无意按了键盘。这个函数在显示提示符前清空这些"垃圾输入"。

实现原理：
```
1. 优先用 termios.tcflush()（Unix 原生刷新）
2. 降级用 select + os.read 循环读取并丢弃
```

### 3.2 终端状态保存/恢复

```python
_SAVED_TERM_ATTRS = None  # 保存原始终端设置

def _restore_terminal() -> None:
    """恢复终端到原始状态（回显、行缓冲等）"""
    if _SAVED_TERM_ATTRS is None:
        return
    try:
        import termios
        termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, _SAVED_TERM_ATTRS)
    except Exception:
        pass
```

> **为什么需要**：`prompt_toolkit` 会修改终端的 raw mode。如果程序异常退出，终端可能变得不可用（不回显、不换行）。这里在退出时恢复原状。

### 3.3 初始化 prompt_toolkit 会话

```python
def _init_prompt_session() -> None:
    global _PROMPT_SESSION, _SAVED_TERM_ATTRS
    
    # 保存终端状态
    _SAVED_TERM_ATTRS = termios.tcgetattr(sys.stdin.fileno())
    
    # 创建带历史记录的输入会话
    _PROMPT_SESSION = PromptSession(
        history=FileHistory(str(history_file)),  # 持久化历史到文件
        enable_open_in_editor=False,
        multiline=False,   # Enter 直接提交（单行模式）
    )
```

> **功能**：支持 ↑↓ 翻阅历史、粘贴多行文本、持久化历史记录。

### 3.4 渲染输出

```python
def _render_interactive_ansi(render_fn) -> str:
    """将 Rich 输出渲染为 ANSI 字符串，供 prompt_toolkit 安全显示"""
```

> **问题**：Rich（输出库）和 prompt_toolkit（输入库）都想控制终端。直接混用会显示错乱。
>
> **解决**：Rich 先渲染成 ANSI 字符串 → 再交给 prompt_toolkit 输出。

```python
def _print_agent_response(response: str, render_markdown: bool) -> None:
    """渲染 AI 回复"""
    body = Markdown(content) if render_markdown else Text(content)
    console.print(f"[cyan]{__logo__} nanobot[/cyan]")  # 蓝色 logo
    console.print(body)                                  # Markdown 或纯文本
```

### 3.5 异步读取用户输入

```python
async def _read_interactive_input_async() -> str:
    with patch_stdout():  # 防止异步输出干扰输入行
        return await _PROMPT_SESSION.prompt_async(
            HTML("<b fg='ansiblue'>You:</b> "),  # 蓝色粗体 "You: " 提示符
        )
```

---

## 四、版本号回调

```python
def version_callback(value: bool):
    if value:
        console.print(f"{__logo__} nanobot v{__version__}")
        raise typer.Exit()

@app.callback()
def main(
    version: bool = typer.Option(
        None, "--version", "-v", callback=version_callback, is_eager=True
    ),
):
    """nanobot - Personal AI Assistant."""
    pass
```

> 运行 `nanobot --version` 或 `nanobot -v` 时打印版本号并退出。
> `is_eager=True` 表示此选项优先于子命令处理。

---

## 五、`onboard` 命令 —— 初始化配置

```bash
$ nanobot onboard
```

```python
@app.command()
def onboard():
    """Initialize nanobot configuration and workspace."""
```

### 工作流程：

```
1. 检查配置文件是否存在
   ├── 存在 → 询问用户：
   │   ├── y → 覆盖为默认值
   │   └── N → 保留现有值，补充新字段
   └── 不存在 → 创建默认配置

2. 调用 _onboard_plugins() 注入所有频道的默认配置

3. 创建工作空间目录

4. 同步模板文件到工作空间

5. 打印引导信息（API key 设置等）
```

### 插件配置注入

```python
def _onboard_plugins(config_path: Path) -> None:
    """为所有发现的频道注入默认配置"""
    all_channels = discover_all()        # 发现所有频道（内置 + 插件）
    for name, cls in all_channels.items():
        if name not in channels:
            channels[name] = cls.default_config()  # 新频道 → 添加默认配置
        else:
            channels[name] = _merge_missing_defaults(...)  # 已有 → 合并缺失字段
```

### 递归合并函数

```python
def _merge_missing_defaults(existing, defaults):
    """递归填充缺失值，不覆盖用户已设置的值"""
    merged = dict(existing)
    for key, value in defaults.items():
        if key not in merged:
            merged[key] = value          # 缺失 → 用默认值
        else:
            merged[key] = _merge_missing_defaults(merged[key], value)  # 递归
    return merged
```

> 例如：用户配置了 `{"api_key": "xxx"}`，默认有 `{"api_key": "", "timeout": 30}`，合并后得到 `{"api_key": "xxx", "timeout": 30}`。

---

## 六、Provider 创建 —— `_make_provider()`

```python
def _make_provider(config: Config):
    """根据配置创建相应的 LLM 提供商"""
```

这是一个**工厂函数**，根据模型名/配置选择不同的 AI 提供商：

```
模型判断逻辑：
├── openai_codex/...        → OpenAICodexProvider（OAuth 认证）
├── custom                  → CustomProvider（自定义 OpenAI 兼容端点）
├── azure_openai            → AzureOpenAIProvider（Azure 部署）
└── 其他（默认）             → LiteLLMProvider（通用 LLM 路由）
    ├── bedrock/...         → AWS Bedrock（无需显式 API key）
    ├── OAuth 提供商         → 无需 API key
    ├── 本地模型             → 无需 API key
    └── 其他                → 需要 API key
```

最后设置生成参数：

```python
provider.generation = GenerationSettings(
    temperature=defaults.temperature,
    max_tokens=defaults.max_tokens,
    reasoning_effort=defaults.reasoning_effort,
)
```

---

## 七、`gateway` 命令 —— 启动网关服务器

```bash
$ nanobot gateway --port 8080
```

这是**最复杂的命令**，启动一个完整的后台服务：

```python
@app.command()
def gateway(
    port: int | None = ...,
    workspace: str | None = ...,
    verbose: bool = ...,
    config: str | None = ...,
):
```

### 架构图

```
┌─────────────────────────────────────────────────┐
│                  Gateway Server                  │
├─────────────────────────────────────────────────┤
│                                                  │
│  ┌──────────┐  ┌──────────┐  ┌──────────────┐  │
│  │ AgentLoop│  │ MessageBus│  │SessionManager│  │
│  │ (AI引擎) │←→│ (消息总线) │←→│ (会话管理)   │  │
│  └──────────┘  └──────────┘  └──────────────┘  │
│       ↕              ↕                           │
│  ┌──────────┐  ┌──────────────┐                 │
│  │CronService│ │ChannelManager│                 │
│  │(定时任务) │  │(频道管理)    │                 │
│  └──────────┘  ├──────────────┤                 │
│       ↕        │ - Telegram   │                 │
│  ┌──────────┐  │ - WhatsApp   │                 │
│  │Heartbeat │  │ - Discord    │                 │
│  │(心跳服务)│  │ - ...        │                 │
│  └──────────┘  └──────────────┘                 │
│       ↕                                          │
│  ┌──────────────────────┐                       │
│  │ HTTP API (aiohttp)   │                       │
│  │ POST /api/message    │                       │
│  │ GET  /api/health     │                       │
│  └──────────────────────┘                       │
└─────────────────────────────────────────────────┘
```

### 核心组件初始化

```python
bus = MessageBus()                          # 消息总线（发布-订阅模式）
provider = _make_provider(config)           # AI 提供商
session_manager = SessionManager(...)       # 会话管理
cron = CronService(c
```