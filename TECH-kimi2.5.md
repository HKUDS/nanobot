# nanobot 技术开发文档

> **目标读者**: 开发者、架构师、贡献者  
> **文档版本**: v1.0  
> **最后更新**: 2026-02-08

---

## 1. 架构概览

### 1.1 系统架构图

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              nanobot 系统架构                                │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐        │
│  │  Telegram   │  │   Discord   │  │   Feishu    │  │  WhatsApp   │        │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘        │
│         │                │                │                │               │
│         └────────────────┴────────────────┴────────────────┘               │
│                                   │                                         │
│                           ┌───────┴───────┐                                │
│                           │  Message Bus  │  ◄── 事件总线，解耦渠道与核心    │
│                           │   (Queue)     │                                │
│                           └───────┬───────┘                                │
│                                   │                                         │
│                    ┌──────────────┼──────────────┐                         │
│                    │              │              │                         │
│              ┌─────┴─────┐  ┌─────┴─────┐  ┌─────┴─────┐                  │
│              │  Agent    │  │   Cron    │  │ Heartbeat │                  │
│              │   Loop    │  │  Service  │  │  Service  │                  │
│              └─────┬─────┘  └───────────┘  └───────────┘                  │
│                    │                                                        │
│         ┌──────────┼──────────┐                                            │
│         │          │          │                                            │
│    ┌────┴───┐ ┌────┴───┐ ┌────┴───┐                                       │
│    │  LLM   │ │ Tools  │ │Memory  │                                       │
│    │Provider│ │Registry│ │System  │                                       │
│    └────────┘ └────────┘ └────────┘                                       │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 1.2 核心模块说明

| 模块 | 路径 | 职责 | 代码行数 |
|------|------|------|----------|
| Agent Loop | `agent/loop.py` | 核心处理引擎，协调 LLM、工具、记忆 | ~200 |
| Tool Registry | `agent/tools/` | 工具注册与执行 | ~600 |
| LLM Provider | `providers/` | 多模型统一接口 | ~300 |
| Message Bus | `bus/` | 事件总线，解耦组件 | ~150 |
| Channels | `channels/` | 多平台消息接入 | ~800 |
| Skills | `skills/` | 技能系统 | ~400 |
| Session | `session/` | 会话管理 | ~150 |
| Cron | `cron/` | 定时任务 | ~200 |

---

## 2. 核心流程

### 2.1 消息处理流程

```
用户消息
    │
    ▼
┌─────────────┐
│   Channel   │ ──► 接收消息，验证来源
└──────┬──────┘
       │
       ▼
┌─────────────┐
│ Message Bus │ ──► 转换为 InboundMessage
└──────┬──────┘
       │
       ▼
┌─────────────┐
│  Agent Loop │ ──► 构建上下文，调用 LLM
└──────┬──────┘
       │
       ├─────────────────────────────────────┐
       ▼                                     ▼
┌─────────────┐                      ┌─────────────┐
│  Tool Call  │ ◄──────────────────► │  LLM Resp   │
└──────┬──────┘                      └─────────────┘
       │
       ▼
┌─────────────┐
│Tool Registry│ ──► 执行工具，返回结果
└──────┬──────┘
       │
       ▼
┌─────────────┐
│   Response  │ ──► 生成回复
└──────┬──────┘
       │
       ▼
┌─────────────┐
│ Message Bus │ ──► 发送 OutboundMessage
└──────┬──────┘
       │
       ▼
┌─────────────┐
│   Channel   │ ──► 用户收到回复
└─────────────┘
```

### 2.2 Agent Loop 详细流程

```python
# agent/loop.py 核心逻辑

async def process_message(self, message: InboundMessage):
    # 1. 加载或创建会话
    session = self.sessions.get_or_create(message.session_key)
    
    # 2. 构建上下文
    context = self.context.build(
        system_prompt=self._load_system_prompt(),
        skills=self._load_relevant_skills(message),
        memory=self._load_memory(),
        history=session.get_history(),
        user_message=message.content
    )
    
    # 3. LLM 调用循环 (最多 max_iterations 次)
    for i in range(self.max_iterations):
        response = await self.provider.chat(
            messages=context,
            tools=self.tools.get_definitions()
        )
        
        if response.has_tool_calls:
            # 执行工具调用
            results = await self._execute_tool_calls(response.tool_calls)
            context.extend(results)
        else:
            # 返回最终回复
            break
    
    # 4. 保存会话历史
    session.add_exchange(message.content, response.content)
```

---

## 3. 模块详解

