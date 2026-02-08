# nanobot 技术文档

## 概述
nanobot 是一个基于 Python 的轻量级个人 AI 助手框架，采用模块化设计，核心代码约 4,000 行。框架支持多种 LLM 提供商、工具调用、多通道通信和持久化内存。

## 系统架构

### 高层架构图
```
+-------------------+     +-------------------+     +-------------------+
|  通信通道         |     |  消息总线         |     |  智能体循环       |
|  (Telegram,       |---->|  (MessageBus)     |---->|  (AgentLoop)      |
|   Discord, etc.)  |     |                   |     |                   |
+-------------------+     +-------------------+     +-------------------+
                                                           |
                                                           v
+-------------------+     +-------------------+     +-------------------+
|  工具系统         |<----|  上下文构建器     |<----|  会话管理器       |
|  (ToolRegistry)   |     |  (ContextBuilder) |     |  (SessionManager) |
+-------------------+     +-------------------+     +-------------------+
         |                       |                       |
         v                       v                       v
+-------------------+     +-------------------+     +-------------------+
|  文件/Shell/Web   |     |  内存系统         |     |  持久化存储       |
|  工具实现         |     |  (MemoryStore)    |     |  (JSON/文件)      |
+-------------------+     +-------------------+     +-------------------+
```

### 数据流
1. **消息接收**：通道管理器（ChannelManager）接收用户消息，转换为 `InboundMessage` 事件发布到消息总线。
2. **消息处理**：AgentLoop 从总线消费消息，通过 ContextBuilder 构建对话上下文，调用 LLM 获取响应。
3. **工具执行**：如果 LLM 返回工具调用请求，ToolRegistry 执行相应工具，结果通过上下文返回给 LLM。
4. **响应发送**：最终的文本响应封装为 `OutboundMessage` 发布到总线，通道管理器将其发送回用户。
5. **状态持久化**：会话历史、记忆、定时任务等状态定期保存到文件系统。

## 核心模块详解

### 1. 智能体循环 (agent/loop.py)
**职责**：处理消息的核心引擎，协调 LLM 调用、工具执行和响应生成。

**关键类**：
- `AgentLoop`：主循环类
  - `__init__()`：初始化工具注册表、会话管理器、子代理管理器
  - `run()`：启动事件循环，持续从总线消费消息
  - `_process_message()`：处理单条消息的完整流程

**工作流程**：
```python
async def _process_message(self, msg):
    # 1. 获取或创建会话
    session = self.sessions.get_or_create(msg.session_key)
    
    # 2. 构建消息列表（包含系统提示、历史、当前消息）
    messages = self.context.build_messages(
        history=session.get_history(),
        current_message=msg.content,
        channel=msg.channel,
        chat_id=msg.chat_id
    )
    
    # 3. LLM 调用循环（最多 max_iterations 次）
    iteration = 0
    while iteration < self.max_iterations:
        # 调用 LLM
        response = await self.provider.chat(
            messages=messages,
            tools=self.tools.get_definitions(),
            model=self.model
        )
        
        if response.has_tool_calls:
            # 执行工具调用
            for tool_call in response.tool_calls:
                result = await self.tools.execute(tool_call.name, tool_call.arguments)
                # 将结果添加到消息列表
                messages = self.context.add_tool_result(
                    messages, tool_call.id, tool_call.name, result
                )
        else:
            # 无工具调用，生成最终响应
            final_content = response.content
            break
    
    # 4. 保存会话历史
    session.add_message("user", msg.content)
    session.add_message("assistant", final_content)
    self.sessions.save(session)
    
    # 5. 返回响应
    return OutboundMessage(
        channel=msg.channel,
        chat_id=msg.chat_id,
        content=final_content
    )
```

### 2. 工具系统 (agent/tools/)
**职责**：提供一组可执行的操作，供 LLM 调用来完成实际任务。

**工具注册表 (ToolRegistry)**：
- 管理所有可用工具的注册和查找
- 提供工具定义（符合 OpenAI 工具调用格式）
- 处理工具执行和错误处理

