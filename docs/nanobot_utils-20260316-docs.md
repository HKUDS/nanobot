# Project Documentation

- **Generated at:** 2026-03-16 23:11:27
- **Root Dir:** `nanobot/utils`
- **File Count:** 3
- **Total Size:** 9.66 KB
claude 解读：
*Thinking...*

> The user has shared documentation for a Python project called `nanobot/utils` containing three files: `__init__.py`, `evaluator.py`, and `helpers.py`. They simply said "详细解释" which means "detailed explanation" in Chinese. Let me provide a thorough explanation of the entire codebase in Chinese.

# `nanobot/utils` 模块详细解释

这是一个名为 **nanobot** 的智能代理（Agent）项目中的工具模块，包含三个文件。下面逐一详细分析。

---

## 1. `__init__.py` — 模块入口

这个文件非常简洁，它将 `helpers.py` 中的 `ensure_dir` 函数导出为本模块的公开 API。这意味着外部代码可以直接通过 `from nanobot.utils import ensure_dir` 来使用，而不需要知道它具体定义在哪个子文件里。`__all__` 列表声明了模块的公开接口，当别人使用 `from nanobot.utils import *` 时，只会导入 `ensure_dir`。

值得注意的是，`helpers.py` 中其实有很多实用函数，但只有 `ensure_dir` 被提升到了包级别。其他函数需要通过 `from nanobot.utils.helpers import xxx` 显式导入，这是一种有意为之的封装策略。

---

## 2. `evaluator.py` — 后台任务通知评估器

### 整体目的

这个模块解决的问题是：当 nanobot 在后台执行定时任务（心跳检测、定时任务等）后，**是否需要通知用户**。并不是所有后台任务的结果都值得打扰用户，所以它使用一个轻量级的 LLM 调用来做"通知门控"（notification gate）。

### `_EVALUATE_TOOL` 工具定义

这是一个符合 OpenAI function calling 格式的工具定义。它定义了一个名为 `evaluate_notification` 的函数，LLM 被要求调用这个函数来返回结构化的判断结果。参数有两个：`should_notify`（布尔值，是否通知）和 `reason`（一句话解释原因）。其中 `should_notify` 是必填的，`reason` 是可选的。

这种"强制 LLM 通过 tool call 返回结构化数据"的模式是目前 Agent 开发中非常常见的做法，相比让 LLM 直接返回文本再解析，它更可靠、更不容易出格式错误。

### `_SYSTEM_PROMPT` 系统提示词

系统提示词明确告诉 LLM 它的角色是一个"通知门控"，并给出了两类判断标准：应该通知的情况包括可操作的信息、错误、已完成的交付物、用户明确要求提醒的事项；应该抑制的情况包括常规状态检查无新内容、一切正常的确认、基本为空的回复。

### `evaluate_response` 异步函数

这是模块的核心函数。它接收四个参数：`response`（代理的执行结果文本）、`task_context`（原始任务描述）、`provider`（LLM 提供者实例，如 OpenAI、Anthropic 等）、`model`（使用的模型名）。

函数的执行流程如下：首先将原始任务和代理回复组装成一条用户消息，连同系统提示词一起发送给 LLM，要求它调用 `evaluate_notification` 工具。`temperature=0.0` 确保结果的确定性，`max_tokens=256` 限制开销。然后检查 LLM 是否返回了 tool call，如果返回了就提取 `should_notify` 字段作为结果。

关键的设计决策是**失败安全**（fail-safe）：无论是 LLM 没有返回 tool call，还是整个调用过程抛出异常，都默认返回 `True`（通知用户）。这确保了重要信息永远不会被静默丢弃。这是一种保守但合理的策略——误通知只是打扰用户，而漏通知可能导致用户错过关键信息。

---

## 3. `helpers.py` — 通用工具函数集

这是一个包含多个独立工具函数的文件，覆盖了从文件操作到 token 估算的多种需求。

### `detect_image_mime(data: bytes)`

通过检查文件的**魔术字节**（magic bytes）来判断图片的 MIME 类型，而不是依赖文件扩展名。它支持四种格式：PNG（以 `\x89PNG\r\n\x1a\n` 开头）、JPEG（以 `\xff\xd8\xff` 开头）、GIF（以 `GIF87a` 或 `GIF89a` 开头）、WebP（以 `RIFF....WEBP` 结构开头）。无法识别时返回 `None`。这在处理用户上传的图片时非常实用，因为文件扩展名可能是错误的或缺失的。