### 3.1 Agent Loop (`agent/loop.py`)

**职责**: 核心处理引擎，协调各组件完成消息处理

**关键类**:
```python
class AgentLoop:
    def __init__(self, bus, provider, workspace, ...):
        self.context = ContextBuilder(workspace)    # 上下文构建
        self.sessions = SessionManager(workspace)   # 会话管理
        self.tools = ToolRegistry()                  # 工具注册表
        self.subagents = SubagentManager(...)       # 子代理管理
```

**处理流程**:
1. 接收 `InboundMessage`
2. 构建完整上下文（系统提示 + 技能 + 记忆 + 历史）
3. 调用 LLM，处理工具调用循环
4. 发送 `OutboundMessage`

### 3.2 工具系统 (`agent/tools/`)

**架构**:
```
agent/tools/
├── base.py       # Tool 抽象基类
├── registry.py   # ToolRegistry 工具注册表
├── filesystem.py # 文件操作工具 (read/write/edit/list)
├── shell.py      # Shell 执行工具
├── web.py        # 网络工具 (search/fetch)
├── message.py    # 消息发送工具
├── spawn.py      # 子代理工具
└── cron.py       # 定时任务工具
```

**Tool 基类**:
```python
class Tool(ABC):
    @property
    @abstractmethod
    def name(self) -> str: ...
    
    @property
    @abstractmethod
    def description(self) -> str: ...
    
    @property
    @abstractmethod
    def parameters(self) -> dict: ...
    
    @abstractmethod
    async def execute(self, **kwargs) -> str: ...
```

**内置工具列表**:

| 工具 | 名称 | 功能 | 安全限制 |
|------|------|------|----------|
| ReadFileTool | `read_file` | 读取文件内容 | 可选工作区限制 |
| WriteFileTool | `write_file` | 写入文件 | 可选工作区限制 |
| EditFileTool | `edit_file` | 编辑文件 | 可选工作区限制 |
| ListDirTool | `list_dir` | 列出目录 | 可选工作区限制 |
| ExecTool | `exec` | 执行 shell | 危险命令拦截 |
| WebSearchTool | `web_search` | 网络搜索 | 需 API Key |
| WebFetchTool | `web_fetch` | 获取网页 | 内容长度限制 |
| MessageTool | `message` | 发送消息 | 内部使用 |
| SpawnTool | `spawn` | 子代理 | 资源限制 |
| CronTool | `cron` | 定时任务 | - |

### 3.3 LLM Provider (`providers/`)

**架构**:
```python
# providers/base.py
class LLMProvider(ABC):
    @abstractmethod
    async def chat(self, messages, tools, model, ...) -> LLMResponse: ...
    
    @abstractmethod
    def get_default_model(self) -> str: ...

# providers/litellm_provider.py
class LiteLLMProvider(LLMProvider):
    # 使用 litellm 统一接口支持多模型
```

**支持的 Provider**:

| Provider | 标识 | 默认模型 |
|----------|------|----------|
| Anthropic | `anthropic` | claude-opus-4-5 |
| OpenAI | `openai` | gpt-4 |
| OpenRouter | `openrouter` | anthropic/claude-opus-4-5 |
| DeepSeek | `deepseek` | deepseek-chat |
| Groq | `groq` | llama-3.1-70b |
| Zhipu | `zhipu` | glm-4 |
| DashScope | `dashscope` | qwen-max |
| vLLM | `vllm` | 自定义 |
| Gemini | `gemini` | gemini-pro |
| Moonshot | `moonshot` | moonshot-v1-8k |
| AiHubMix | `aihubmix` | 多模型 |

### 3.4 消息总线 (`bus/`)

**设计**: 基于异步队列的事件总线，解耦渠道与核心

```python
# bus/events.py
@dataclass
class InboundMessage:
    channel: str      # telegram/discord/feishu/whatsapp
    sender_id: str    # 用户标识
    chat_id: str      # 会话标识
    content: str      # 消息内容
    timestamp: datetime
    metadata: dict    # 渠道特定数据

@dataclass
class OutboundMessage:
    channel: str
    chat_id: str
    content: str
    reply_to: str | None
```

```python
# bus/queue.py
class MessageBus:
    async def publish_inbound(self, message: InboundMessage): ...
    async def publish_outbound(self, message: OutboundMessage): ...
    async def subscribe(self, handler): ...
```

### 3.5 渠道接入 (`channels/`)

**架构**:
```python
# channels/base.py
class BaseChannel(ABC):
    name: str = "base"
    
    @abstractmethod
    async def start(self) -> None: ...
    
    @abstractmethod
    async def stop(self) -> None: ...
```