**内置工具**：
| 工具类 | 功能 | 安全限制 |
|--------|------|----------|
| `ReadFileTool` | 读取文件内容 | 可限制到工作空间目录 |
| `WriteFileTool` | 写入文件 | 可限制到工作空间目录 |
| `EditFileTool` | 编辑文件（查找替换） | 可限制到工作空间目录 |
| `ListDirTool` | 列出目录内容 | 可限制到工作空间目录 |
| `ExecTool` | 执行 Shell 命令 | 可限制工作目录，超时控制 |
| `WebSearchTool` | 网页搜索（Brave Search API） | 需要 API 密钥 |
| `WebFetchTool` | 抓取网页内容 | 遵循 robots.txt |
| `MessageTool` | 发送消息到通信通道 | 需要通道上下文 |
| `SpawnTool` | 创建子代理执行后台任务 | 继承父代理权限 |
| `CronTool` | 管理定时任务 | 需要 CronService |

**工具定义示例**：
```python
{
    "type": "function",
    "function": {
        "name": "read_file",
        "description": "Read the contents of a file",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the file (relative to workspace if restrict_to_workspace is enabled)"
                }
            },
            "required": ["path"]
        }
    }
}
```

### 3. 上下文构建器 (agent/context.py)
**职责**：构建系统提示和消息列表，为 LLM 提供完整的对话上下文。

**关键组件**：
- **引导文件**：`AGENTS.md`, `SOUL.md`, `USER.md`, `TOOLS.md`, `IDENTITY.md`
- **内存上下文**：长期记忆 + 今日笔记
- **技能摘要**：可用技能的描述和状态
- **会话信息**：当前通道和聊天 ID

**系统提示结构**：
```
# nanobot 🐈
[核心身份描述]

# 引导文件
[AGENTS.md 内容]
[SOUL.md 内容]
...

# 内存
[长期记忆]
[今日笔记]

# 技能
[技能摘要]

# 当前会话
Channel: telegram
Chat ID: 123456789
```

### 4. 内存系统 (agent/memory.py)
**职责**：管理持久化记忆，包括每日笔记和长期记忆。

**文件结构**：
```
workspace/
├── memory/
│   ├── MEMORY.md          # 长期记忆
│   ├── 2026-02-08.md      # 今日笔记
│   ├── 2026-02-07.md      # 昨日笔记
│   └── ...
```

**API**：
- `read_today()`：读取今日笔记
- `append_today(content)`：追加内容到今日笔记
- `read_long_term()`：读取长期记忆
- `write_long_term(content)`：写入长期记忆
- `get_recent_memories(days=7)`：获取最近 N 天的记忆

### 5. 会话管理 (session/manager.py)
**职责**：管理对话历史，支持多会话隔离。

**会话标识**：`{channel}:{chat_id}`（如 `telegram:123456789`）

**存储格式**：JSON 文件，每个会话单独存储
```json
{
    "session_key": "telegram:123456789",
    "messages": [
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi there!"}
    ],
    "created_at": "2026-02-08T10:30:00",
    "updated_at": "2026-02-08T10:31:00"
}
```

### 6. 消息总线 (bus/)
**职责**：提供发布-订阅机制，解耦各组件通信。

**关键类**：
- `MessageBus`：基于 asyncio.Queue 的简单实现
- `InboundMessage`：入站消息事件
- `OutboundMessage`：出站消息事件

**事件类型**：
```python
@dataclass
class InboundMessage:
    channel: str          # 来源通道：telegram, discord, cli 等
    sender_id: str        # 发送者 ID
    chat_id: str          # 聊天/用户 ID
    content: str          # 消息内容
    media: list[str] | None = None  # 媒体文件路径
    
@dataclass  
class OutboundMessage:
    channel: str          # 目标通道
    chat_id: str          # 目标聊天 ID
    content: str          # 响应内容
```

### 7. 通道管理 (channels/)
**职责**：集成外部通信平台，处理消息收发。

**支持通道**：
- **Telegram**：使用 `python-telegram-bot` 库
- **Discord**：使用 Discord Bot API
- **WhatsApp**：通过 Node.js 桥接（`bridge/` 目录）
- **飞书**：使用 Lark OpenAPI WebSocket 连接

