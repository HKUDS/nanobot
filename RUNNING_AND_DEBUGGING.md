# Nanobot 运行与调试指南

本文档详细介绍如何运行、调试和排查 nanobot 项目的各种问题。

---

## 📋 目录

1. [环境准备](#环境准备)
2. [安装与配置](#安装与配置)
3. [运行方式](#运行方式)
4. [调试技巧](#调试技巧)
5. [常见问题排查](#常见问题排查)
6. [开发模式](#开发模式)

---

## 环境准备

### 系统要求

| 项目 | 要求 | 说明 |
|------|------|------|
| Python | ≥3.11 | 必需，使用类型注解和 asyncio 特性 |
| 操作系统 | Linux/macOS/Windows | 全平台支持 |
| 内存 | ≥2GB | 取决于使用的 LLM |
| 磁盘空间 | ≥500MB | 代码 + 依赖 + 工作空间 |

### 检查 Python 版本

```bash
python --version  # 应显示 3.11 或更高
```

---

## 安装与配置

### 1. 克隆项目

```bash
git clone https://github.com/HKUDS/nanobot.git
cd nanobot
```

### 2. 安装依赖

**方式一：开发模式（推荐）**

```bash
# 创建虚拟环境（推荐）
python -m venv venv

# 激活虚拟环境
# Windows:
venv\Scripts\activate
# Linux/macOS:
source venv/bin/activate

# 安装项目（可编辑模式）
pip install -e ".[dev]"
```

**方式二：使用 uv（更快）**

```bash
pip install uv
uv pip install -e ".[dev]"
```

### 3. 初始化配置

```bash
nanobot onboard
```

这会创建：
- `~/.nanobot/config.json` - 主配置文件
- `~/.nanobot/sessions/` - 会话存储目录
- `~/.nanobot/cron_store.json` - 定时任务存储

### 4. 配置 API 密钥

编辑 `~/.nanobot/config.json`：

```json
{
  "providers": {
    "openrouter": {
      "apiKey": "sk-or-v1-你的密钥"
    }
  },
  "agents": {
    "defaults": {
      "model": "anthropic/claude-3.5-sonnet"
    }
  }
}
```

获取 API 密钥：
- [OpenRouter](https://openrouter.ai/keys) (推荐，支持多种模型)
- [DashScope](https://dashscope.console.aliyun.com) (通义千问)
- [DeepSeek](https://platform.deepseek.com) (DeepSeek)

---

## 运行方式

### 方式一：命令行交互模式

适合快速测试和单次任务：

```bash
# 单条消息
nanobot agent -m "你好，请介绍一下自己"

# 交互模式（多轮对话）
nanobot agent
```

### 方式二：Gateway 模式（推荐）

启动持续运行的服务，支持 Telegram/Discord 等通道：

```bash
nanobot gateway
```

预期输出：
```
INFO:     Agent loop started
INFO:     Telegram channel enabled
INFO:     Starting telegram channel...
INFO:     Outbound dispatcher started
```

### 方式三：Docker 运行

```bash
# 构建镜像
docker build -t nanobot .

# 运行 gateway
docker run -v ~/.nanobot:/root/.nanobot -p 18790:18790 nanobot gateway

# 运行单次命令
docker run -v ~/.nanobot:/root/.nanobot --rm nanobot agent -m "Hello"
```

### 方式四：Python 直接运行

适合开发和调试：

```bash
# 运行模块
python -m nanobot agent -m "测试消息"

# 运行 gateway
python -m nanobot gateway
```

---

## 调试技巧

### 1. 日志级别控制

nanobot 使用 `loguru` 进行日志记录，默认级别为 `INFO`。

**查看详细日志：**

在代码中设置（临时）：
```python
from loguru import logger
import sys

# 添加更详细的日志输出
logger.add(sys.stderr, level="DEBUG")
```

**日志文件位置：**
- 标准输出：控制台实时显示
- 日志文件：`~/.nanobot/logs/`（如配置了文件日志）

### 2. 常见日志解读

```
# 正常启动
INFO:     Agent loop started

# 收到消息
INFO:     Processing message from telegram:user123: 你好...

# 工具调用
INFO:     Tool call: read_file({"file_path": "/path/to/file"})

# 发送响应
INFO:     Response to telegram:user123: 你好！我是 nanobot...

# 错误示例
ERROR:    Error processing message: Connection timeout
```

### 3. 使用 VS Code 调试

创建 `.vscode/launch.json`：

```json
{
  "version": "0.2.0",
  "configurations": [
    {
      "name": "Debug: nanobot agent",
      "type": "debugpy",
      "request": "launch",
      "module": "nanobot",
      "args": ["agent", "-m", "测试消息"],
      "console": "integratedTerminal",
      "justMyCode": false
    },
    {
      "name": "Debug: nanobot gateway",
      "type": "debugpy",
      "request": "launch",
      "module": "nanobot",
      "args": ["gateway"],
      "console": "integratedTerminal",
      "justMyCode": false
    }
  ]
}
```

**调试步骤：**
1. 在代码中设置断点（点击行号左侧）
2. 选择调试配置（如 "Debug: nanobot agent"）
3. 按 F5 启动调试
4. 使用 F10（单步跳过）、F11（单步进入）进行调试

### 4. 关键断点位置

推荐在以下位置设置断点进行问题排查：

| 文件 | 位置 | 用途 |
|------|------|------|
| `agent/loop.py:136` | `_process_message` | 消息处理入口 |
| `agent/loop.py:209` | `provider.chat` | LLM 调用前 |
| `agent/tools/registry.py:87` | `execute` | 工具执行前 |
| `channels/telegram.py` | `start` | 通道启动 |
| `bus/queue.py:25` | `publish_inbound` | 消息入队 |

### 5. 性能分析

**查看代码行数（项目统计）：**

```bash
bash core_agent_lines.sh
```

**Python 性能分析：**

```bash
# 使用 cProfile
python -m cProfile -o output.prof -m nanobot agent -m "测试"

# 查看分析结果
python -m pstats output.prof
```

---

## 常见问题排查

### 问题 1：ImportError / 模块未找到

**现象：**
```
ModuleNotFoundError: No module named 'nanobot'
```

**解决：**
```bash
# 确保在虚拟环境中
which python  # 应显示虚拟环境路径

# 重新安装
pip install -e .

# 检查安装
pip list | grep nanobot
```

### 问题 2：API 密钥错误

**现象：**
```
Error: 401 Unauthorized
```

**排查步骤：**
1. 检查 `~/.nanobot/config.json` 中的 API 密钥
2. 验证密钥是否有效（使用 curl 测试）
3. 检查网络连接和代理设置

**测试命令：**
```bash
# 测试 OpenRouter
curl https://openrouter.ai/api/v1/auth/key \
  -H "Authorization: Bearer $YOUR_API_KEY"
```

### 问题 3：通道连接失败

**Telegram 连接失败：**
```
ERROR:    Failed to start channel telegram: Invalid token
```

**解决：**
1. 从 @BotFather 获取有效 token
2. 检查 config.json 格式是否正确
3. 确认 token 没有额外的空格或换行

**Discord 连接失败：**
1. 检查是否启用了 MESSAGE CONTENT INTENT
2. 确认 bot token 有效
3. 检查是否已邀请 bot 到服务器

### 问题 4：工具执行失败

**现象：**
```
Error executing read_file: File not found
```

**排查：**
1. 检查文件路径是否正确
2. 确认文件在工作空间内（如启用 `restrictToWorkspace`）
3. 检查文件权限

**调试代码：**
```python
# 在工具执行处添加日志
logger.debug(f"Executing tool {name} with params: {params}")
```

### 问题 5：内存不足

**现象：**
```
MemoryError
```

**解决：**
1. 限制会话历史长度（默认 50 条）
2. 减少同时运行的子代理数量
3. 使用更小的模型

### 问题 6：定时任务不执行

**排查：**
```bash
# 查看定时任务列表
nanobot cron list

# 检查服务状态
nanobot status

# 手动执行任务测试
nanobot cron run <job_id>
```

---

## 开发模式

### 热重载开发

使用 `watchdog` 或 `entr` 实现代码修改自动重启：

```bash
# 安装 watchdog
pip install watchdog

# 使用 watchdog 监控文件变化
watchmedo auto-restart \
  --directory=./nanobot \
  --pattern="*.py" \
  --recursive \
  -- python -m nanobot gateway
```

### 运行测试

```bash
# 运行所有测试
pytest

# 运行特定测试
pytest tests/test_specific.py -v

# 带覆盖率报告
pytest --cov=nanobot --cov-report=html
```

### 代码检查

```bash
# 使用 ruff 检查代码风格
ruff check nanobot/

# 自动修复
ruff check nanobot/ --fix

# 类型检查（如有配置）
basedpyright nanobot/
```

### 本地 LLM 调试

使用 vLLM 进行本地调试（无需 API 费用）：

```bash
# 1. 安装 vLLM
pip install vllm

# 2. 启动本地服务
vllm serve meta-llama/Llama-3.1-8B-Instruct --port 8000

# 3. 配置 config.json
{
  "providers": {
    "vllm": {
      "apiKey": "dummy",
      "apiBase": "http://localhost:8000/v1"
    }
  }
}

# 4. 运行测试
nanobot agent -m "测试本地模型" --provider vllm
```

---

## 配置文件详解

### 完整配置示例

```json
{
  "providers": {
    "openrouter": {
      "apiKey": "sk-or-v1-xxx",
      "apiBase": "https://openrouter.ai/api/v1"
    },
    "groq": {
      "apiKey": "gsk_xxx"
    }
  },
  "agents": {
    "defaults": {
      "model": "anthropic/claude-3.5-sonnet",
      "provider": "openrouter",
      "maxIterations": 20
    }
  },
  "channels": {
    "telegram": {
      "enabled": true,
      "token": "123456:ABC-DEF...",
      "allowFrom": ["123456789"]
    },
    "discord": {
      "enabled": false,
      "token": "..."
    }
  },
  "tools": {
    "restrictToWorkspace": true,
    "exec": {
      "timeout": 60,
      "allowedCommands": ["git", "python", "pip"]
    }
  },
  "cron": {
    "enabled": true
  }
}
```

### 配置项说明

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `providers.*.apiKey` | string | - | LLM API 密钥 |
| `agents.defaults.model` | string | - | 默认使用的模型 |
| `agents.defaults.maxIterations` | number | 20 | 最大工具调用轮数 |
| `channels.*.enabled` | boolean | false | 是否启用该通道 |
| `channels.*.allowFrom` | array | [] | 白名单用户ID，空数组表示允许所有 |
| `tools.restrictToWorkspace` | boolean | false | 是否限制工具在工作空间内 |
| `tools.exec.timeout` | number | 60 | Shell 命令超时时间（秒） |

---

## 获取帮助

### 命令行帮助

```bash
# 查看所有命令
nanobot --help

# 查看特定命令帮助
nanobot agent --help
nanobot gateway --help
nanobot cron --help
```

### 调试信息收集

遇到问题时，收集以下信息：

1. **日志输出**（带 DEBUG 级别）
2. **配置文件**（脱敏后）
3. **Python 版本**：`python --version`
4. **依赖版本**：`pip list`
5. **操作系统版本**

---

## 总结

| 场景 | 推荐方式 |
|------|----------|
| 快速测试 | `nanobot agent -m "消息"` |
| 日常使用 | `nanobot gateway` |
| 开发调试 | VS Code + launch.json |
| 生产部署 | Docker |
| 本地开发 | 虚拟环境 + 热重载 |

---

**下一步：**
- 阅读 [README.md](./README.md) 了解功能特性
- 查看 [TECHNICAL_DOCUMENTATION.md](./TECHNICAL_DOCUMENTATION.md) 了解架构设计
- 参考代码中的中文注释理解实现细节
