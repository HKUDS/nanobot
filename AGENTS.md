# nanobot - AI 编码助手指南

本文档为在 nanobot 项目上工作的 AI 编码助手提供重要信息。

## 项目概述

**nanobot** 是一个受 OpenClaw 启发的超轻量级个人 AI 助手框架。它在代码量减少 99% 的同时，保持了核心智能体功能，并具备良好的可扩展性，适用于研发场景。

- **版本**: 0.1.4.post4
- **Python**: >= 3.11
- **许可证**: MIT
- **包名**: `nanobot-ai` (PyPI)

## 技术栈

### 核心依赖
- **LLM 集成**: `litellm`（多提供商统一接口）
- **配置管理**: `pydantic` + `pydantic-settings`（带验证的 JSON 配置）
- **CLI 框架**: `typer`（命令行界面）
- **异步运行时**: `asyncio` + `websockets`（网关和通道）
- **网页抓取**: `readability-lxml`, `httpx`, `ddgs`（DuckDuckGo 搜索）
- **日志记录**: `loguru`（结构化日志）
- **输出格式化**: `rich`（终端 Markdown 渲染）

### 可选依赖
- **Matrix**: `matrix-nio[e2e]`（端到端加密支持）
- **企业微信**: `wecom-aibot-sdk-python`（企业微信）
- **开发工具**: `pytest`, `pytest-asyncio`, `ruff`

### 桥接技术（WhatsApp）
- **Node.js**: >= 20
- **TypeScript**: 使用 Baileys 库的 WhatsApp 桥接
- **WebSocket**: Python 与 Node.js 桥接之间的本地通信

## 架构

```
┌─────────────────────────────────────────────────────────────┐
│                      nanobot 架构                            │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌──────────┐    ┌──────────┐    ┌──────────────────────┐  │
│  │  CLI     │    │  通道    │    │  智能体循环          │  │
│  │  层      │◄──►│ (聊天    │◄──►│  (核心引擎)          │  │
│  │          │    │  平台)   │    │                      │  │
│  └──────────┘    └──────────┘    └──────────┬───────────┘  │
│         │                                    │              │
│         ▼                                    ▼              │
│  ┌──────────┐    ┌──────────┐    ┌──────────────────────┐  │
│  │  配置    │    │  消息    │    │  工具                │  │
│  │  (JSON)  │    │  总线    │    │  (文件、Shell、Web)  │  │
│  └──────────┘    └──────────┘    └──────────────────────┘  │
│                                                              │
│  ┌──────────┐    ┌──────────┐    ┌──────────────────────┐  │
│  │ 提供商   │    │  技能    │    │  MCP (外部)          │  │
│  │ (LLM)    │    │ (智能体  │    │  工具服务器          │  │
│  │          │    │  记忆)   │    │                      │  │
│  └──────────┘    └──────────┘    └──────────────────────┘  │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

## 模块组织

```
nanobot/
├── __init__.py           # 包版本和 Logo
├── agent/                # 核心智能体实现
│   ├── loop.py           # AgentLoop - 主处理引擎
│   ├── context.py        # ContextBuilder - 提示词构建
│   ├── memory.py         # MemoryConsolidator - 会话管理
│   ├── skills.py         # 技能加载和管理
│   ├── subagent.py       # 后台任务执行
│   └── tools/            # 内置工具
│       ├── base.py       # 工具基类
│       ├── registry.py   # 工具注册表
│       ├── filesystem.py # 文件操作（读/写/编辑/列表）
│       ├── shell.py      # Shell 命令执行
│       ├── web.py        # 网页搜索和获取
│       ├── spawn.py      # 子智能体创建
│       ├── message.py    # 通道消息
│       ├── cron.py       # 定时任务
│       └── mcp.py        # MCP 服务器集成
├── bus/                  # 消息总线系统
│   ├── events.py         # InboundMessage, OutboundMessage
│   └── queue.py          # MessageBus - 异步消息路由
├── channels/             # 聊天平台集成（基于插件）
│   ├── base.py           # BaseChannel 抽象类
│   ├── registry.py       # 通道发现（内置 + 插件）
│   ├── manager.py        # 通道生命周期管理
│   ├── telegram.py       # Telegram 机器人
│   ├── discord.py        # Discord 机器人
│   ├── whatsapp.py       # WhatsApp（通过 Node.js 桥接）
│   ├── feishu.py         # 飞书/Lark
│   ├── dingtalk.py       # 钉钉
│   ├── slack.py          # Slack
│   ├── email.py          # 邮件（IMAP/SMTP）
│   ├── qq.py             # QQ 机器人
│   ├── matrix.py         # Matrix/Element
│   ├── wecom.py          # 企业微信
│   └── mochat.py         # MoChat (Claw IM)
├── cli/                  # 命令行界面
│   └── commands.py       # 所有 CLI 命令（agent、gateway、status）
├── config/               # 配置管理
│   ├── schema.py         # 配置的 Pydantic 模型验证
│   ├── loader.py         # 配置加载/保存
│   └── paths.py          # 路径解析工具
├── cron/                 # 定时任务系统
│   ├── service.py        # CronService 实现
│   └── types.py          # 定时任务类型定义
├── heartbeat/            # 主动式周期性任务
│   └── service.py        # HeartbeatService 用于 HEARTBEAT.md 任务
├── providers/            # LLM 提供商集成
│   ├── base.py           # LLMProvider 抽象类
│   ├── registry.py       # ProviderSpec 注册表（单一事实来源）
│   ├── litellm_provider.py # 基于 LiteLLM 的提供商
│   ├── custom_provider.py  # 直接 OpenAI 兼容端点
│   ├── azure_openai_provider.py # Azure OpenAI 直连
│   ├── openai_codex_provider.py # OpenAI Codex OAuth
│   └── transcription.py  # Groq Whisper 语音转文字
├── session/              # 对话会话管理
│   └── manager.py        # 会话持久化和检索
├── skills/               # 捆绑的智能体技能（Markdown 文档）
│   ├── clawhub/          # ClawHub 技能搜索
│   ├── cron/             # Cron 任务管理
│   ├── github/           # GitHub 操作
│   ├── memory/           # 记忆管理
│   ├── skill-creator/    # 技能开发工具
│   ├── summarize/        # 文本摘要
│   ├── tmux/             # 终端复用器控制
│   └── weather/          # 天气查询
└── templates/            # 工作区模板
    └── memory/           # 默认 MEMORY.md 模板
