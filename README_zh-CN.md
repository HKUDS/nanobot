<div align="center">
  <img src="nanobot_logo.png" alt="nanobot" width="500">
  <h1>nanobot: 超轻量级个人 AI 助手</h1>
  <p>
    <a href="./README_zh-CN.md">中文</a> | <a href="./README.md">English</a>
  </p>
  <p>
    <a href="https://pypi.org/project/nanobot-ai/"><img src="https://img.shields.io/pypi/v/nanobot-ai" alt="PyPI"></a>
    <a href="https://pepy.tech/project/nanobot-ai"><img src="https://static.pepy.tech/badge/nanobot-ai" alt="Downloads"></a>
    <img src="https://img.shields.io/badge/python-≥3.11-blue" alt="Python">
    <img src="https://img.shields.io/badge/license-MIT-green" alt="License">
    <a href="./COMMUNICATION.md"><img src="https://img.shields.io/badge/Feishu-Group-E9DBFC?style=flat&logo=feishu&logoColor=white" alt="Feishu"></a>
    <a href="./COMMUNICATION.md"><img src="https://img.shields.io/badge/WeChat-Group-C5EAB4?style=flat&logo=wechat&logoColor=white" alt="WeChat"></a>
    <a href="https://discord.gg/MnCvHqpUGB"><img src="https://img.shields.io/badge/Discord-Community-5865F2?style=flat&logo=discord&logoColor=white" alt="Discord"></a>
  </p>
</div>

