<div align="center">
  <img src="nanobot_logo.png" alt="nanobot" width="500">
  <h1>nanobot: 超轻量级个人 AI 助手</h1>

  [English](README.md)｜ 
  [简体中文](README_zh.md)

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

🐈 **nanobot** 是一款**超轻量级**个人 AI 助手，灵感来自 [Clawdbot](https://github.com/openclaw/openclaw)

⚡️ 仅用 **~4,000** 行代码实现核心代理功能 — 比 Clawdbot 的 43 万行代码**小 99%**

📏 实时代码行数：**3,510 行**（随时运行 `bash core_agent_lines.sh` 验证）

## 📢 最新动态

- **2026-02-09** 💬 新增 Slack、Email 和 QQ 支持 — nanobot 现已支持多个聊天平台！
- **2026-02-08** 🔧 重构 Providers — 添加新 LLM 提供商只需 2 步！查看[这里](#providers)。
- **2026-02-07** 🚀 发布 v0.1.3.post5，支持 Qwen 及多项重要改进！查看[这里](https://github.com/HKUDS/nanobot/releases/tag/v0.1.3.post5)了解详情。
- **2026-02-06** ✨ 新增 Moonshot/Kimi 提供商、Discord 集成和增强的安全加固！
- **2026-02-05** ✨ 新增飞书频道、DeepSeek 提供商和增强的定时任务支持！
- **2026-02-04** 🚀 发布 v0.1.3.post4，支持多提供商和 Docker！查看[这里](https://github.com/HKUDS/nanobot/releases/tag/v0.1.3.post4)了解详情。
- **2026-02-03** ⚡ 集成 vLLM 支持本地 LLM，改进自然语言任务调度！
- **2026-02-02** 🎉 nanobot 正式发布！欢迎体验 🐈 nanobot！

## nanobot 核心特性：

🪶 **超轻量**：核心代理代码仅约 4,000 行 — 比 Clawdbot 小 99%。

🔬 **研究友好**：代码清晰易读，易于理解、修改和扩展进行研究。

⚡️ **极速启动**：最小化占用意味着更快的启动速度、更低的资源使用和更快的迭代。

💎 **简单易用**：一键部署，开箱即用。

## 🏗️ 架构

<p align="center">
  <img src="nanobot_arch.png" alt="nanobot architecture" width="800">
</p>

## ✨ 功能特性

<table align="center">
  <tr align="center">
    <th><p align="center">📈 7×24 实时市场分析</p></th>
    <th><p align="center">🚀 全栈软件工程师</p></th>
    <th><p align="center">📅 智能日常管理</p></th>
    <th><p align="center">📚 个人知识助手</p></th>
  </tr>
  <tr>
    <td align="center"><p align="center"><img src="case/search.gif" width="180" height="400"></p></td>
    <td align="center"><p align="center"><img src="case/code.gif" width="180" height="400"></p></td>
    <td align="center"><p align="center"><img src="case/scedule.gif" width="180" height="400"></p></td>
    <td align="center"><p align="center"><img src="case/memory.gif" width="180" height="400"></p></td>
  </tr>
  <tr>
    <td align="center">发现 · 洞察 · 趋势</td>
    <td align="center">开发 · 部署 · 扩展</td>
    <td align="center">调度 · 自动化 · 组织</td>
    <td align="center">学习 · 记忆 · 推理</td>
  </tr>
</table>

## 📦 安装

**从源码安装**（最新功能，推荐用于开发）

```bash
git clone https://github.com/HKUDS/nanobot.git
cd nanobot
pip install -e .
```

**使用 [uv](https://github.com/astral-sh/uv) 安装**（稳定，快速）

```bash
uv tool install nanobot-ai
```

**从 PyPI 安装**（稳定版）

```bash
pip install nanobot-ai
```

## 🚀 快速开始

> [!TIP]
> 在 `~/.nanobot/config.json` 中设置你的 API 密钥。
> 获取 API 密钥：[OpenRouter](https://openrouter.ai/keys) （全球）· [DashScope](https://dashscope.console.aliyun.com) （Qwen）· [Brave Search](https://brave.com/search/api/) （可选，用于网络搜索）

**1. 初始化**

```bash
nanobot onboard
```

**2. 配置** (`~/.nanobot/config.json`)

对于 OpenRouter - 推荐全球用户使用：
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
  }
}
```

**3. 开始对话**

```bash
nanobot agent -m "2+2等于几？"
```

就这么简单！2 分钟内你就有了一个可用的 AI 助手。

## 🖥️ 本地模型 (vLLM)

使用 vLLM 或任何兼容 OpenAI 的服务器运行你自己的本地模型。

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

**3. 开始对话**

```bash
nanobot agent -m "你好，来自本地 LLM！"
```

> [!TIP]
> 对于不需要身份验证的本地服务器，`apiKey` 可以是任何非空字符串。

## 💬 聊天应用

通过 Telegram、Discord、WhatsApp、飞书、钉钉、Slack、Email 或 QQ 随时随地与你的 nanobot 对话。

| 频道 | 配置难度 |
|---------|-------|
| **Telegram** | 简单（仅需 token） |
| **Discord** | 简单（bot token + intents） |
| **WhatsApp** | 中等（扫描二维码） |
| **飞书** | 中等（应用凭证） |
| **钉钉** | 中等（应用凭证） |
| **Slack** | 中等（bot + app tokens） |
| **Email** | 中等（IMAP/SMTP 凭证） |
| **QQ** | 简单（应用凭证） |

<details>
<summary><b>Telegram</b> （推荐）</summary>

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

> 你可以在 Telegram 设置中找到你的 **User ID**。显示为 `@yourUserId`。
> 复制此值（**不要带 `@` 符号**）并粘贴到配置文件中。


**3. 运行**

```bash
nanobot gateway
```

</details>

<details>
<summary><b>Discord</b></summary>

**1. 创建机器人**
- 访问 https://discord.com/developers/applications
- 创建应用程序 → Bot → 添加 Bot
- 复制 bot token

**2. 启用 intents**
- 在 Bot 设置中，启用 **MESSAGE CONTENT INTENT**
- （可选）如果你计划使用基于成员数据的允许列表，启用 **SERVER MEMBERS INTENT**

**3. 获取你的 User ID**
- Discord 设置 → 高级 → 启用**开发者模式**
- 右键点击你的头像 → **复制用户 ID**

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
- OAuth2 → URL 生成器
- 范围：`bot`
- Bot 权限：`发送消息`、`读取消息历史`
- 打开生成的邀请 URL 并将机器人添加到你的服务器

**6. 运行**

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
# 使用 WhatsApp → 设置 → 关联设备扫描二维码
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

使用 **WebSocket** 长连接 — 无需公网 IP。

**1. 创建飞书机器人**
- 访问[飞书开放平台](https://open.feishu.cn/app)
- 创建新应用 → 启用 **机器人** 能力
- **权限**：添加 `im:message`（发送消息）
- **事件**：添加 `im.message.receive_v1`（接收消息）
  - 选择 **长连接** 模式（需要先运行 nanobot 建立连接）
- 从"凭证与基础信息"获取 **App ID** 和 **App Secret**
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

> 长连接模式下 `encryptKey` 和 `verificationToken` 是可选的。
> `allowFrom`：留空允许所有用户，或添加 `[\"ou_xxx\"]` 限制访问。

**3. 运行**

```bash
nanobot gateway
```

> [!TIP]
> 飞书使用 WebSocket 接收消息 — 无需 webhook 或公网 IP！

</details>

<details>
<summary><b>QQ (QQ私聊)</b></summary>

使用 **botpy SDK** 和 WebSocket — 无需公网 IP。

**1. 创建 QQ 机器人**
- 访问 [QQ 开放平台](https://q.qq.com)
- 创建新的机器人应用
- 从"开发者设置"中获取 **AppID** 和 **Secret**

**2. 配置**

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

> `allowFrom`：留空为公开访问，或添加用户 openid 限制访问。
> 示例：`\"allowFrom\": [\"user_openid_1\", \"user_openid_2\"]`

**3. 运行**

```bash
nanobot gateway
```

> [!TIP]
> QQ 机器人目前仅支持**私聊**。群聊支持即将推出！

</details>

<details>
<summary><b>DingTalk (钉钉)</b></summary>

使用 **Stream 模式** — 无需公网 IP。

**1. 创建钉钉机器人**
- 访问 [钉钉开放平台](https://open-dev.dingtalk.com/)
- 创建新应用 → 添加 **机器人** 能力
- **配置**：
  - 打开 **Stream 模式**
- **权限**：添加发送消息的必要权限
- 从"凭证"获取 **AppKey**（Client ID）和 **AppSecret**（Client Secret）
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

> `allowFrom`：留空允许所有用户，或添加 `[\"staffId\"]` 限制访问。

**3. 运行**

```bash
nanobot gateway
```

</details>

<details>
<summary><b>Slack</b></summary>

使用 **Socket 模式** — 无需公网 URL。

**1. 创建 Slack 应用**
- 访问 [Slack API](https://api.slack.com/apps) → 创建新应用
- **OAuth & Permissions**：添加 bot 范围：`chat:write`、`reactions:write`、`app_mentions:read`
- 安装到你的工作区并复制 **Bot Token**（`xoxb-...`）
- **Socket Mode**：启用并生成具有 `connections:write` 范围的 **App-Level Token**（`xapp-...`）
- **Event Subscriptions**：订阅 `message.im`、`message.channels`、`app_mention`

**2. 配置**

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

> `groupPolicy`：`\"mention\"`（仅在 @ 提及时响应）、`\"open\"`（响应所有消息）或 `\"allowlist\"`（限制到特定频道）。
> 私聊策略默认为开放。设置 `\"dm\": {\"enabled\": false}` 禁用私聊。

**3. 运行**

```bash
nanobot gateway
```

</details>

<details>
<summary><b>Email</b></summary>

给 nanobot 一个自己的邮箱账户。它会通过 **IMAP** 轮询接收邮件并通过 **SMTP** 回复 — 就像一个个人邮件助手。

**1. 获取凭证（Gmail 示例）**
- 为你的机器人创建一个专用 Gmail 账户（例如 `my-nanobot@gmail.com`）
- 启用两步验证 → 创建[应用密码](https://myaccount.google.com/apppasswords)
- 将此应用密码同时用于 IMAP 和 SMTP

**2. 配置**

> - `consentGranted` 必须为 `true` 以允许邮箱访问。这是一个安全门 — 设置 `false` 可完全禁用。
> - `allowFrom`：留空接受任何人的邮件，或限制到特定发件人。
> - `smtpUseTls` 和 `smtpUseSsl` 默认为 `true` / `false`，这对 Gmail（端口 587 + STARTTLS）是正确的。无需显式设置。
> - 如果只想读取/分析邮件而不发送自动回复，设置 `\"autoReplyEnabled\": false`。

```json
{
  "channels": {
    "email": {
      "enabled": true,
      "consentGranted": true,
      "imapHost": "imap.gmail.com",
      "imapPort": 993,
      "imapUsername": "my-nanobot@gmail.com",
      "imapPassword": "your-app-password",
      "smtpHost": "smtp.gmail.com",
      "smtpPort": 587,
      "smtpUsername": "my-nanobot@gmail.com",
      "smtpPassword": "your-app-password",
      "fromAddress": "my-nanobot@gmail.com",
      "allowFrom": ["your-real-email@gmail.com"]
    }
  }
}
```


**3. 运行**

```bash
nanobot gateway
```

</details>

## ⚙️ 配置

配置文件：`~/.nanobot/config.json`

### Providers

> [!TIP]
> - **Groq** 通过 Whisper 提供免费的语音转文字。如果配置了，Telegram 语音消息将自动转录。
> - **Zhipu 编码计划**：如果你使用的是 Zhipu 的编码计划，请在 zhipu 提供商配置中设置 `\"apiBase\": \"https://open.bigmodel.cn/api/coding/paas/v4\"`。

| Provider | 用途 | 获取 API 密钥 |
|----------|---------|-------------|
| `openrouter` | LLM（推荐，访问所有模型） | [openrouter.ai](https://openrouter.ai) |
| `anthropic` | LLM（Claude 直连） | [console.anthropic.com](https://console.anthropic.com) |
| `openai` | LLM（GPT 直连） | [platform.openai.com](https://platform.openai.com) |
| `deepseek` | LLM（DeepSeek 直连） | [platform.deepseek.com](https://platform.deepseek.com) |
| `groq` | LLM + **语音转文字**（Whisper） | [console.groq.com](https://console.groq.com) |
| `gemini` | LLM（Gemini 直连） | [aistudio.google.com](https://aistudio.google.com) |
| `aihubmix` | LLM（API 网关，访问所有模型） | [aihubmix.com](https://aihubmix.com) |
| `dashscope` | LLM（Qwen） | [dashscope.console.aliyun.com](https://dashscope.console.aliyun.com) |
| `moonshot` | LLM（Moonshot/Kimi） | [platform.moonshot.cn](https://platform.moonshot.cn) |
| `zhipu` | LLM（Zhipu GLM） | [open.bigmodel.cn](https://open.bigmodel.cn) |
| `vllm` | LLM（本地，任何兼容 OpenAI 的服务器） | — |

<details>
<summary><b>添加新提供商（开发者指南）</b></summary>

nanobot 使用**提供商注册表**（`nanobot/providers/registry.py`）作为唯一真实来源。
添加新提供商只需 **2 步** — 无需触及 if-elif 链。

**步骤 1.** 在 `nanobot/providers/registry.py` 的 `PROVIDERS` 中添加一个 `ProviderSpec` 条目：

```python
ProviderSpec(
    name="myprovider",                   # 配置字段名
    keywords=("myprovider", "mymodel"),  # 模型名关键字用于自动匹配
    env_key="MYPROVIDER_API_KEY",        # LiteLLM 的环境变量
    display_name="My Provider",          # 显示在 `nanobot status` 中
    litellm_prefix="myprovider",         # 自动前缀：model → myprovider/model
    skip_prefixes=("myprovider/","),     # 不重复前缀
)
```

**步骤 2.** 在 `nanobot/config/schema.py` 中为 `ProvidersConfig` 添加一个字段：

```python
class ProvidersConfig(BaseModel):
    ...
    myprovider: ProviderConfig = ProviderConfig()
```

就这样！环境变量、模型前缀、配置匹配和 `nanobot status` 显示都会自动工作。

**常用 `ProviderSpec` 选项：**

| 字段 | 描述 | 示例 |
|-------|-------------|---------|
| `litellm_prefix` | 为 LiteLLM 自动添加模型名称前缀 | `\"dashscope\"` → `dashscope/qwen-max` |
| `skip_prefixes` | 如果模型已以此开头，则不添加前缀 | `(\"dashscope/\", \"openrouter/\")` |
| `env_extras` | 要设置的其他环境变量 | `((\"ZHIPUAI_API_KEY\", \"{api_key}\"),)` |
| `model_overrides` | 每模型参数覆盖 | `((\"kimi-k2.5\", {\"temperature\": 1.0}),)` |
| `is_gateway` | 可以路由任何模型（如 OpenRouter） | `True` |
| `detect_by_key_prefix` | 通过 API 密钥前缀检测网关 | `\"sk-or-\"` |
| `detect_by_base_keyword` | 通过 API base URL 检测网关 | `\"openrouter\"` |
| `strip_model_prefix` | 在重新添加前缀之前去除现有前缀 | `True`（用于 AiHubMix） |

</details>


### 安全性

> 对于生产部署，在配置中设置 `\"restrictToWorkspace\": true` 以沙盒化代理。

| 选项 | 默认值 | 描述 |
|--------|---------|-------------|
| `tools.restrictToWorkspace` | `false` | 为 `true` 时，将**所有**代理工具（shell、文件读/写/编辑、列表）限制到工作区目录。防止路径遍历和超出范围的访问。 |
| `channels.*.allowFrom` | `[]`（允许所有） | 用户 ID 白名单。空 = 允许所有人；非空 = 只有列出的用户可以交互。 |


## CLI 参考

| 命令 | 描述 |
|---------|-------------|
| `nanobot onboard` | 初始化配置和工作区 |
| `nanobot agent -m "..."` | 与代理对话 |
| `nanobot agent` | 交互式聊天模式 |
| `nanobot agent --no-markdown` | 显示纯文本回复 |
| `nanobot agent --logs` | 聊天期间显示运行时日志 |
| `nanobot gateway` | 启动网关 |
| `nanobot status` | 显示状态 |
| `nanobot channels login` | 链接 WhatsApp（扫描二维码） |
| `nanobot channels status` | 显示频道状态 |

交互模式退出命令：`exit`、`quit`、`/exit`、`/quit`、`:q` 或 `Ctrl+D`。

<details>
<summary><b>定时任务（Cron）</b></summary>

```bash
# 添加任务
nanobot cron add --name "daily" --message "早上好！" --cron "0 9 * * *"
nanobot cron add --name "hourly" --message "检查状态" --every 3600

# 列出任务
nanobot cron list

# 删除任务
nanobot cron remove <job_id>
```

</details>

## 🐳 Docker

> [!TIP]
> `-v ~/.nanobot:/root/.nanobot` 标志将本地配置目录挂载到容器中，因此你的配置和工作区在容器重启后仍然存在。

在容器中构建和运行 nanobot：

```bash
# 构建镜像
docker build -t nanobot .

# 初始化配置（仅第一次）
docker run -v ~/.nanobot:/root/.nanobot --rm nanobot onboard

# 在主机上编辑配置以添加 API 密钥
vim ~/.nanobot/config.json

# 运行网关（连接到 Telegram/WhatsApp）
docker run -v ~/.nanobot:/root/.nanobot -p 18790:18790 nanobot gateway

# 或运行单个命令
docker run -v ~/.nanobot:/root/.nanobot --rm nanobot agent -m "你好！"
docker run -v ~/.nanobot:/root/.nanobot --rm nanobot status
```

## 📁 项目结构

```
nanobot/
├── agent/          # 🧠 核心代理逻辑
│   ├── loop.py     #    代理循环（LLM ↔ 工具执行）
│   ├── context.py  #    提示构建器
│   ├── memory.py   #    持久化记忆
│   ├── skills.py   #    技能加载器
│   ├── subagent.py #    后台任务执行
│   └── tools/      #    内置工具（包括 spawn）
├── skills/         # 🎯 打包的技能（github、weather、tmux...）
├── channels/       # 📱 WhatsApp 集成
├── bus/            # 🚌 消息路由
├── cron/           # ⏰ 定时任务
├── heartbeat/      # 💓 主动唤醒
├── providers/      # 🤖 LLM 提供商（OpenRouter 等）
├── session/        # 💬 对话会话
├── config/         # ⚙️ 配置
└── cli/            # 🖥️ 命令
```

## 🤝 贡献与路线图

欢迎 PR！代码库故意保持小巧和易读。🤗

**路线图** — 选择一项并[提交 PR](https://github.com/HKUDS/nanobot/pulls)！

- [x] **语音转文字** — 支持 Groq Whisper（问题 #13）
- [ ] **多模态** — 看见和听见（图像、语音、视频）
- [ ] **长期记忆** — 永不忘记重要上下文
- [ ] **更好的推理** — 多步规划和反思
- [ ] **更多集成** — 日历等
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
  <em> 感谢访问 ✨ nanobot！</em><br><br>
  <img src="https://visitor-badge.laobi.icu/badge?page_id=HKUDS.nanobot&style=for-the-badge&color=00d4ff" alt="Views">
</p>


<p align="center">
  <sub>nanobot 仅供教育、研究和技术交流目的使用</sub>
</p>
