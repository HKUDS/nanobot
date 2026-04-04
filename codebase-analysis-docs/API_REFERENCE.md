# API_REFERENCE.md — 工具与提供商 API 参考

---

## 1. 内置工具 JSON Schema

所有工具通过 `ToolRegistry.get_definitions()` 以 OpenAI function calling 格式暴露。

### read_file

```json
{
  "name": "read_file",
  "description": "Read file contents with optional pagination. Returns line-numbered output.",
  "parameters": {
    "type": "object",
    "properties": {
      "path":   { "type": "string", "description": "File path (relative to workspace or absolute)" },
      "offset": { "type": "integer", "description": "Start line number (1-indexed, default 1)" },
      "limit":  { "type": "integer", "description": "Max lines to read (default 2000)" }
    },
    "required": ["path"]
  }
}
```

**返回值：** 行号格式 `"1: content\n2: content\n..."` 或图片的多模态内容块。
**限制：** 128,000 字符；超出时截断并提示。

---

### write_file

```json
{
  "name": "write_file",
  "parameters": {
    "properties": {
      "path":    { "type": "string" },
      "content": { "type": "string" }
    },
    "required": ["path", "content"]
  }
}
```

**行为：** 覆写全文件；自动创建父目录；UTF-8 编码。

---

### edit_file

```json
{
  "name": "edit_file",
  "parameters": {
    "properties": {
      "path":        { "type": "string" },
      "old_text":    { "type": "string", "description": "Exact text block to find (fuzzy whitespace match)" },
      "new_text":    { "type": "string" },
      "replace_all": { "type": "boolean", "default": false }
    },
    "required": ["path", "old_text", "new_text"]
  }
}
```

**模糊匹配：** 先精确匹配，失败则按行去 strip() 后做滑窗匹配。替换时保留原文件缩进。

---

### list_dir

```json
{
  "name": "list_dir",
  "parameters": {
    "properties": {
      "path": { "type": "string", "description": "Directory path" }
    },
    "required": ["path"]
  }
}
```

---

### exec

```json
{
  "name": "exec",
  "parameters": {
    "properties": {
      "command":     { "type": "string" },
      "working_dir": { "type": "string" },
      "timeout":     { "type": "integer", "description": "Seconds, max 600, default 60" }
    },
    "required": ["command"]
  }
}
```

**安全拦截：** `rm -rf`、`dd of=`、fork bomb 等模式会被拒绝执行。
**输出：** 最多 10,000 字符；超时后返回已有输出 + 超时提示。

---

### web_search

```json
{
  "name": "web_search",
  "parameters": {
    "properties": {
      "query": { "type": "string" },
      "count": { "type": "integer", "minimum": 1, "maximum": 10, "default": 5 }
    },
    "required": ["query"]
  }
}
```

**Provider 配置：** `config.tools.web.provider`（brave/tavily/duckduckgo/searxng/jina）。
**结果格式：** `Title\nURL\nSnippet` 每条用 `---` 分隔，附安全警告横幅。

---

### web_fetch

```json
{
  "name": "web_fetch",
  "parameters": {
    "properties": {
      "url": { "type": "string" }
    },
    "required": ["url"]
  }
}
```

**行为：** HTML → Markdown 转换；图片自动 base64；最多 5 次重定向；SSRF 防护。

---

### message

```json
{
  "name": "message",
  "parameters": {
    "properties": {
      "content":  { "type": "string" },
      "channel":  { "type": "string", "description": "Defaults to current channel" },
      "chat_id":  { "type": "string", "description": "Defaults to current chat" },
      "media":    { "type": "array", "items": { "type": "string" }, "description": "File paths" }
    },
    "required": ["content"]
  }
}
```

**注意：** 需在 `AgentLoop._process_message()` 中调用 `tool.set_context(channel, chat_id)` 才能正确路由。

---

### spawn

```json
{
  "name": "spawn",
  "parameters": {
    "properties": {
      "task":  { "type": "string", "description": "Task description for subagent" },
      "label": { "type": "string", "description": "Display label" }
    },
    "required": ["task"]
  }
}
```