```

## 配置系统

### 配置位置
- **默认**: `~/.nanobot/config.json`
- **自定义**: 使用 `--config /path/to/config.json`

### 配置模式 (config/schema.py)

```json
{
  "agents": {
    "defaults": {
      "workspace": "~/.nanobot/workspace",
      "model": "anthropic/claude-opus-4-5",
      "provider": "auto",
      "maxTokens": 8192,
      "contextWindowTokens": 65536,
      "temperature": 0.1,
      "maxToolIterations": 40,
      "reasoningEffort": null
    }
  },
  "channels": {
    "telegram": {
      "enabled": true,
      "token": "...",
      "allowFrom": ["user_id"]
    }
  },
  "providers": {
    "openrouter": {
      "apiKey": "sk-or-...",
      "apiBase": "",
      "extraHeaders": {}
    }
  },
  "gateway": {
    "host": "0.0.0.0",
    "port": 18790,
    "heartbeat": {
      "enabled": true,
      "intervalS": 1800
    }
  },
  "tools": {
    "web": {
      "proxy": "",
      "search": {
        "provider": "brave",
        "apiKey": "",
        "maxResults": 5
      }
    },
    "exec": {
      "timeout": 60,
      "pathAppend": ""
    },
    "restrictToWorkspace": false,
    "mcpServers": {}
  }
}
```

### 支持的 LLM 提供商 (providers/registry.py)

| 提供商 | 类型 | 检测方式 |
|----------|------|-----------|
| `openrouter` | 网关 | API key 前缀 `sk-or-` |
| `anthropic` | 标准 | 模型名包含 "claude" |
| `openai` | 标准 | 模型名包含 "gpt" |
| `deepseek` | 标准 | 模型名包含 "deepseek" |
| `gemini` | 标准 | 模型名包含 "gemini" |
| `moonshot` | 标准 | 模型名包含 "moonshot"/"kimi" |
| `dashscope` | 标准 | 模型名包含 "qwen" |
| `zhipu` | 标准 | 模型名包含 "glm"/"zhipu" |
| `ollama` | 本地 | 配置键或 api_base 包含 "11434" |
| `vllm` | 本地 | 配置键 |
| `custom` | 直连 | 显式选择，绕过 LiteLLM |

## 构建和开发

### 设置（开发环境）
```bash
# 克隆并以可编辑模式安装
git clone https://github.com/HKUDS/nanobot.git
cd nanobot
pip install -e .

# 或安装所有可选依赖
pip install -e ".[matrix,wecom,dev]"
```

### 构建命令
```bash
# 安装依赖
pip install -e .

# 构建 WhatsApp 桥接（需要 Node.js >= 20）
cd bridge && npm install && npm run build