**渠道实现**:

| 渠道 | 协议 | 特点 |
|------|------|------|
| Telegram | HTTP Polling / Webhook | python-telegram-bot |
| Discord | WebSocket Gateway | 原生异步 |
| Feishu | WebSocket | lark-oapi SDK |
| WhatsApp | WebSocket (puppet) | Node.js Bridge |

### 3.6 技能系统 (`skills/`)

**设计**: 基于 Markdown 的声明式技能定义

```
skills/
├── SKILL.md          # 技能元数据
├── github/SKILL.md   # GitHub 操作技能
├── weather/SKILL.md  # 天气查询技能
├── summarize/        # 内容总结技能
├── tmux/             # Tmux 控制技能
└── skill-creator/    # 技能创建技能
```

**SKILL.md 格式**:
```markdown
---
name: "skill-name"
description: "技能描述，LLM 用它来决定何时调用"
---

# 技能名称

## 功能说明
...

## 使用示例
...
```

**加载机制**:
1. 扫描 `skills/` 目录
2. 解析所有 `SKILL.md` 文件
3. 提取 frontmatter 和内容
4. 根据描述相关性选择技能

### 3.7 会话管理 (`session/`)

**设计**: 基于文件的轻量级会话存储

```python
class SessionManager:
    def get_or_create(self, session_key: str) -> Session
    def get_history(self, limit: int = 10) -> list[dict]
    def add_exchange(self, user_msg: str, assistant_msg: str)
```

**存储结构**:
```
workspace/
└── .nanobot/
    └── sessions/
        └── {session_key}.json
```

### 3.8 定时任务 (`cron/`)

**设计**: 基于 `croniter` 的定时任务系统

```python
class CronService:
    async def add_job(self, name, message, schedule, ...)
    async def remove_job(self, name)
    async def list_jobs()
```

**支持格式**:
- Cron 表达式: `0 9 * * *` (每天 9 点)
- 间隔秒数: `--every 3600` (每小时)
- 指定时间: `--at 2025-01-31T15:00:00`

---

## 4. 配置系统

### 4.1 配置文件结构

```json
{
  "providers": {
    "openrouter": {
      "apiKey": "sk-or-v1-xxx",
      "apiBase": null
    }
  },
  "agents": {
    "defaults": {
      "workspace": "~/.nanobot/workspace",
      "model": "anthropic/claude-opus-4-5",
      "max_tokens": 8192,
      "temperature": 0.7,
      "max_tool_iterations": 20
    }
  },
  "channels": {
    "telegram": {
      "enabled": true,
      "token": "xxx",
      "allow_from": ["user_id"]
    }
  },
  "tools": {
    "web": {
      "search": {
        "api_key": "brave-api-key"
      }
    },
    "exec": {
      "timeout": 60,
      "dangerous_commands": ["rm -rf", "format", "dd"]
    }
  }
}
```

### 4.2 配置加载优先级

1. 环境变量 (NANOBOT_*)
2. 配置文件 (`~/.nanobot/config.json`)
3. 默认值

---

## 5. 开发指南

### 5.1 环境搭建

```bash
# 1. 克隆仓库
git clone https://github.com/HKUDS/nanobot.git
cd nanobot

# 2. 创建虚拟环境
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 3. 安装依赖
pip install -e ".[dev]"

# 4. 运行测试
pytest
```

### 5.2 添加新工具

```python
# 1. 创建工具类
from nanobot.agent.tools.base import Tool

class MyTool(Tool):
    @property
    def name(self) -> str:
        return "my_tool"
    
    @property
    def description(self) -> str:
        return "工具描述"
    
    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "param": {"type": "string"}
            },
            "required": ["param"]
        }
    
    async def execute(self, param: str) -> str:
        return f"Result: {param}"

# 2. 注册工具
# 在 agent/loop.py 的 _register_default_tools 中添加:
self.tools.register(MyTool())
```

### 5.3 添加新渠道

```python
# 1. 实现 BaseChannel
from nanobot.channels.base import BaseChannel

class MyChannel(BaseChannel):
    name = "my_channel"
    
    async def start(self) -> None:
        # 连接渠道，监听消息
        # 收到消息后调用 self._handle_message(inbound_msg)
        pass
    
    async def stop(self) -> None:
        # 清理资源
        pass
    
    async def send(self, message: OutboundMessage) -> None:
        # 发送消息到渠道
        pass

# 2. 添加到 ChannelManager
# 在 channels/manager.py 中添加初始化逻辑
```