### `ensure_dir(path: Path)`

确保目录存在，如果不存在就递归创建。`parents=True` 意味着会创建所有缺失的中间目录，`exist_ok=True` 意味着如果目录已存在不会报错。返回路径本身，方便链式调用。

### `timestamp()`

返回当前时间的 ISO 格式字符串，例如 `2026-03-16T23:11:27.123456`。

### `safe_filename(name: str)`

用正则表达式将文件名中不安全的字符（`< > : " / \ | ? *`）替换为下划线。这些字符在 Windows 或 URL 中会引起问题。替换后还会去除首尾空格。

### `split_message(content: str, max_len: int = 2000)`

将长文本分割成不超过 `max_len` 字符的多个块。默认上限 2000 是 Discord 消息的长度限制，这暗示 nanobot 可能运行在 Discord 平台上。分割策略是智能的：优先在换行符处断开，其次在空格处断开，最后才硬性截断。这样可以尽量保持消息的可读性。分割后会对剩余部分做 `lstrip()` 去除前导空白。

### `build_assistant_message(...)`

构建一个标准的 assistant 消息字典，支持可选的 `tool_calls`、`reasoning_content`（用于 DeepSeek 等模型的推理内容）和 `thinking_blocks`（用于 Claude 的思考块）。这种设计表明 nanobot 支持多种 LLM 提供商，并且需要适配不同模型的消息格式差异。

### `estimate_prompt_tokens(messages, tools)`

使用 OpenAI 的 `tiktoken` 库（`cl100k_base` 编码，对应 GPT-4 系列）来估算 prompt 的 token 数量。它提取所有消息中的文本内容（包括纯文本和结构化内容列表中的文本部分），如果有 tools 定义也会加上它的 JSON 序列化文本，然后统一编码计数。如果 tiktoken 出错则返回 0。

需要注意的是，这只是一个**估算**，因为它忽略了模型实际的 token 化规则中的一些细节，比如每条消息的固定开销 token、角色标记等。但作为预算控制来说已经足够。

### `estimate_message_tokens(message)`

估算单条消息的 token 数。比上面的函数更精细：它不仅处理 `content`，还会计入 `name`、`tool_call_id` 和 `tool_calls` 字段。对于非字符串的 content（如列表或其他类型），它会 JSON 序列化后再计数。有一个保底逻辑：如果 tiktoken 失败，就用字符数除以 4 来粗略估算（英文平均约 4 字符一个 token）。任何情况下最少返回 1。

### `estimate_prompt_tokens_chain(provider, model, messages, tools)`

这是一个带优先级的 token 估算链。它优先使用 LLM provider 自带的 token 计数器（如果有的话），因为不同模型的 tokenizer 不同，provider 自己的计数器会更准确。如果 provider 没有计数器或计数失败，就 fallback 到 tiktoken 估算。返回值是一个元组 `(token数, 来源)`，来源标识了使用了哪种计数方法，便于调试。

### `sync_workspace_templates(workspace, silent)`

将项目捆绑的模板文件同步到用户的工作区目录。它使用 Python 的 `importlib.resources` 来访问包内的模板资源，只创建缺失的文件（不覆盖已有文件）。具体会同步以下内容：`templates/` 下所有 `.md` 文件到工作区根目录、`memory/MEMORY.md` 和一个空的 `memory/HISTORY.md`，以及创建 `skills/` 目录。

这个函数有两个值得注意的设计：一是 `_write` 内部函数接受 `src=None` 的情况，此时会创建空文件（用于 `HISTORY.md`）；二是非静默模式下使用 `rich` 库美化输出，告知用户创建了哪些文件。导入 `rich` 和 `importlib.resources` 是延迟导入（lazy import），避免在不需要时增加启动开销。

---

## 整体架构观察

从这三个文件可以推断出 nanobot 项目的几个特征：它是一个**多 LLM 提供商**的智能代理框架，支持后台定时任务，很可能运行在 **Discord** 等即时通讯平台上。项目采用了异步编程模型（`async/await`），使用 `loguru` 做日志，`tiktoken` 做 token 估算，`rich` 做终端美化输出。整体代码风格简洁，类型注解完整，异常处理策略倾向于保守安全（宁可多通知也不漏通知，宁可多估算也不返回错误值）。