**通道配置**：
```json
{
    "channels": {
        "telegram": {
            "enabled": true,
            "token": "YOUR_BOT_TOKEN",
            "allowFrom": ["USER_ID_1", "USER_ID_2"]
        },
        "whatsapp": {
            "enabled": true,
            "bridge_url": "http://localhost:18790/whatsapp",
            "allowFrom": ["+1234567890"]
        }
    }
}
```

### 8. LLM 提供商 (providers/)
**职责**：抽象不同 LLM API 的接口，提供统一的调用方式。

**支持提供商**：
- OpenRouter（推荐，支持多种模型）
- Anthropic（Claude 直接访问）
- OpenAI（GPT 直接访问）
- DeepSeek
- Groq（附带 Whisper 语音转录）
- Gemini
- AiHubMix（API 网关）
- vLLM（本地模型）

**提供商接口**：
```python
class LLMProvider(ABC):
    @abstractmethod
    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None
    ) -> LLMResponse:
        pass
```

### 9. 定时任务 (cron/)
**职责**：基于 Cron 表达式或固定间隔执行任务。

**存储**：`~/.nanobot/cron/jobs.json`
**调度器**：使用 `croniter` 库解析 Cron 表达式

**任务类型**：
- **周期性**：每 N 秒执行
- **Cron 表达式**：如 `0 9 * * *`（每天上午9点）
- **一次性**：在指定时间执行一次

### 10. 心跳服务 (heartbeat/)
**职责**：定期唤醒智能体，执行主动任务（如提醒、状态检查）。

**默认间隔**：30分钟
**触发逻辑**：检查工作空间中的 `HEARTBEAT.md` 文件，执行其中定义的任务

## 配置系统

### 配置文件位置
- 主配置：`~/.nanobot/config.json`
- 数据目录：`~/.nanobot/`（存储会话、记忆、定时任务等）

### 配置结构
```json
{
    "workspace": "/path/to/workspace",
    "providers": {
        "openrouter": {
            "apiKey": "sk-or-v1-xxx",
            "apiBase": "https://openrouter.ai/api/v1"
        }
    },
    "agents": {
        "defaults": {
            "model": "anthropic/claude-opus-4-5",
            "max_tool_iterations": 20
        }
    },
    "tools": {
        "web": {
            "search": {
                "api_key": "brave_api_key_xxx"
            }
        },
        "exec": {
            "timeout": 30,
            "working_dir": "/workspace"
        },
        "restrict_to_workspace": false
    },
    "channels": {
        "telegram": {
            "enabled": true,
            "token": "bot_token_xxx",
            "allowFrom": ["user_id_1"]
        },
        "discord": {
            "enabled": false,
            "token": "",
            "gateway_url": "ws://localhost:18790/discord"
        },
        "whatsapp": {
            "enabled": true,
            "bridge_url": "http://localhost:18790/whatsapp",
            "allowFrom": ["+1234567890"]
        },
        "feishu": {
            "enabled": false,
            "appId": "",
            "appSecret": ""
        }
    }
}
```

### 配置加载流程
1. `config/loader.py` 中的 `load_config()` 读取配置文件
2. 使用 Pydantic 模型 `Config` 验证和解析
3. 应用默认值（未设置的字段使用 schema 中定义的默认值）
4. 返回配置对象供各模块使用

## API 接口

### CLI 命令
| 命令 | 功能 | 示例 |
|------|------|------|
| `nanobot onboard` | 初始化配置和工作空间 | `nanobot onboard` |
| `nanobot agent -m "消息"` | 发送单条消息给智能体 | `nanobot agent -m "Hello"` |
| `nanobot agent` | 进入交互式聊天模式 | `nanobot agent` |
| `nanobot gateway` | 启动网关（启用通道） | `nanobot gateway` |
| `nanobot status` | 显示系统状态 | `nanobot status` |
| `nanobot channels login` | 登录 WhatsApp（扫码） | `nanobot channels login` |
| `nanobot channels status` | 显示通道状态 | `nanobot channels status` |
| `nanobot cron add` | 添加定时任务 | `nanobot cron add --name "daily" --message "Good morning" --cron "0 9 * * *"` |
| `nanobot cron list` | 列出定时任务 | `nanobot cron list` |
| `nanobot cron remove` | 删除定时任务 | `nanobot cron remove job_id` |