**行为：** 立即返回 ACK，后台异步运行（最多 15 次迭代）。完成后通过 system message 汇报。

---

### cron

```json
{
  "name": "cron",
  "parameters": {
    "properties": {
      "action":         { "type": "string", "enum": ["add", "list", "remove"] },
      "task":           { "type": "string" },
      "cron_expr":      { "type": "string", "description": "e.g. '0 9 * * *'" },
      "at":             { "type": "string", "description": "ISO datetime for one-time" },
      "every_seconds":  { "type": "integer" },
      "timezone":       { "type": "string", "default": "UTC" },
      "job_id":         { "type": "string", "description": "For remove action" }
    },
    "required": ["action"]
  }
}
```

---

### MCP 工具

命名格式：`mcp_{server_name}_{tool_name}`

JSON Schema 从 MCP server 自动获取，经 `MCPToolWrapper._normalize_schema()` 规范化（处理 nullable 类型、移除 OpenAI 不支持的关键字）。

---

## 2. LLMProvider API

### 核心 chat 接口

```python
async def chat(
    messages: list[dict],
    tools: list[dict] | None = None,
    model: str | None = None,
    max_tokens: int = 4096,
    temperature: float = 0.7,
    reasoning_effort: str | None = None,    # "low" | "medium" | "high" | "max"
    tool_choice: str | dict | None = None,  # "auto" | "required" | {"type": "function", "function": {"name": "..."}}
) -> LLMResponse
```

### LLMResponse 字段

```python
@dataclass
class LLMResponse:
    content: str | None                      # 文本响应（无工具调用时）
    tool_calls: list[ToolCallRequest]        # 工具调用列表
    finish_reason: str                       # "stop" | "tool_calls" | "error" | "length"
    usage: dict                              # {"prompt_tokens": int, "completion_tokens": int}
    reasoning_content: str | None            # CoT 内容（DeepSeek-R1、Kimi）
    thinking_blocks: list[dict] | None       # Anthropic extended thinking 块
```

### 流式 chat 接口

```python
async def chat_stream(
    messages: list[dict],
    tools: list[dict] | None = None,
    model: str | None = None,
    max_tokens: int = 4096,
    temperature: float = 0.7,
    reasoning_effort: str | None = None,
    on_content_delta: Callable[[str], Awaitable[None]] | None = None,
) -> LLMResponse
```

回调 `on_content_delta(chunk)` 在每个内容片段到达时调用。

### 重试接口

```python
async def chat_with_retry(...) -> LLMResponse
async def chat_stream_with_retry(...) -> LLMResponse
```

重试策略：(1, 2, 4) 秒指数退避，仅 transient 错误重试（429、503、timeout、"overloaded" 等）。

---

## 3. BaseChannel API

```python
class BaseChannel:
    name: str           # 渠道标识符（如 "telegram"）
    display_name: str   # 显示名称

    # 必须实现
    async def start(self) -> None
    async def stop(self) -> None
    async def send(self, msg: OutboundMessage) -> None

    # 可选实现
    async def login(self, force: bool = False) -> bool
    async def send_delta(self, chat_id: str, delta: str, metadata: dict) -> None

    # 工具方法（无需重写）
    async def _handle_message(self, ...) -> None   # 统一入口
    def is_allowed(self, sender_id: str) -> bool   # 权限检查
    async def transcribe_audio(self, file_path: str) -> str  # Whisper 转写
```

### 创建自定义渠道示例

```python
from nanobot.channels.base import BaseChannel
from nanobot.bus.events import InboundMessage, OutboundMessage

class MyChannel(BaseChannel):
    name = "my_channel"
    display_name = "My Channel"

    async def start(self):
        self._running = True
        while self._running:
            # 监听消息...
            raw = await self._receive()
            await self._handle_message(
                sender_id=raw["user"],
                chat_id=raw["room"],
                content=raw["text"],
            )

    async def stop(self):
        self._running = False

    async def send(self, msg: OutboundMessage):
        await self._client.send(msg.chat_id, msg.content)

    # 可选：流式支持
    async def send_delta(self, chat_id: str, delta: str, metadata: dict):
        await self._client.append(chat_id, delta)
```