<a name="toc"></a>
## 📂 扫描目录
- [__init__.py](#📄-__init__py) (5 lines, 0.11 KB)
- [evaluator.py](#📄-evaluatorpy) (92 lines, 3.18 KB)
- [helpers.py](#📄-helperspy) (203 lines, 6.38 KB)

---

## 📄 __init__.py

````python
"""Utility functions for nanobot."""

from nanobot.utils.helpers import ensure_dir

__all__ = ["ensure_dir"]

````

[⬆ 回到目录](#toc)

## 📄 evaluator.py

````python
"""Post-run evaluation for background tasks (heartbeat & cron).

After the agent executes a background task, this module makes a lightweight
LLM call to decide whether the result warrants notifying the user.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from nanobot.providers.base import LLMProvider

_EVALUATE_TOOL = [
    {
        "type": "function",
        "function": {
            "name": "evaluate_notification",
            "description": "Decide whether the user should be notified about this background task result.",
            "parameters": {
                "type": "object",
                "properties": {
                    "should_notify": {
                        "type": "boolean",
                        "description": "true = result contains actionable/important info the user should see; false = routine or empty, safe to suppress",
                    },
                    "reason": {
                        "type": "string",
                        "description": "One-sentence reason for the decision",
                    },
                },
                "required": ["should_notify"],
            },
        },
    }
]

_SYSTEM_PROMPT = (
    "You are a notification gate for a background agent. "
    "You will be given the original task and the agent's response. "
    "Call the evaluate_notification tool to decide whether the user "
    "should be notified.\n\n"
    "Notify when the response contains actionable information, errors, "
    "completed deliverables, or anything the user explicitly asked to "
    "be reminded about.\n\n"
    "Suppress when the response is a routine status check with nothing "
    "new, a confirmation that everything is normal, or essentially empty."
)


async def evaluate_response(
    response: str,
    task_context: str,
    provider: LLMProvider,
    model: str,
) -> bool:
    """Decide whether a background-task result should be delivered to the user.

    Uses a lightweight tool-call LLM request (same pattern as heartbeat
    ``_decide()``).  Falls back to ``True`` (notify) on any failure so
    that important messages are never silently dropped.
    """
    try:
        llm_response = await provider.chat_with_retry(
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": (
                    f"## Original task\n{task_context}\n\n"
                    f"## Agent response\n{response}"
                )},
            ],
            tools=_EVALUATE_TOOL,
            model=model,
            max_tokens=256,
            temperature=0.0,
        )

        if not llm_response.has_tool_calls:
            logger.warning("evaluate_response: no tool call returned, defaulting to notify")
            return True

        args = llm_response.tool_calls[0].arguments
        should_notify = args.get("should_notify", True)
        reason = args.get("reason", "")
        logger.info("evaluate_response: should_notify={}, reason={}", should_notify, reason)
        return bool(should_notify)

    except Exception:
        logger.exception("evaluate_response failed, defaulting to notify")
        return True

````

[⬆ 回到目录](#toc)

## 📄 helpers.py

````python
"""Utility functions for nanobot."""

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import tiktoken


def detect_image_mime(data: bytes) -> str | None:
    """Detect image MIME type from magic bytes, ignoring file extension."""
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def ensure_dir(path: Path) -> Path:
    """Ensure directory exists, return it."""
    path.mkdir(parents=True, exist_ok=True)
    return path


def timestamp() -> str:
    """Current ISO timestamp."""
    return datetime.now().isoformat()


_UNSAFE_CHARS = re.compile(r'[<>:"/\\|?*]')

def safe_filename(name: str) -> str:
    """Replace unsafe path characters with underscores."""
    return _UNSAFE_CHARS.sub("_", name).strip()


def split_message(content: str, max_len: int = 2000) -> list[str]:
    """
    Split content into chunks within max_len, preferring line breaks.

    Args:
        content: The text content to split.
        max_len: Maximum length per chunk (default 2000 for Discord compatibility).

    Returns:
        List of message chunks, each within max_len.
    """
    if not content:
        return []
    if len(content) <= max_len:
        return [content]
    chunks: list[str] = []
    while content:
        if len(content) <= max_len:
            chunks.append(content)
            break
        cut = content[:max_len]
        # Try to break at newline first, then space, then hard break
        pos = cut.rfind('\n')
        if pos <= 0:
            pos = cut.rfind(' ')
        if pos <= 0:
            pos = max_len
        chunks.append(content[:pos])
        content = content[pos:].lstrip()
    return chunks


def build_assistant_message(
    content: str | None,
    tool_calls: list[dict[str, Any]] | None = None,
    reasoning_content: str | None = None,
    thinking_blocks: list[dict] | None = None,
) -> dict[str, Any]:
    """Build a provider-safe assistant message with optional reasoning fields."""
    msg: dict[str, Any] = {"role": "assistant", "content": content}
    if tool_calls:
        msg["tool_calls"] = tool_calls
    if reasoning_content is not None:
        msg["reasoning_content"] = reasoning_content
    if thinking_blocks:
        msg["thinking_blocks"] = thinking_blocks
    return msg


def estimate_prompt_tokens(
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
) -> int:
    """Estimate prompt tokens with tiktoken."""
    try:
        enc = tiktoken.get_encoding("cl100k_base")
        parts: list[str] = []
        for msg in messages:
            content = msg.get("content")
            if isinstance(content, str):
                parts.append(content)
            elif isinstance(content, list):
                for part in content:
                    if isinstance(part, dict) and part.get("type") == "text":
                        txt = part.get("text", "")
                        if txt:
                            parts.append(txt)
        if tools:
            parts.append(json.dumps(tools, ensure_ascii=False))
        return len(enc.encode("\n".join(parts)))
    except Exception:
        return 0


def estimate_message_tokens(message: dict[str, Any]) -> int:
    """Estimate prompt tokens contributed by one persisted message."""
    content = message.get("content")
    parts: list[str] = []
    if isinstance(content, str):
        parts.append(content)
    elif isinstance(content, list):
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                text = part.get("text", "")
                if text:
                    parts.append(text)
            else:
                parts.append(json.dumps(part, ensure_ascii=False))
    elif content is not None:
        parts.append(json.dumps(content, ensure_ascii=False))

    for key in ("name", "tool_call_id"):
        value = message.get(key)
        if isinstance(value, str) and value:
            parts.append(value)
    if message.get("tool_calls"):
        parts.append(json.dumps(message["tool_calls"], ensure_ascii=False))

    payload = "\n".join(parts)
    if not payload:
        return 1
    try:
        enc = tiktoken.get_encoding("cl100k_base")
        return max(1, len(enc.encode(payload)))
    except Exception:
        return max(1, len(payload) // 4)


def estimate_prompt_tokens_chain(
    provider: Any,
    model: str | None,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
) -> tuple[int, str]:
    """Estimate prompt tokens via provider counter first, then tiktoken fallback."""
    provider_counter = getattr(provider, "estimate_prompt_tokens", None)
    if callable(provider_counter):
        try:
            tokens, source = provider_counter(messages, tools, model)
            if isinstance(tokens, (int, float)) and tokens > 0:
                return int(tokens), str(source or "provider_counter")
        except Exception:
            pass

    estimated = estimate_prompt_tokens(messages, tools)
    if estimated > 0:
        return int(estimated), "tiktoken"
    return 0, "none"


def sync_workspace_templates(workspace: Path, silent: bool = False) -> list[str]:
    """Sync bundled templates to workspace. Only creates missing files."""
    from importlib.resources import files as pkg_files
    try:
        tpl = pkg_files("nanobot") / "templates"
    except Exception:
        return []
    if not tpl.is_dir():
        return []

    added: list[str] = []

    def _write(src, dest: Path):
        if dest.exists():
            return
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(src.read_text(encoding="utf-8") if src else "", encoding="utf-8")
        added.append(str(dest.relative_to(workspace)))

    for item in tpl.iterdir():
        if item.name.endswith(".md") and not item.name.startswith("."):
            _write(item, workspace / item.name)
    _write(tpl / "memory" / "MEMORY.md", workspace / "memory" / "MEMORY.md")
    _write(None, workspace / "memory" / "HISTORY.md")
    (workspace / "skills").mkdir(exist_ok=True)

    if added and not silent:
        from rich.console import Console
        for name in added:
            Console().print(f"  [dim]Created {name}[/dim]")
    return added

````

[⬆ 回到目录](#toc)

---
### 📊 最终统计汇总
- **文件总数:** 3
- **代码总行数:** 300
- **物理总大小:** 9.66 KB