### 程序化 API
```python
from nanobot.config.loader import load_config
from nanobot.bus.queue import MessageBus
from nanobot.agent.loop import AgentLoop

# 1. 加载配置
config = load_config()

# 2. 创建消息总线和提供商
bus = MessageBus()
provider = _make_provider(config)  # 内部工具函数

# 3. 创建智能体循环
agent = AgentLoop(
    bus=bus,
    provider=provider,
    workspace=config.workspace_path,
    model=config.agents.defaults.model,
    brave_api_key=config.tools.web.search.api_key,
    restrict_to_workspace=config.tools.restrict_to_workspace
)

# 4. 处理消息
response = await agent.process_direct(
    content="What's 2+2?",
    session_key="cli:test"
)
```

## 部署指南

### 本地安装
```bash
# 从源码安装（开发推荐）
git clone https://github.com/HKUDS/nanobot.git
cd nanobot
pip install -e .

# 从 PyPI 安装（稳定版）
pip install nanobot-ai

# 使用 uv 安装（快速）
uv tool install nanobot-ai
```

### Docker 部署
```bash
# 构建镜像
docker build -t nanobot .

# 初始化配置
docker run -v ~/.nanobot:/root/.nanobot --rm nanobot onboard

# 编辑配置文件（添加 API 密钥）
vim ~/.nanobot/config.json

# 运行网关
docker run -v ~/.nanobot:/root/.nanobot -p 18790:18790 nanobot gateway
```

### 配置 API 密钥
1. **OpenRouter**（推荐）：访问 https://openrouter.ai/keys
2. **Brave Search**（可选）：访问 https://brave.com/search/api/
3. **其他提供商**：参考 README 中的对应链接

### 安全配置
```json
{
    "tools": {
        "restrict_to_workspace": true
    },
    "channels": {
        "telegram": {
            "allowFrom": ["YOUR_USER_ID"]
        }
    }
}
```

## 开发指南

### 项目结构
```
nanobot/
├── agent/              # 智能体核心逻辑
│   ├── loop.py         # 主循环
│   ├── context.py      # 上下文构建
│   ├── memory.py       # 内存系统
│   ├── skills.py       # 技能加载器
│   ├── subagent.py     # 子代理管理
│   └── tools/          # 内置工具
│       ├── registry.py # 工具注册表
│       ├── filesystem.py
│       ├── shell.py
│       ├── web.py
│       ├── message.py
│       ├── spawn.py
│       └── cron.py
├── skills/             # 内置技能
│   ├── github/
│   ├── weather/
│   └── tmux/
├── channels/           # 通信通道
│   ├── manager.py
│   ├── telegram.py
│   ├── discord.py
│   ├── whatsapp.py
│   └── feishu.py
├── bus/                # 消息总线
│   ├── events.py
│   └── queue.py
├── cron/               # 定时任务
│   ├── service.py
│   └── types.py
├── heartbeat/          # 心跳服务
├── providers/          # LLM 提供商
│   ├── base.py
│   ├── litellm_provider.py
│   └── ...
├── session/            # 会话管理
├── config/             # 配置系统
├── utils/              # 工具函数
└── cli/                # 命令行接口
```

### 添加新工具
1. 在 `agent/tools/` 目录下创建新文件
2. 继承 `BaseTool` 类
3. 实现 `execute()` 方法
4. 注册到 `ToolRegistry`

**示例**：
```python
# agent/tools/calculator.py
from nanobot.agent.tools.base import BaseTool

class CalculatorTool(BaseTool):
    name = "calculator"
    description = "Perform basic arithmetic calculations"
    
    async def execute(self, expression: str) -> str:
        # 安全计算表达式
        try:
            # 注意：实际实现中需要更严格的安全检查
            result = eval(expression, {"__builtins__": None}, {})
            return f"{expression} = {result}"
        except Exception as e:
            return f"Error: {str(e)}"
```