# 打包分发
python -m build
```

### CLI 命令

| 命令 | 描述 |
|---------|-------------|
| `nanobot onboard` | 初始化配置和工作区 |
| `nanobot agent` | 交互式 CLI 聊天模式 |
| `nanobot agent -m "..."` | 单条消息模式 |
| `nanobot gateway` | 启动网关（通道 + 智能体） |
| `nanobot status` | 显示配置状态 |
| `nanobot channels login` | 绑定 WhatsApp（扫码） |
| `nanobot channels status` | 列出已启用的通道 |
| `nanobot plugins list` | 显示所有通道（内置 + 插件） |
| `nanobot provider login openai-codex` | 提供商 OAuth 登录 |

### 多实例运行

支持同时运行多个机器人：

```bash
# 实例 A - Telegram
nanobot gateway --config ~/.nanobot-telegram/config.json

# 实例 B - Discord
nanobot gateway --config ~/.nanobot-discord/config.json
```

使用 `--config` 时的路径解析：
- 配置: 来自 `--config` 路径
- 工作区: 来自配置或 `--workspace` 覆盖
- 定时任务: `{config_dir}/cron/`
- 媒体/状态: `{config_dir}/media/`

## 测试

### 测试框架
- **框架**: pytest + pytest-asyncio
- **位置**: `tests/`
- **异步模式**: 自动（在 pyproject.toml 中配置）

### 运行测试
```bash
# 运行所有测试
pytest

# 详细输出
pytest -v

# 运行特定测试文件
pytest tests/test_filesystem_tools.py

# 带覆盖率运行
pytest --cov=nanobot
```

### 测试结构
- `test_*_channel.py` - 通道特定测试
- `test_*_tools.py` - 工具功能测试
- `test_*_provider.py` - 提供商测试
- `test_config_*.py` - 配置测试
- `test_loop_*.py` - 智能体循环测试

### 关键测试领域
1. **通道测试**: Telegram, Discord, 飞书, Slack, 邮件, QQ, Matrix, 钉钉
2. **工具测试**: 文件系统, Shell, 网页搜索, MCP 集成
3. **提供商测试**: Azure OpenAI, LiteLLM 参数, 重试逻辑
4. **集成测试**: CLI 输入, 消息处理, 心跳服务

## 代码风格指南

### 代码检查/格式化工具
- **工具**: Ruff
- **配置**: pyproject.toml

```toml
[tool.ruff]
line-length = 100
target-version = "py311"

[tool.ruff.lint]
select = ["E", "F", "I", "N", "W"]
ignore = ["E501"]
```

### 风格规则
- **行长度**: 最多 100 个字符
- **Python 版本**: 3.11+
- **导入**: 排序（由 Ruff 处理）
- **命名**: 符合 PEP 8
- **文档字符串**: Google 风格（整个代码库使用）

### 运行代码检查
```bash
# 检查代码
ruff check nanobot/

# 修复可自动修复的问题
ruff check --fix nanobot/

# 格式化代码
ruff format nanobot/
```

## 安全注意事项

### 访问控制
- **`allowFrom` 列表**: 生产环境所有通道必需
- **空 `allowFrom`**: 默认拒绝所有访问（自 v0.1.4.post4 起）
- **通配符**: 使用 `["*"]` 显式允许所有用户

### 文件系统安全
- **`restrictToWorkspace`**: 为 `true` 时，所有文件操作限制在工作区内
- **路径遍历**: 内置对 `../` 攻击的防护
- **阻止的命令**: Shell 工具阻止危险模式（`rm -rf /`、fork 炸弹等）

### API 密钥安全
- 存储在 `~/.nanobot/config.json`，权限为 `0600`
- 永远不要将 API 密钥提交到版本控制
- 使用环境变量作为后备
- 生产环境考虑使用操作系统密钥环

### 网络安全
- 所有外部 API 调用使用 HTTPS
- WhatsApp 桥接绑定到 `127.0.0.1:3001`（仅本地）
- 可选的 `bridgeToken` 用于桥接认证
- 网页工具可配置 HTTP/SOCKS5 代理

### 生产环境安全检查清单
- [ ] 所有通道配置 `allowFrom`
- [ ] 配置中设置 `restrictToWorkspace: true`
- [ ] 配置文件权限设置为 0600
- [ ] 以非 root 用户运行
- [ ] WhatsApp 认证目录权限 0700
- [ ] 依赖项已更新（运行 `pip-audit`）
- [ ] API 提供商配置了速率限制

## 部署

### Docker
```bash
# 构建
docker build -t nanobot .

# 运行网关
docker run -v ~/.nanobot:/root/.nanobot -p 18790:18790 nanobot gateway

# 运行 CLI 命令
docker run -v ~/.nanobot:/root/.nanobot --rm nanobot agent -m "Hello!"
```

### Docker Compose
```bash
# 设置
docker compose run --rm nanobot-cli onboard

# 启动网关
docker compose up -d nanobot-gateway

# 查看日志
docker compose logs -f nanobot-gateway
```

### Linux 服务（systemd）
```ini
# ~/.config/systemd/user/nanobot-gateway.service
[Unit]
Description=Nanobot Gateway
After=network.target