🐈 **nanobot** 是一款受 [Clawdbot](https://github.com/openclaw/openclaw) 启发的**超轻量级**个人 AI 助手。

⚡️ 仅用 **~4,000** 行代码即实现了核心 Agent 功能 — 比 Clawdbot 的 430k+ 行代码**小 99%**。

## 📢 新闻

- **2026-02-01** 🎉 nanobot 发布！欢迎尝试 🐈 nanobot！

## nanobot 的主要特性：

🪶 **超轻量级**：仅 ~4,000 行代码 — 包含核心功能，体积比 Clawdbot 小 99%。

🔬 **易于研究**：代码干净易读，易于理解、修改和扩展，非常适合研究使用。

⚡️ **闪电般快速**：极小的占用意味着更快的启动速度、更低的资源消耗和更快的迭代。

💎 **易于使用**：一键部署，开箱即用。

## 🏗️ 架构

<p align="center">
  <img src="nanobot_arch.png" alt="nanobot architecture" width="800">
</p>

## ✨ 功能

<table align="center">
  <tr align="center">
    <th><p align="center">📈 7x24 实时市场分析</p></th>
    <th><p align="center">🚀 全栈软件工程师</p></th>
    <th><p align="center">📅 智能日程管理</p></th>
    <th><p align="center">📚 个人知识助手</p></th>
  </tr>
  <tr>
    <td align="center"><p align="center"><img src="case/search.gif" width="180" height="400"></p></td>
    <td align="center"><p align="center"><img src="case/code.gif" width="180" height="400"></p></td>
    <td align="center"><p align="center"><img src="case/scedule.gif" width="180" height="400"></p></td>
    <td align="center"><p align="center"><img src="case/memory.gif" width="180" height="400"></p></td>
  </tr>
  <tr>
    <td align="center">发现 • 洞察 • 趋势</td>
    <td align="center">开发 • 部署 • 扩展</td>
    <td align="center">日程 • 自动化 • 组织</td>
    <td align="center">学习 • 记忆 • 推理</td>
  </tr>
</table>

## 📦 安装

**从源码安装** (最新功能，推荐用于开发)

```bash
git clone https://github.com/HKUDS/nanobot.git
cd nanobot
pip install -e .
```

**使用 [uv](https://github.com/astral-sh/uv) 安装** (稳定，快速)

```bash
uv tool install nanobot-ai
```

**从 PyPI 安装** (稳定)

```bash
pip install nanobot-ai
```

## 🚀 快速开始

> [!TIP]
> 在 `~/.nanobot/config.json` 中设置 API Key。
> 获取 API Key: [OpenRouter](https://openrouter.ai/keys) (LLM) · [Brave Search](https://brave.com/search/api/) (可选，用于网络搜索)
> 你也可以将模型更改为 `minimax/minimax-m2` 以降低成本。

**1. 初始化**

```bash
nanobot onboard
```

**2. 配置** (`~/.nanobot/config.json`)

```json
{
  "providers": {
    "openrouter": {
      "apiKey": "sk-or-v1-xxx"
    }
  },
  "agents": {
    "defaults": {
      "model": "anthropic/claude-opus-4-5"
    }
  },
  "tools": {
    "web": {
      "search": {
        "apiKey": "BSA-xxx"
      }
    }
  }
}
```

**3. 聊天**

```bash
nanobot agent -m "2+2 等于几？"
```

就是这样！你在 2 分钟内就有了一个工作的 AI 助手。

## 🖥️ 本地模型 (vLLM)

使用 vLLM 或任何 OpenAI 兼容的服务器运行你自己的本地模型。

**1. 启动 vLLM 服务器**

```bash
vllm serve meta-llama/Llama-3.1-8B-Instruct --port 8000
```

**2. 配置** (`~/.nanobot/config.json`)

```json
{
  "providers": {
    "vllm": {
      "apiKey": "dummy",
      "apiBase": "http://localhost:8000/v1"
    }
  },
  "agents": {
    "defaults": {
      "model": "meta-llama/Llama-3.1-8B-Instruct"
    }
  }
}
```

**3. 聊天**

```bash
nanobot agent -m "来自本地 LLM 的问候！"
```

> [!TIP]
> 对于不需要认证的本地服务器，`apiKey` 可以是任何非空字符串。

## 💬 聊天应用

通过 Telegram、WhatsApp 或 飞书 随时随地与你的 nanobot 交谈。

| 渠道 | 设置 |
|---------|-------|
| **Telegram** | 简单 (仅需 token) |
| **WhatsApp** | 中等 (扫码) |
| **飞书 (Feishu)** | 中等 (应用凭证) |

<details>
<summary><b>Telegram</b> (推荐)</summary>

**1. 创建机器人**
- 打开 Telegram，搜索 `@BotFather`
- 发送 `/newbot`，按照提示操作
- 复制 token

**2. 配置**

```json
{
  "channels": {
    "telegram": {
      "enabled": true,
      "token": "YOUR_BOT_TOKEN",
      "allowFrom": ["YOUR_USER_ID"]
    }
  }
}
```

> 从 Telegram 上的 `@userinfobot` 获取你的 User ID。

**3. 运行**

```bash
nanobot gateway
```

</details>

<details>
<summary><b>WhatsApp</b></summary>

需要 **Node.js ≥18**。

**1. 链接设备**

```bash
nanobot channels login
# 使用 WhatsApp 扫描二维码 → 设置 → 已链接设备
```

**2. 配置**

```json
{
  "channels": {
    "whatsapp": {
      "enabled": true,
      "allowFrom": ["+1234567890"]
    }
  }
}
```

**3. 运行** (两个终端)

```bash
# 终端 1
nanobot channels login

# 终端 2
nanobot gateway
```

</details>

<details>
<summary><b>飞书 (Feishu)</b></summary>

使用 **WebSocket** 长连接 — 无需公网 IP。

```bash
pip install nanobot-ai[feishu]
```

**1. 创建飞书应用**
- 访问 [飞书开放平台](https://open.feishu.cn/app)
- 创建新应用 → 启用 **机器人** 能力
- **权限**：添加 `im:message` (发送消息)
- **事件**：添加 `im.message.receive_v1` (接收消息)
  - 选择 **长连接** 模式 (需要先运行 nanobot 以建立连接)
- 从 "凭证与基础信息" 获取 **App ID** 和 **App Secret**
- 发布应用

**2. 配置**

```json
{
  "channels": {
    "feishu": {
      "enabled": true,
      "appId": "cli_xxx",
      "appSecret": "xxx",
      "encryptKey": "",
      "verificationToken": "",
      "allowFrom": []
    }
  }
}
```

> `encryptKey` 和 `verificationToken` 对于长连接模式是可选的。
> `allowFrom`: 留空允许所有用户，或添加 `["ou_xxx"]` 限制访问。

**3. 运行**

```bash
nanobot gateway
```

> [!TIP]
> 飞书使用 WebSocket 接收消息 — 不需要 webhook 或公网 IP！

</details>

## 🔌 MCP 工具

nanobot 支持 [Model Context Protocol (MCP)](https://modelcontextprotocol.io/)，允许你通过任何 MCP 服务器轻松扩展其能力。

**配置** (`~/.nanobot/config.json`)

在你的配置中添加 `mcp_tool` 部分：

```json
{
  "mcp_tool": {
    "math": {
      "command": "python",
      "args": ["/path/to/math_server.py"],
      "transport": "stdio"
    },
    "weather": {
      "url": "http://localhost:8000/mcp",
      "transport": "http"
    }
  }
}
```

支持的传输方式：
- `stdio`: 运行本地命令 (推荐用于本地工具)
- `http` / `sse`: 通过 HTTP/SSE 连接到远程 MCP 服务器

这些服务器暴露的工具将被自动加载并可供 Agent 使用。

## ⚙️ 配置

配置文件：`~/.nanobot/config.json`

### 提供商 (Providers)

nanobot 通过 OpenAI 兼容性支持**几乎所有 LLM 提供商**。你可以配置任何支持 OpenAI API 格式的提供商。

常见提供商包括：

| 提供商 | 用途 | 获取 API Key |
|----------|---------|-------------|
| `openrouter` | 访问所有模型 (推荐) | [openrouter.ai](https://openrouter.ai) |
| `deepseek` | DeepSeek 模型 (国内) | [deepseek.com](https://platform.deepseek.com) |
| `zhipu` | GLM 模型 (国内) | [bigmodel.cn](https://open.bigmodel.cn) |
| `qwen` | 通义千问模型 (国内) | [dashscope.aliyun.com](https://dashscope.aliyun.com) |
| `anthropic` | Claude 模型 | [console.anthropic.com](https://console.anthropic.com) |
| `openai` | GPT 模型 | [platform.openai.com](https://platform.openai.com) |
| `gemini` | Gemini 模型 | [aistudio.google.com](https://aistudio.google.com) |
| `groq` | 快速推理 + Whisper | [console.groq.com](https://console.groq.com) |
| `vllm` | 本地模型 | - |

你可以通过在 `config.json` 的 `providers` 下添加带有 `apiBase` 和 `apiKey` 的新键来添加**任何自定义提供商**。

<details>
<summary><b>完整配置示例</b></summary>

```json
{
  "agents": {
    "defaults": {
      "model": "deepseek/deepseek-chat"
    }
  },
  "providers": {
    "openrouter": {
      "apiKey": "sk-or-v1-xxx"
    },
    "deepseek": {
      "apiKey": "sk-xxx"
    },
    "custom_provider": {
      "apiBase": "https://api.example.com/v1",
      "apiKey": "sk-xxx"
    }
  },
  "channels": {
    "telegram": {
      "enabled": true,
      "token": "123456:ABC...",
      "allowFrom": ["123456789"]
    },
    "whatsapp": {
      "enabled": false
    },
    "feishu": {
      "enabled": false,
      "appId": "cli_xxx",
      "appSecret": "xxx",
      "encryptKey": "",
      "verificationToken": "",
      "allowFrom": []
    }
  },
  "tools": {
    "web": {
      "search": {
        "apiKey": "BSA..."
      }
    }
  }
}
```

</details>

## CLI 参考

| 命令 | 描述 |
|---------|-------------|
| `nanobot onboard` | 初始化配置和工作区 |
| `nanobot agent -m "..."` | 与 agent 聊天 |
| `nanobot agent` | 交互式聊天模式 |
| `nanobot gateway` | 启动网关 |
| `nanobot status` | 显示状态 |
| `nanobot channels login` | 链接 WhatsApp (扫码) |
| `nanobot channels status` | 显示渠道状态 |

<details>
<summary><b>定时任务 (Cron)</b></summary>

```bash
# 添加任务
nanobot cron add --name "daily" --message "Good morning!" --cron "0 9 * * *"
nanobot cron add --name "hourly" --message "Check status" --every 3600

# 列出任务
nanobot cron list

# 删除任务
nanobot cron remove <job_id>
```

</details>

## 🐳 Docker

> [!TIP]
> `-v ~/.nanobot:/root/.nanobot` 标志将你的本地配置目录挂载到容器中，因此你的配置和工作区在容器重启后依然保留。

在容器中构建并运行 nanobot：

```bash
# 构建镜像
docker build -t nanobot .

# 初始化配置 (仅第一次)
docker run -v ~/.nanobot:/root/.nanobot --rm nanobot onboard

# 在主机上编辑配置以添加 API Key
vim ~/.nanobot/config.json

# 运行网关 (连接 Telegram/WhatsApp)
docker run -v ~/.nanobot:/root/.nanobot -p 18790:18790 nanobot gateway

# 或者运行单个命令
docker run -v ~/.nanobot:/root/.nanobot --rm nanobot agent -m "Hello!"
docker run -v ~/.nanobot:/root/.nanobot --rm nanobot status
```

## 📁 项目结构

```
nanobot/
├── agent/          # 🧠 核心 Agent 逻辑
│   ├── loop.py     #    Agent 循环 (LLM ↔ 工具执行)
│   ├── context.py  #    Prompt 构建
│   ├── memory.py   #    持久化记忆
│   ├── skills.py   #    技能加载器
│   ├── subagent.py #    后台任务执行
│   └── tools/      #    内置工具 (包含 spawn)
├── skills/         # 🎯 捆绑技能 (github, weather, tmux...)
├── channels/       # 📱 WhatsApp 集成
├── bus/            # 🚌 消息路由
├── cron/           # ⏰ 定时任务
├── heartbeat/      # 💓 主动唤醒
├── providers/      # 🤖 LLM 提供商 (OpenRouter 等)
├── session/        # 💬 对话会话
├── config/         # ⚙️ 配置
└── cli/            # 🖥️ 命令行工具
```

## 🤝 贡献与路线图

欢迎 PR！代码库刻意保持小巧和可读。🤗

**路线图** — 选择一项并[提交 PR](https://github.com/HKUDS/nanobot/pulls)！

- [x] **语音转录** — 支持 Groq Whisper (Issue #13)
- [ ] **多模态** — 视觉和听觉 (图像, 语音, 视频)
- [ ] **长期记忆** — 永不忘记重要的上下文
- [ ] **更好的推理** — 多步规划和反思
- [ ] **更多集成** — Discord, Slack, 邮件, 日历
- [ ] **自我改进** — 从反馈和错误中学习

### 贡献者

<a href="https://github.com/HKUDS/nanobot/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=HKUDS/nanobot&max=100&columns=12" />
</a>


## ⭐ Star 历史

<div align="center">
  <a href="https://star-history.com/#HKUDS/nanobot&Date">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/svg?repos=HKUDS/nanobot&type=Date&theme=dark" />
      <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/svg?repos=HKUDS/nanobot&type=Date" />
      <img alt="Star History Chart" src="https://api.star-history.com/svg?repos=HKUDS/nanobot&type=Date" style="border-radius: 15px; box-shadow: 0 0 30px rgba(0, 217, 255, 0.3);" />
    </picture>
  </a>
</div>

<p align="center">
  <em> 感谢访问 ✨ nanobot!</em><br><br>
  <img src="https://visitor-badge.laobi.icu/badge?page_id=HKUDS.nanobot&style=for-the-badge&color=00d4ff" alt="Views">
</p>


<p align="center">
  <sub>nanobot 仅供教育、研究和技术交流使用</sub>
</p>