### 添加新技能
1. 在 `skills/` 目录下创建新文件夹
2. 添加 `SKILL.md` 文件（技能说明）
3. 可选：添加 `__init__.py` 和实现代码
4. 技能会自动被 `SkillsLoader` 发现

**技能目录结构**：
```
skills/my_skill/
├── SKILL.md            # 技能文档（必须）
├── __init__.py         # 实现代码（可选）
└── requirements.txt    # 依赖（可选）
```

### 添加新 LLM 提供商
1. 在 `providers/` 目录下创建新文件
2. 继承 `LLMProvider` 基类
3. 实现 `chat()` 方法
4. 在配置 schema 中添加对应的 provider 字段

### 调试技巧
1. **启用详细日志**：运行 `nanobot gateway --verbose`
2. **查看会话历史**：检查 `~/.nanobot/sessions/` 目录
3. **监控工具调用**：查看日志中的 `Tool call:` 条目
4. **测试配置**：使用 `nanobot status` 验证配置

## 性能优化

### 内存优化
- **会话清理**：定期清理过期会话（默认保留7天）
- **记忆剪裁**：长期记忆文件大小限制
- **工具缓存**：常用工具结果缓存

### 响应时间优化
- **并发处理**：支持多个消息并行处理
- **LLM 批处理**：合并相似请求
- **工具预加载**：常用工具预热

### 扩展性设计
- **水平扩展**：支持多个智能体实例负载均衡
- **垂直扩展**：可替换更强的 LLM 提供商
- **插件架构**：所有核心组件都可替换

## 故障排除

### 常见问题
1. **API 密钥错误**：检查 `~/.nanobot/config.json` 中的 provider 配置
2. **文件权限问题**：确保工作空间目录可读写
3. **网络连接问题**：检查代理设置或防火墙规则
4. **依赖缺失**：运行 `pip install -r requirements.txt` 或 `uv pip install .`

### 日志位置
- 控制台日志（默认级别 INFO）
- 文件日志：`~/.nanobot/logs/`（如果启用）

### 诊断命令
```bash
# 检查配置
nanobot status

# 测试 LLM 连接
nanobot agent -m "Test connection"

# 查看通道状态
nanobot channels status
```

## 安全考虑

### 默认安全设置
1. **工作空间限制**：默认关闭，建议生产环境启用
2. **用户白名单**：通道可配置 `allowFrom` 列表
3. **命令超时**：Shell 命令默认 30 秒超时
4. **文件访问限制**：可配置仅访问工作空间内文件

### 风险缓解
- **输入验证**：所有工具参数都经过 Pydantic 验证
- **沙箱执行**：Shell 命令在指定工作目录执行
- **权限最小化**：默认使用当前用户权限，不建议以 root 运行

### 生产部署建议
1. 启用 `restrict_to_workspace`
2. 配置通道用户白名单
3. 使用 Docker 容器隔离
4. 定期备份重要数据
5. 监控 API 使用量

## 贡献指南

### 开发流程
1. Fork 仓库
2. 创建特性分支
3. 提交更改
4. 运行测试
5. 创建 Pull Request

### 代码规范
- **格式化**：使用 Ruff（配置在 `pyproject.toml`）
- **类型提示**：所有公共函数都需要类型提示
- **文档**：公共 API 需要文档字符串
- **测试**：新功能需要测试用例

### 测试
```bash
# 运行所有测试
pytest

# 运行特定测试
pytest tests/test_agent.py

# 带覆盖率报告
pytest --cov=nanobot
```

## 版本历史

### v0.1.3.post5 (2026-02-07)
- 添加 Qwen 支持
- 多项改进和 bug 修复

### v0.1.3.post4 (2026-02-04)
- 多提供商支持
- Docker 支持

### v0.1.0 (2026-02-02)
- 初始发布
- 核心智能体循环
- 基础工具集
- Telegram/WhatsApp 集成

## 相关资源
- **GitHub**：https://github.com/HKUDS/nanobot
- **PyPI**：https://pypi.org/project/nanobot-ai/
- **文档**：https://github.com/HKUDS/nanobot#readme
- **讨论组**：见 `COMMUNICATION.md`

---
*文档版本：v1.0*  
*最后更新：2026-02-08*  
*维护团队：nanobot contributors*