### 5.4 添加新技能

```bash
# 1. 创建技能目录
mkdir -p nanobot/skills/my_skill

# 2. 创建 SKILL.md
cat > nanobot/skills/my_skill/SKILL.md << 'EOF'
---
name: "my-skill"
description: "技能描述，说明何时使用此技能"
---

# My Skill

## 功能
详细描述技能功能...

## 使用示例
示例代码...
EOF
```

---

## 6. 部署方案

### 6.1 Docker 部署

```bash
# 构建镜像
docker build -t nanobot .

# 运行容器
docker run -d \
  -v ~/.nanobot:/root/.nanobot \
  -p 18790:18790 \
  nanobot agent
```

### 6.2 本地部署

```bash
# 安装
pip install nanobot-ai

# 初始化
nanobot onboard

# 编辑配置
nano ~/.nanobot/config.json

# 启动
nanobot agent
```

### 6.3 系统服务 (systemd)

```ini
# /etc/systemd/system/nanobot.service
[Unit]
Description=nanobot AI Assistant
After=network.target

[Service]
Type=simple
User=nanobot
WorkingDirectory=/home/nanobot
ExecStart=/usr/local/bin/nanobot agent
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

---

## 7. 性能优化

### 7.1 代码行数统计

```bash
# 运行统计脚本
bash core_agent_lines.sh

# 当前统计 (~3,422 行)
# - agent/: ~1,000 行
# - channels/: ~800 行
# - providers/: ~300 行
# - tools/: ~600 行
# - 其他: ~700 行
```

### 7.2 内存优化

- 使用生成器处理大文件
- 限制对话历史长度
- 异步 I/O 避免阻塞

### 7.3 延迟优化

- LLM 调用使用流式响应
- 工具调用并行执行
- 会话缓存热数据

---

## 8. 安全考虑

### 8.1 命令执行安全

```python
# shell.py 中的危险命令拦截
DANGEROUS_COMMANDS = [
    "rm -rf", "format", "dd", "shutdown", "reboot",
    "mkfs", "fdisk", "del /f", "rd /s"
]
```

### 8.2 文件系统安全

```python
# 可选的工作区限制
if self.restrict_to_workspace:
    allowed_dir = self.workspace
    if not path.startswith(allowed_dir):
        raise PermissionError("Access denied")
```

### 8.3 配置安全

- API Key 存储在本地配置文件
- 支持环境变量覆盖
- 日志脱敏处理

---

## 9. 调试技巧

### 9.1 日志级别

```python
# 设置 DEBUG 级别
export LOGURU_LEVEL=DEBUG
```

### 9.2 本地测试

```bash
# CLI 模式测试
nanobot agent -m "测试消息"

# 查看工具调用
nanobot agent -m "测试" --verbose
```

### 9.3 性能分析

```python
# 使用 cProfile
python -m cProfile -o profile.stats -m nanobot agent

# 分析结果
python -m pstats profile.stats
```

---

## 10. 贡献指南

### 10.1 代码规范

- 使用 `ruff` 进行代码检查
- 类型注解必需
- 文档字符串使用 Google Style

### 10.2 提交规范

```
feat: 新功能
fix: 修复
docs: 文档
style: 格式调整
refactor: 重构
test: 测试
chore: 构建/工具
```

### 10.3 PR 流程

1. Fork 仓库
2. 创建功能分支 (`git checkout -b feature/xxx`)
3. 提交更改 (`git commit -m "feat: xxx"`)
4. 推送分支 (`git push origin feature/xxx`)
5. 创建 Pull Request

---

## 11. 参考资源

- **GitHub**: https://github.com/HKUDS/nanobot
- **PyPI**: https://pypi.org/project/nanobot-ai/
- **文档**: 本文档 + README.md
- **社区**: Discord / 飞书 / 微信

---

## 附录: 核心代码索引

| 功能 | 文件路径 |
|------|----------|
| Agent 主循环 | `nanobot/agent/loop.py` |
| 工具基类 | `nanobot/agent/tools/base.py` |
| 工具注册表 | `nanobot/agent/tools/registry.py` |
| LLM 基类 | `nanobot/providers/base.py` |
| LiteLLM 实现 | `nanobot/providers/litellm_provider.py` |
| 消息事件 | `nanobot/bus/events.py` |
| 消息总线 | `nanobot/bus/queue.py` |
| 渠道基类 | `nanobot/channels/base.py` |
| 配置模型 | `nanobot/config/schema.py` |
| CLI 入口 | `nanobot/cli/commands.py` |