[Service]
Type=simple
ExecStart=%h/.local/bin/nanobot gateway
Restart=always
RestartSec=10
NoNewPrivileges=yes

[Install]
WantedBy=default.target
```

启用并启动：
```bash
systemctl --user daemon-reload
systemctl --user enable --now nanobot-gateway
```

## 通道插件开发

### 创建自定义通道

1. **继承 BaseChannel**：
```python
from nanobot.channels.base import BaseChannel
from nanobot.bus.events import OutboundMessage

class MyChannel(BaseChannel):
    name = "mychannel"
    display_name = "My Channel"
    
    @classmethod
    def default_config(cls) -> dict:
        return {"enabled": False, "token": "", "allowFrom": []}
    
    async def start(self) -> None:
        """必须阻塞直到 stop() 被调用。"""
        self._running = True
        # 连接平台并监听
        while self._running:
            await asyncio.sleep(1)
    
    async def stop(self) -> None:
        self._running = False
    
    async def send(self, msg: OutboundMessage) -> None:
        """将消息发送到平台。"""
        pass
```

2. **注册入口点**（在 `pyproject.toml` 中）：
```toml
[project.entry-points."nanobot.channels"]
mychannel = "my_package:MyChannel"
```

3. **安装和测试**：
```bash
pip install -e .
nanobot plugins list  # 验证通道出现
nanobot onboard       # 自动添加默认配置
```

## MCP（模型上下文协议）集成

MCP 支持连接外部工具服务器。配置示例：

```json
{
  "tools": {
    "mcpServers": {
      "filesystem": {
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-filesystem", "/path/to/dir"]
      },
      "remote-server": {
        "url": "https://example.com/mcp/",
        "headers": {"Authorization": "Bearer token"},
        "toolTimeout": 60
      }
    }
  }
}
```

传输模式：
- **Stdio**: `command` + `args`（本地进程）
- **HTTP/SSE**: `url` + 可选 `headers`（远程端点）

## 关键架构模式

### 1. 提供商注册表模式
所有 LLM 提供商在 `providers/registry.py` 中定义为 `ProviderSpec` 数据类。这是以下内容的单一事实来源：
- 环境变量名称
- 模型名前缀规则
- 自动检测逻辑（通过键前缀或 base URL）

添加新提供商只需 2 步：
1. 将 `ProviderSpec` 添加到 `PROVIDERS` 元组
2. 在 `config/schema.py` 的 `ProvidersConfig` 中添加字段

### 2. 工具注册表模式
工具在 `AgentLoop._register_default_tools()` 中注册并存储在 `ToolRegistry` 中。每个工具：
- 继承自 `BaseTool`
- 为 LLM 定义 JSON 模式
- 实现 `async execute(**kwargs)` 方法

### 3. 消息总线模式
所有通信通过 `MessageBus` 流动：
- **入站**: 通道 → 总线 → AgentLoop
- **出站**: AgentLoop → 总线 → 通道

这将通道与智能体逻辑解耦。

### 4. 会话管理
- 会话以 `{channel}:{chat_id}` 为键
- 持久化到 `{workspace}/sessions/`
- 当接近 token 限制时自动进行记忆整合

### 5. 配置优先设计
所有行为由 `~/.nanobot/config.json` 驱动：
- 无硬编码 API 密钥
- 无硬编码路径
- 所有内容可通过 CLI 标志覆盖

## 常见开发任务

### 添加新工具
1. 在 `nanobot/agent/tools/` 中创建类
2. 继承自 `BaseTool`
3. 定义 `name`、`description`、`parameters` 模式
4. 实现 `async execute()` 方法
5. 在 `AgentLoop._register_default_tools()` 中注册

### 添加新通道
1. 在 `nanobot/channels/` 中创建文件
2. 继承自 `BaseChannel`
3. 实现 `start()`、`stop()`、`send()`
4. 接收消息时调用 `_handle_message()`
5. 添加到 `nanobot/channels/registry.py`（或使用入口点作为插件）

### 添加新提供商
1. 将 `ProviderSpec` 添加到 `providers/registry.py`
2. 在 `config/schema.py` 的 `ProvidersConfig` 中添加字段
3. 用 `nanobot status` 测试

## 重要文件

| 文件 | 用途 |
|------|---------|
| `nanobot/agent/loop.py` | 核心智能体引擎 - 主处理逻辑 |
| `nanobot/config/schema.py` | Pydantic 模型 - 配置验证 |
| `nanobot/providers/registry.py` | 提供商元数据 - 单一事实来源 |
| `nanobot/channels/base.py` | 抽象通道接口 |
| `nanobot/bus/queue.py` | 消息路由系统 |
| `pyproject.toml` | 包元数据、依赖、工具配置 |
| `README.md` | 用户文档 |
| `SECURITY.md` | 安全策略和最佳实践 |
