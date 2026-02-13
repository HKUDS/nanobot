<div align="center">
  <img src="nanobot_logo.png" alt="nanobot" width="500">
  <h1>nanobot: 超轻量级个人 AI 助手</h1>
  <p align="center">
    <a href="README.md">English</a> |
    <a href="README_CN.md">简体中文</a>
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

🐈 **nanobot** 是一个受 [Clawdbot](https://github.com/openclaw/openclaw) 启发的 **超轻量级** 个人 AI 助手。

⚡️ 仅需 **~4,000** 行代码即可提供核心代理功能 —— 比 Clawdbot 的 43万+ 行代码 **小 99%**。

📏 实时代码行数：**3,510 行** (随时运行 `bash core_agent_lines.sh` 验证)

## 📢 新闻

- **2026-02-10** 🎉 发布 v0.1.3.post6，包含多项改进！查看 [发布说明](https://github.com/HKUDS/nanobot/releases/tag/v0.1.3.post6) 和我们的 [路线图](https://github.com/HKUDS/nanobot/discussions/431)。
- **2026-02-09** 💬 新增 Slack, Email, 和 QQ 支持 —— nanobot 现在支持多种聊天平台！
- **2026-02-08** 🔧 重构了提供商——添加新的 LLM 提供商现在只需 2 个简单步骤！查看 [这里](#providers)。
- **2026-02-07** 🚀 发布 v0.1.3.post5，支持 Qwen 及多项重要改进！详情请查看 [这里](https://github.com/HKUDS/nanobot/releases/tag/v0.1.3.post5)。
- **2026-02-06** ✨ 新增 Moonshot/Kimi 提供商、Discord 集成，并增强了安全加固！
- **2026-02-05** ✨ 新增飞书 (Feishu) 渠道、DeepSeek 提供商，以及更好的定时任务支持！
- **2026-02-04** 🚀 发布 v0.1.3.post4，支持多提供商和 Docker！详情请查看 [发布说明](https://github.com/HKUDS/nanobot/releases/tag/v0.1.3.post4)。
- **2026-02-03** ⚡ 集成 vLLM 以支持本地 LLM，并改进了自然语言任务调度！
- **2026-02-02** 🎉 nanobot 正式发布！欢迎试用 🐈 nanobot！

## nanobot 的主要特性：

🪶 **超轻量级**：核心功能仅需 ~4,000 行代码 —— 比 Clawdbot 小 99%。

🔬 **适合研究**：代码整洁、可读性强，易于理解、修改和扩展，适合研究用途。

⚡️ **闪电般快速**：极小的占用空间意味着启动更快、资源占用更低、迭代更迅速。

💎 **易于使用**：一键部署，开箱即用。

## 🏗️ 架构

<p align="center">
  <img src="nanobot_arch.png" alt="nanobot architecture" width="800">
</p>

## ✨ 功能

<table align="center">
  <tr align="center">
    <th><p align="center">📈 24/7 实时市场分析</p></th>
    <th><p align="center">🚀 全栈软件工程师</p></th>
    <th><p align="center">📅 智能日常事务管理</p></th>
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
    <td align="center">调度 • 自动化 • 组织</td>
    <td align="center">学习 • 记忆 • 推理</td>
  </tr>
</table>

## 📦 安装

**从源码安装**（最新特性，推荐用于开发）

```bash
git clone https://github.com/HKUDS/nanobot.git
cd nanobot
pip install -e .
```

**使用 [uv](https://github.com/astral-sh/uv) 安装**（稳定，快速）

```bash
uv tool install nanobot-ai
```

**从 PyPI 安装**（稳定）

```bash
pip install nanobot-ai
```

## 🚀 快速开始

> [!TIP]
> 在 `~/.nanobot/config.json` 中设置您的 API 密钥。
> 获取 API 密钥：[OpenRouter](https://openrouter.ai/keys) (Global) · [DashScope](https://dashscope.console.aliyun.com) (Qwen) · [Brave Search](https://brave.com/search/api/) (可选，用于网络搜索)

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

就是这样！您在 2 分钟内就有了一个工作的 AI 助手。

## 🖥️ 本地模型 (vLLM)

使用 vLLM 或任何兼容 OpenAI 的服务器运行 nanobot 和您自己的本地模型。

**1. 启动您的 vLLM 服务器**

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
nanobot agent -m "Hello from my local LLM!"
```

> [!TIP]
> 对于不需要身份验证的本地服务器，`apiKey` 可以是任何非空字符串。

## 💬 聊天应用

随时随地通过 Telegram、WhatsApp 或飞书与您的 nanobot 交谈。

| 渠道 | 设置 |
|---------|-------|
| **Telegram** | 简单（只需一个 token） |
| **Discord** | 简单（bot token + intents） |
| **WhatsApp** | 中等（扫描二维码） |
| **Feishu (飞书)** | 中等（应用凭据） |
| **Mochat** | 中等（claw token + websocket） |
| **DingTalk (钉钉)** | 中等（应用凭据） |
| **Slack** | 中等（bot + app tokens） |
| **Email (邮件)** | 中等（IMAP/SMTP 凭据） |
| **QQ** | 简单（应用凭据） |

<details>
<summary><b>Telegram</b> (推荐)</summary>

**1. 创建一个机器人**
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

> 从 Telegram 上的 `@userinfobot` 获取您的用户 ID。

**3. 运行**

```bash
nanobot gateway
```

</details>

<details>
<summary><b>Mochat (Claw IM)</b></summary>

默认使用 **Socket.IO WebSocket**，并支持 HTTP 轮询回退。

**1. 让 nanobot 为您设置 Mochat**

只需发送此消息给 nanobot（将 `xxx@xxx` 替换为您的真实邮箱）：

```
Read https://raw.githubusercontent.com/HKUDS/MoChat/refs/heads/main/skills/nanobot/skill.md and register on MoChat. My Email account is xxx@xxx Bind me as your owner and DM me on MoChat.
```

nanobot 将自动注册、配置 `~/.nanobot/config.json` 并连接到 Mochat。

**2. 重启网关**

```bash
nanobot gateway
```

就是这样 —— nanobot 处理剩下的事情！

<br>

<details>
<summary>手动配置（高级）</summary>

如果您更喜欢手动配置，请将以下内容添加到 `~/.nanobot/config.json`：

> 请保密 `claw_token`。它只能在 `X-Claw-Token` 标头中发送到您的 Mochat API 端点。

```json
{
  "channels": {
    "mochat": {
      "enabled": true,
      "base_url": "https://mochat.io",
      "socket_url": "https://mochat.io",
      "socket_path": "/socket.io",
      "claw_token": "claw_xxx",
      "agent_user_id": "6982abcdef",
      "sessions": ["*"],
      "panels": ["*"],
      "reply_delay_mode": "non-mention",
      "reply_delay_ms": 120000
    }
  }
}
```

</details>

</details>

<details>
<summary><b>Discord</b></summary>

**1. 创建一个机器人**
- 前往 https://discord.com/developers/applications
- 创建一个应用 → Bot → Add Bot
- 复制 bot token

**2. 启用 intents**
- 在 Bot 设置中，启用 **MESSAGE CONTENT INTENT**
- (可选) 启用 **SERVER MEMBERS INTENT** 如果您计划基于成员数据使用白名单

**3. 获取您的用户 ID**
- Discord 设置 → 高级 → 启用 **开发者模式**
- 右键点击您的头像 → **复制用户 ID**

**4. 配置**

```json
{
  "channels": {
    "discord": {
      "enabled": true,
      "token": "YOUR_BOT_TOKEN",
      "allowFrom": ["YOUR_USER_ID"]
    }
  }
}
```

**5. 邀请机器人**
- OAuth2 → URL Generator
- Scopes: `bot`
- Bot Permissions: `Send Messages`, `Read Message History`
- 打开生成的邀请链接并将机器人添加到您的服务器

**6. 运行**

```bash
nanobot gateway
```

</details>

<details>
<summary><b>WhatsApp</b></summary>

需要 **Node.js ≥18**。

**1. 连接设备**

```bash
nanobot channels login
# 使用 WhatsApp 扫描二维码 → 设置 → 已连接设备
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

**3. 运行**（两个终端）

```bash
# 终端 1
nanobot channels login

# 终端 2
nanobot gateway
```

</details>

<details>
<summary><b>Feishu (飞书)</b></summary>

使用 **WebSocket** 长连接 —— 无需公网 IP。

```bash
pip install nanobot-ai[feishu]
```

**1. 创建一个飞书机器人**
- 访问 [飞书开放平台](https://open.feishu.cn/app)
- 创建新应用 → 启用 **机器人** 能力
- **权限**：添加 `im:message`（发送消息）
- **事件**：添加 `im.message.receive_v1`（接收消息）
  - 选择 **长连接** 模式（需要先运行 nanobot 以建立连接）
- 从“凭证与基础信息”获取 **App ID** 和 **App Secret**
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

> 对于长连接模式，`encryptKey` 和 `verificationToken` 是可选的。
> `allowFrom`：留空以允许所有用户，或添加 `["ou_xxx"]` 以限制访问。

**3. 运行**

```bash
nanobot gateway
```

> [!TIP]
> 飞书使用 WebSocket 接收消息 —— 不需要 webhook 或公网 IP！

</details>

<details>
<summary><b>QQ (QQ单聊)</b></summary>

使用 **botpy SDK** 和 WebSocket —— 无需公网 IP。目前仅支持 **私聊**。

**1. 注册并创建机器人**
- 访问 [QQ 开放平台](https://q.qq.com) → 注册为开发者（个人或企业）
- 创建一个新的机器人应用
- 前往 **开发设置** → 复制 **AppID** 和 **AppSecret**

**2. 设置沙箱进行测试**
- 在机器人管理后台，找到 **沙箱配置**
- 在 **在消息列表配置** 下，点击 **添加成员** 并添加您自己的 QQ 号
- 添加完成后，使用手机 QQ 扫描机器人的二维码 → 打开机器人资料页 → 点击 "发消息" 开始聊天

**3. 配置**

> - `allowFrom`: 留空以允许公众访问，或添加用户 openid 以限制访问。当用户给机器人发消息时，您可以在 nanobot 日志中找到 openid。
> - 对于生产环境：在机器人控制台提交审核并发布。完整的发布流程请参阅 [QQ 机器人文档](https://bot.q.qq.com/wiki/)。

```json
{
  "channels": {
    "qq": {
      "enabled": true,
      "appId": "YOUR_APP_ID",
      "secret": "YOUR_APP_SECRET",
      "allowFrom": []
    }
  }
}
```

**4. 运行**

```bash
nanobot gateway
```

现在从 QQ 给机器人发消息 —— 它应该会回复！

</details>

<details>
<summary><b>DingTalk (钉钉)</b></summary>

使用 **Stream 模式** —— 无需公网 IP。

**1. 创建一个钉钉机器人**
- 访问 [钉钉开放平台](https://open-dev.dingtalk.com/)
- 创建新应用 -> 添加 **机器人** 能力
- **配置**：
  - 开启 **Stream 模式**
- **权限**：添加发送消息所需的必要权限
- 从“凭证与基础信息”获取 **AppKey** (Client ID) 和 **AppSecret** (Client Secret)
- 发布应用

**2. 配置**

```json
{
  "channels": {
    "dingtalk": {
      "enabled": true,
      "clientId": "YOUR_APP_KEY",
      "clientSecret": "YOUR_APP_SECRET",
      "allowFrom": []
    }
  }
}
```

> `allowFrom`：留空以允许所有用户，或添加 `["staffId"]` 以限制访问。

**3. 运行**

```bash
nanobot gateway
```

</details>

<details>
<summary><b>Slack</b></summary>

使用 **Socket Mode** —— 无需公网 URL。

**1. 创建 Slack 应用**
- 前往 [Slack API](https://api.slack.com/apps) → **Create New App** → "From scratch"
- 选择名称和工作区

**2. 配置应用**
- **Socket Mode**: 开启 → 生成具有 `connections:write` 权限的 **App-Level Token** → 复制它 (`xapp-...`)
- **OAuth & Permissions**: 添加 bot scopes: `chat:write`, `reactions:write`, `app_mentions:read`
- **Event Subscriptions**: 开启 → 订阅 bot events: `message.im`, `message.channels`, `app_mention` → Save Changes
- **App Home**: 滚动到 **Show Tabs** → 启用 **Messages Tab** → 勾选 **"Allow users to send Slash commands and messages from the messages tab"**
- **Install App**: 点击 **Install to Workspace** → 授权 → 复制 **Bot Token** (`xoxb-...`)

**3. 配置 nanobot**

```json
{
  "channels": {
    "slack": {
      "enabled": true,
      "botToken": "xoxb-...",
      "appToken": "xapp-...",
      "groupPolicy": "mention"
    }
  }
}
```

**4. 运行**

```bash
nanobot gateway
```

直接私信机器人或在频道中 @ 它 —— 它应该会回复！

> [!TIP]
> - `groupPolicy`: `"mention"` (默认 —— 仅在被 @ 时回复), `"open"` (回复所有频道消息), 或 `"allowlist"` (限制在特定频道).
> - DM 策略默认为 open。设置 `"dm": {"enabled": false}` 以禁用私信。

</details>

<details>
<summary><b>Email</b></summary>

使用 **IMAP** 轮询接收邮件 + **SMTP** 发送邮件。在访问邮箱数据前需要明确授权。

**1. 获取凭证 (Gmail 示例)**
- 在 Google 账户安全中启用两步验证
- 创建一个 [应用专用密码](https://myaccount.google.com/apppasswords)
- 将此应用专用密码用于 IMAP 和 SMTP

**2. 配置**

> [!TIP]
> 设置 `"autoReplyEnabled": false` 如果您只想读取/分析邮件而不发送自动回复。

```json
{
  "channels": {
    "email": {
      "enabled": true,
      "consentGranted": true,
      "imapHost": "imap.gmail.com",
      "imapPort": 993,
      "imapUsername": "you@gmail.com",
      "imapPassword": "your-app-password",
      "imapUseSsl": true,
      "smtpHost": "smtp.gmail.com",
      "smtpPort": 587,
      "smtpUsername": "you@gmail.com",
      "smtpPassword": "your-app-password",
      "smtpUseTls": true,
      "fromAddress": "you@gmail.com",
      "allowFrom": ["trusted@example.com"]
    }
  }
}
```

> `consentGranted`: 必须为 `true` 以允许邮箱访问。设置为 `false` 以完全禁用读取和发送。
> `allowFrom`: 留空以接受任何人的邮件，或限制为特定发件人地址。

**3. 运行**

```bash
nanobot gateway
```

</details>

## ⚙️ 配置

配置文件：`~/.nanobot/config.json`

### 提供商 (Providers)

> [!NOTE]
> Groq 提供免费的 Whisper 语音转录。如果配置了，Telegram 语音消息将被自动转录。

| 提供商 | 用途 | 获取 API 密钥 |
|----------|---------|-------------|
| `openrouter` | LLM (推荐，访问所有模型) | [openrouter.ai](https://openrouter.ai) |
| `anthropic` | LLM (Claude 直连) | [console.anthropic.com](https://console.anthropic.com) |
| `openai` | LLM (GPT 直连) | [platform.openai.com](https://platform.openai.com) |
| `deepseek` | LLM (DeepSeek 直连) | [platform.deepseek.com](https://platform.deepseek.com) |
| `groq` | LLM + **语音转录** (Whisper) | [console.groq.com](https://console.groq.com) |
| `gemini` | LLM (Gemini 直连) | [aistudio.google.com](https://aistudio.google.com) |
| `aihubmix` | LLM (API 网关，访问所有模型) | [aihubmix.com](https://aihubmix.com) |
| `dashscope` | LLM (Qwen) | [dashscope.console.aliyun.com](https://dashscope.console.aliyun.com) |
| `moonshot` | LLM (Moonshot/Kimi) | [platform.moonshot.cn](https://platform.moonshot.cn) |
| `zhipu` | LLM (Zhipu GLM) | [open.bigmodel.cn](https://open.bigmodel.cn) |
| `vllm` | LLM (本地，任何兼容 OpenAI 的服务器) | — |

<details>
<summary><b>添加新提供商 (开发者指南)</b></summary>

nanobot 使用 **提供商注册表** (`nanobot/providers/registry.py`) 作为单一事实来源。
添加新提供商仅需 **2 步** —— 无需修改 if-elif 链。

**第 1 步。** 在 `nanobot/providers/registry.py` 的 `PROVIDERS` 中添加 `ProviderSpec` 条目：

```python
ProviderSpec(
    name="myprovider",                   # 配置字段名称
    keywords=("myprovider", "mymodel"),  # 用于自动匹配的模型名称关键字
    env_key="MYPROVIDER_API_KEY",        # LiteLLM 的环境变量
    display_name="My Provider",          # 在 `nanobot status` 中显示
    litellm_prefix="myprovider",         # 自动前缀：model → myprovider/model
    skip_prefixes=("myprovider/",),      # 不重复添加前缀
)
```

**第 2 步。** 在 `nanobot/config/schema.py` 的 `ProvidersConfig` 中添加字段：

```python
class ProvidersConfig(BaseModel):
    ...
    myprovider: ProviderConfig = ProviderConfig()
```

就是这样！环境变量、模型前缀、配置匹配和 `nanobot status` 显示都将自动工作。

**常用 `ProviderSpec` 选项：**

| 字段 | 描述 | 示例 |
|-------|-------------|---------|
| `litellm_prefix` | LiteLLM 的自动模型前缀 | `"dashscope"` → `dashscope/qwen-max` |
| `skip_prefixes` | 如果模型已以这些开头，则不加前缀 | `("dashscope/", "openrouter/")` |
| `env_extras` | 要设置的额外环境变量 | `(("ZHIPUAI_API_KEY", "{api_key}"),)` |
| `model_overrides` | 每个模型的参数覆盖 | `(("kimi-k2.5", {"temperature": 1.0}),)` |
| `is_gateway` | 可以路由任何模型（如 OpenRouter） | `True` |
| `detect_by_key_prefix` | 通过 API 密钥前缀检测网关 | `"sk-or-"` |
| `detect_by_base_keyword` | 通过 API 基础 URL 检测网关 | `"openrouter"` |
| `strip_model_prefix` | 重新添加前缀前剥离现有前缀 | `True` (用于 AiHubMix) |

</details>


### 安全

> [!TIP]
> 对于生产部署，在配置中设置 `"restrictToWorkspace": true` 以沙盒化代理。

| 选项 | 默认值 | 描述 |
|--------|---------|-------------|
| `tools.restrictToWorkspace` | `false` | 当为 `true` 时，限制 **所有** 代理工具（shell, 文件读/写/编辑, 列表）在工作区目录内。防止路径遍历和越权访问。 |
| `channels.*.allowFrom` | `[]` (允许所有) | 用户 ID 白名单。空 = 允许所有人；非空 = 仅允许列出的用户交互。 |


<details>
<summary><b>完整配置示例</b></summary>

```json
{
  "agents": {
    "defaults": {
      "model": "anthropic/claude-opus-4-5"
    }
  },
  "providers": {
    "openrouter": {
      "apiKey": "sk-or-v1-xxx"
    },
    "groq": {
      "apiKey": "gsk_xxx"
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
| `nanobot agent -m "..."` | 与代理聊天 |
| `nanobot agent` | 交互式聊天模式 |
| `nanobot agent --no-markdown` | 显示纯文本回复 |
| `nanobot agent --logs` | 在聊天期间显示运行时日志 |
| `nanobot gateway` | 启动网关 |
| `nanobot status` | 显示状态 |
| `nanobot channels login` | 连接 WhatsApp（扫描二维码） |
| `nanobot channels status` | 显示渠道状态 |

<details>
<summary><b>定时任务 (Cron)</b></summary>

```bash
# 添加任务
nanobot cron add --name "daily" --message "Good morning!" --cron "0 9 * * *"
nanobot cron add --name "hourly" --message "Check status" --every 3600

# 列出任务
nanobot cron list

# 移除任务
nanobot cron remove <job_id>
```

</details>

## 🐳 Docker

> [!TIP]
> `-v ~/.nanobot:/root/.nanobot` 标志将您的本地配置目录挂载到容器中，因此您的配置和工作区在容器重启后仍然存在。

构建并在容器中运行 nanobot：

```bash
# 构建镜像
docker build -t nanobot .

# 初始化配置（仅第一次）
docker run -v ~/.nanobot:/root/.nanobot --rm nanobot onboard

# 在宿主机上编辑配置以添加 API 密钥
vim ~/.nanobot/config.json

# 运行网关（连接到 Telegram/WhatsApp）
docker run -v ~/.nanobot:/root/.nanobot -p 18790:18790 nanobot gateway

# 或者运行单个命令
docker run -v ~/.nanobot:/root/.nanobot --rm nanobot agent -m "Hello!"
docker run -v ~/.nanobot:/root/.nanobot --rm nanobot status
```

## 📁 项目结构

```
nanobot/
├── agent/          # 🧠 核心代理逻辑
│   ├── loop.py     #    代理循环（LLM ↔ 工具执行）
│   ├── context.py  #    提示词构建器
│   ├── memory.py   #    持久记忆
│   ├── skills.py   #    技能加载器
│   ├── subagent.py #    后台任务执行
│   └── tools/      #    内置工具（包括 spawn）
├── skills/         # 🎯 捆绑的技能（github, weather, tmux...）
├── channels/       # 📱 聊天渠道集成
├── bus/            # 🚌 消息路由
├── cron/           # ⏰ 定时任务
├── heartbeat/      # 💓 主动唤醒
├── providers/      # 🤖 LLM 提供商 (OpenRouter 等)
├── session/        # 💬 对话会话
├── config/         # ⚙️ 配置
└── cli/            # 🖥️ 命令
```

## 🤝 贡献 & 路线图

欢迎提交 PR！代码库特意保持小巧和可读。🤗

**路线图** — 挑选一项并 [提交 PR](https://github.com/HKUDS/nanobot/pulls)！

- [x] **语音转录** — 支持 Groq Whisper (Issue #13)
- [ ] **多模态** — 视觉和听觉（图像、语音、视频）
- [ ] **长期记忆** — 永远不会忘记重要的上下文
- [ ] **更好的推理** — 多步规划和反思
- [ ] **更多集成** — 日历等
- [ ] **自我进化** — 从反馈和错误中学习

### 贡献者

<a href="https://github.com/HKUDS/nanobot/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=HKUDS/nanobot&max=100&columns=12&updated=20260210" alt="Contributors" />
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
  <em> 感谢访问 ✨ nanobot！</em><br><br>
  <img src="https://visitor-badge.laobi.icu/badge?page_id=HKUDS.nanobot&style=for-the-badge&color=00d4ff" alt="Views">
</p>


<p align="center">
  <sub>nanobot 仅供教育、研究和技术交流目的使用</sub>
</p>