---

## 4. 配置参考

### 完整 config.json 结构

```json
{
  "agent": {
    "workspace": "~/.nanobot/workspace",
    "model": "anthropic/claude-opus-4-5",
    "provider": "auto",
    "maxTokens": 8192,
    "contextWindowTokens": 65536,
    "temperature": 0.1,
    "maxToolIterations": 40,
    "reasoningEffort": null
  },
  "channels": {
    "sendProgress": true,
    "sendToolHints": false,
    "telegram": {
      "token": "...",
      "allowFrom": ["123456789"],
      "streaming": true
    },
    "feishu": {
      "appId": "...",
      "appSecret": "...",
      "verifyToken": "..."
    }
  },
  "providers": {
    "anthropic":  { "apiKey": "sk-ant-..." },
    "openai":     { "apiKey": "sk-..." },
    "deepseek":   { "apiKey": "..." },
    "custom":     { "apiBase": "http://localhost:8000/v1", "apiKey": "..." },
    "azureOpenai": {
      "apiKey": "...",
      "apiBase": "https://xxx.openai.azure.com/",
      "extraHeaders": { "api-version": "2024-02-15-preview" }
    }
  },
  "tools": {
    "restrictToWorkspace": false,
    "exec": {
      "enable": true,
      "timeout": 60,
      "pathAppend": "/usr/local/bin"
    },
    "web": {
      "provider": "duckduckgo",
      "apiKey": "",
      "maxResults": 5
    },
    "mcpServers": {
      "filesystem": {
        "type": "stdio",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
        "toolTimeout": 30,
        "enabledTools": ["*"]
      },
      "my_api": {
        "type": "streamableHttp",
        "url": "http://localhost:3000/mcp",
        "headers": { "Authorization": "Bearer ..." }
      }
    }
  }
}
```

### 环境变量覆盖

使用 `NANOBOT_` 前缀，`__` 代替层级分隔：

```bash
NANOBOT_AGENT__MODEL="openai/gpt-4o"
NANOBOT_AGENT__MAX_TOKENS=16384
NANOBOT_PROVIDERS__ANTHROPIC__API_KEY="sk-ant-..."
NANOBOT_TOOLS__EXEC__ENABLE=false
NANOBOT_MAX_CONCURRENT_REQUESTS=3   # 全局并发上限
```

---

## 5. Session API（内部）

```python
class SessionManager:
    async def get_or_create(self, key: str) -> Session
    async def save(self, session: Session) -> None
    async def invalidate(self, key: str) -> None
    async def list_sessions(self) -> list[str]

class Session:
    key: str
    messages: list[dict]        # append-only
    last_consolidated: int

    def get_history(self, max_messages: int = 500) -> list[dict]
    def clear(self) -> None
    def retain_recent_legal_suffix(self, max_messages: int) -> None
```

---

## 6. 技能（Skill）格式

```markdown
---
name: my-skill
description: 一句话描述（agent 根据此判断何时调用）
version: "1.0"
always_active: false    # true = 始终加载到系统提示词（全局生效）
requires:               # 可用性检查
  commands: ["gh"]      # 需要这些命令存在
  env: ["GITHUB_TOKEN"] # 需要这些环境变量
---

# My Skill

## 何时使用
...

## 指令
...

## 示例
```

技能文件位置：`{workspace}/skills/{name}/SKILL.md`（覆盖同名内置）或内置路径 `nanobot/skills/{name}/SKILL.md`。

---

## 7. 内置命令

| 命令 | 优先级 | 功能 |
|------|--------|------|
| `/stop` | 高（锁外） | 取消当前 session 所有任务和子 agent |
| `/restart` | 高（锁外） | `os.execv()` 重启进程 |
| `/new` | 普通 | 清空当前 session，保留压缩的历史 |
| `/status` | 普通 | 显示模型、版本、uptime、token 使用量 |
| `/help` | 普通 | 列出所有可用命令 |
