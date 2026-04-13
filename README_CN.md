<div align="center">
  <img src="nanobot_logo.png" alt="nanobot" width="500">
  <h1>nanobot: 超轻量级个人 AI 助手</h1>
  <p>
    <a href="https://pypi.org/project/nanobot-ai/"><img src="https://img.shields.io/pypi/v/nanobot-ai" alt="PyPI"></a>
    <a href="https://pepy.tech/project/nanobot-ai"><img src="https://static.pepy.tech/badge/nanobot-ai" alt="Downloads"></a>
    <img src="https://img.shields.io/badge/python-≥3.11-blue" alt="Python">
    <img src="https://img.shields.io/badge/license-MIT-green" alt="License">
    <a href="./COMMUNICATION.md"><img src="https://img.shields.io/badge/Feishu-Group-E9DBFC?style=flat&logo=feishu&logoColor=white" alt="飞书"></a>
    <a href="./COMMUNICATION.md"><img src="https://img.shields.io/badge/WeChat-Group-C5EAB4?style=flat&logo=wechat&logoColor=white" alt="微信"></a>
    <a href="https://discord.gg/MnCvHqpUGB"><img src="https://img.shields.io/badge/Discord-Community-5865F2?style=flat&logo=discord&logoColor=white" alt="Discord"></a>
  </p>
</div>

🐈 **nanobot** 是一款受 [OpenClaw](https://github.com/openclaw/openclaw) 启发的**超轻量级**个人 AI 助手。

⚡️ 用比 OpenClaw 少 **99% 的代码**实现核心 Agent 功能。

📏 实时代码行数：随时运行 `bash core_agent_lines.sh` 验证。

## 📢 新闻动态

- **2026-03-08** 🚀 发布 **v0.1.4.post4** — 可靠性增强版本，带来更安全的默认设置、更好的多实例支持、更稳固的 MCP，以及重大改进的通道和提供商。详见[发布说明](https://github.com/HKUDS/nanobot/releases/tag/v0.1.4.post4)。
- **2026-03-07** 🚀 Azure OpenAI 提供商、WhatsApp 媒体支持、QQ 群聊，以及更多 Telegram/飞书优化。
- **2026-03-06** 🪄 更轻量的提供商、更智能的媒体处理，以及更稳固的内存和 CLI 兼容性。
- **2026-03-05** ⚡️ Telegram 草稿流式传输、MCP SSE 支持，以及更广泛的通道可靠性修复。
- **2026-03-04** 🛠️ 依赖清理、更安全的文件读取，以及更多测试和 Cron 修复。
- **2026-03-03** 🧠 更清晰的用户消息合并、更安全的多模态保存，以及更强的 Cron 保护。
- **2026-03-02** 🛡️ 更安全的默认访问控制、更稳固的 Cron 重新加载，以及更简洁的 Matrix 媒体处理。
- **2026-03-01** 🌐 Web 代理支持、更智能的 Cron 提醒，以及飞书富文本解析改进。
- **2026-02-28** 🚀 发布 **v0.1.4.post3** — 更清爽的上下文、加固的会话历史，以及更智能的 Agent。详见[发布说明](https://github.com/HKUDS/nanobot/releases/tag/v0.1.4.post3)。
- **2026-02-27** 🧠 实验性思考模式支持、钉钉媒体消息，以及飞书和 QQ 通道修复。
- **2026-02-26** 🛡️ 会话污染修复、WhatsApp 去重、Windows 路径保护，以及 Mistral 兼容性。

<details>
<summary>早期新闻</summary>

- **2026-02-25** 🧹 新 Matrix 通道、更清爽的会话上下文、自动工作区模板同步。
- **2026-02-24** 🚀 发布 **v0.1.4.post2** — 可靠性聚焦版本，重新设计的心跳、提示缓存优化，以及加固的提供商和通道稳定性。详见[发布说明](https://github.com/HKUDS/nanobot/releases/tag/v0.1.4.post2)。
- **2026-02-23** 🔧 虚拟工具调用心跳、提示缓存优化、Slack mrkdwn 修复。
- **2026-02-22** 🛡️ Slack 线程隔离、Discord 输入修复、Agent 可靠性改进。
- **2026-02-21** 🎉 发布 **v0.1.4.post1** — 新提供商、跨通道媒体支持，以及重大稳定性改进。详见[发布说明](https://github.com/HKUDS/nanobot/releases/tag/v0.1.4.post1)。
- **2026-02-20** 🐦 飞书现在可以接收来自用户的多模态文件。底层内存更可靠。
- **2026-02-19** ✨ Slack 现在可以发送文件、Discord 拆分长消息，子代理在 CLI 模式下工作。
- **2026-02-18** ⚡️ nanobot 现在支持火山引擎、MCP 自定义认证头，以及 Anthropic 提示缓存。
- **2026-02-17** 🎉 发布 **v0.1.4** — MCP 支持、进度流式传输、新提供商，以及多通道改进。详见[发布说明](https://github.com/HKUDS/nanobot/releases/tag/v0.1.4)。
- **2026-02-16** 🦞 nanobot 现已集成 [ClawHub](https://clawhub.ai) 技能 — 搜索和安装公共 Agent 技能。
- **2026-02-15** 🔑 nanobot 现在支持带 OAuth 登录的 OpenAI Codex 提供商。
- **2026-02-14** 🔌 nanobot 现在支持 MCP！详情见 [MCP 部分](#mcp-模型上下文协议)。
- **2026-02-13** 🎉 发布 **v0.1.3.post7** — 包含安全加固和多项改进。**请升级到最新版本以解决安全问题**。详见[发布说明](https://github.com/HKUDS/nanobot/releases/tag/v0.1.3.post7)。
- **2026-02-12** 🧠 重新设计的内存系统 — 更少代码、更可靠。参与[讨论](https://github.com/HKUDS/nanobot/discussions/566)！
- **2026-02-11** ✨ 增强的 CLI 体验并添加了 MiniMax 支持！
- **2026-02-10** 🎉 发布 **v0.1.3.post6** 带来改进！查看更新[说明](https://github.com/HKUDS/nanobot/releases/tag/v0.1.3.post6)和我们的[路线图](https://github.com/HKUDS/nanobot/discussions/431)。
- **2026-02-09** 💬 添加了 Slack、Email 和 QQ 支持 — nanobot 现在支持多个聊天平台！
- **2026-02-08** 🔧 重构提供商 — 现在添加新的 LLM 提供商只需 2 个简单步骤！查看[这里](#providers)。
- **2026-02-07** 🚀 发布 **v0.1.3.post5**，支持通义及多项关键改进！详情[见这里](https://github.com/HKUDS/nanobot/releases/tag/v0.1.3.post5)。
- **2026-02-06** ✨ 添加 Moonshot/Kimi 提供商、Discord 集成，以及增强的安全加固！
- **2026-02-05** ✨ 添加飞书通道、DeepSeek 提供商，以及增强的定时任务支持！
- **2026-02-04** 🚀 发布 **v0.1.3.post4**，支持多提供商和 Docker！详情[见这里](https://github.com/HKUDS/nanobot/releases/tag/v0.1.3.post4)。
- **2026-02-03** ⚡ 集成 vLLM 支持本地 LLM，改进自然语言任务调度！
- **2026-02-02** 🎉 nanobot 正式发布！欢迎试用 🐈 nanobot！

</details>

## nanobot 核心特性：

🪶 **超轻量**：仅约 4,000 行核心 Agent 代码 — 比 Clawdbot 小 99%。

🔬 **研究友好**：代码清晰易读，易于理解、修改和扩展进行研究。

⚡️ **闪电般快速**：极小的占用空间意味着更快的启动、更低的资源使用和更快的迭代。

💎 **易于使用**：一键部署即可开始使用。

## 🏗️ 架构

<p align="center">
  <img src="nanobot_arch.png" alt="nanobot architecture" width="800">
</p>

## 后台 Subagent

nanobot 仍然以单主 Agent 为核心，但现在可以把独立任务派给后台 subagent 处理。

- `spawn` 更适合不会阻塞下一步的独立工作。
- 调用 `spawn` 时，建议尽量补齐 `task`、`goal`、`constraints`、`relevant_paths`、`done_when`，让 subagent 拿到清晰的任务契约。
- subagent 的结果现在会先以结构化 metadata 回流，再由主 Agent 总结给用户。
- Heartbeat 和 Cron 的通知判断也会优先利用这些结构化结果，因此失败、超时和产物类结果更容易被稳定通知。

典型的 `spawn` 参数：

```json
{
  "task": "Review the latest docs changes and summarize risks",
  "label": "docs review",
  "goal": "Identify user-facing behavior changes",
  "constraints": ["Do not modify files", "Keep the summary brief"],
  "relevant_paths": ["./docs", "./README.md"],
  "done_when": ["List major risks", "List affected files"]
}
```

## ✨ 功能特性

<table align="center">
  <tr align="center">
    <th><p align="center">📈 7x24 实时市场分析</p></th>
    <th><p align="center">🚀 全栈软件工程师</p></th>
    <th><p align="center">📅 智能日程管理助手</p></th>
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
    <td align="center">安排 • 自动化 • 整理</td>
    <td align="center">学习 • 记忆 • 推理</td>
  </tr>
</table>

## 📦 安装

**从源码安装**（最新功能，推荐用于开发）

```bash
git clone https://github.com/HKUDS/nanobot.git
cd nanobot
pip install -e .
```

**使用 [uv](https://github.com/astral-sh/uv) 安装**（稳定、快速）

```bash
uv tool install nanobot-ai
```

**从 PyPI 安装**（稳定版）

```bash
pip install nanobot-ai
```

### 更新到最新版本

**PyPI / pip**

```bash
pip install -U nanobot-ai
nanobot --version
```

**uv**

```bash
uv tool upgrade nanobot-ai
nanobot --version
```

**使用 WhatsApp？** 升级后需重建本地桥接：

```bash
rm -rf ~/.nanobot/bridge
nanobot channels login
```

## 🚀 快速开始

> [!TIP]
> 在 `~/.nanobot/config.json` 中设置你的 API 密钥。
> 获取 API 密钥：[OpenRouter](https://openrouter.ai/keys)（全球）· [Brave Search](https://brave.com/search/api/)（可选，用于网络搜索）

**1. 初始化**

```bash
nanobot onboard
```

**2. 配置**（`~/.nanobot/config.json`）

添加或合并这**两部分**到你的配置（其他选项有默认值）。

*设置你的 API 密钥*（例如 OpenRouter，推荐全球用户使用）：
```json
{
  "providers": {
    "openrouter": {
      "apiKey": "sk-or-v1-xxx"
    }
  }
}
```

*设置你的模型*（可选指定提供商 — 默认自动检测）：
```json
{
  "agents": {
    "defaults": {
      "model": "anthropic/claude-opus-4-5",
      "provider": "openrouter"
    }
  }
}
```

**3. 聊天**

```bash
nanobot agent
```

就这样！2 分钟内你就有了一个可用的 AI 助手。

## 💬 聊天应用

将 nanobot 连接到你喜欢的聊天平台。

| 通道 | 所需信息 |
|---------|---------------|
| **Telegram** | 来自 @BotFather 的 Bot 令牌 |
| **Discord** | Bot 令牌 + 消息内容意图 |
| **WhatsApp** | 二维码扫描 |
| **飞书 (Feishu)** | App ID + App Secret |
| **Mochat** | Claw 令牌（支持自动设置） |
| **钉钉 (DingTalk)** | App Key + App Secret |
| **Slack** | Bot 令牌 + 应用级令牌 |
| **Email** | IMAP/SMTP 凭据 |
| **QQ** | App ID + App Secret |

<details>
<summary><b>Telegram</b>（推荐）</summary>

**1. 创建机器人**
- 打开 Telegram，搜索 `@BotFather`
- 发送 `/newbot`，按照提示操作
- 复制令牌

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

> 你可以在 Telegram 设置中找到你的**用户 ID**。显示为 `@yourUserId`。
> 复制此值**（不带 `@` 符号）**并粘贴到配置文件中。


**3. 运行**

```bash
nanobot gateway
```

</details>

<details>
<summary><b>Mochat (Claw IM)</b></summary>

默认使用 **Socket.IO WebSocket**，HTTP 轮询作为后备。

**1. 让 nanobot 为你设置 Mochat**

只需向 nanobot 发送此消息（将 `xxx@xxx` 替换为你的真实邮箱）：

```
Read https://raw.githubusercontent.com/HKUDS/MoChat/refs/heads/main/skills/nanobot/skill.md and register on MoChat. My Email account is xxx@xxx Bind me as your owner and DM me on MoChat.
```

nanobot 将自动注册、配置 `~/.nanobot/config.json` 并连接到 Mochat。

**2. 重启网关**

```bash
nanobot gateway
```

就这样 — nanobot 会处理剩下的事情！

<br>

<details>
<summary>手动配置（高级）</summary>

如果你更喜欢手动配置，请将以下内容添加到 `~/.nanobot/config.json`：

> 保密 `claw_token`。它应该只通过 `X-Claw-Token` 头发送到你的 Mochat API 端点。

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

**1. 创建机器人**
- 访问 https://discord.com/developers/applications
- 创建应用 → Bot → 添加 Bot
- 复制机器人令牌

**2. 启用意图**
- 在 Bot 设置中，启用**消息内容意图（MESSAGE CONTENT INTENT）**
- （可选）如果你计划使用基于成员数据的允许列表，启用**服务器成员意图（SERVER MEMBERS INTENT）**

**3. 获取你的用户 ID**
- Discord 设置 → 高级 → 启用**开发者模式**
- 右键点击你的头像 → **复制用户 ID**

**4. 配置**

```json
{
  "channels": {
    "discord": {
      "enabled": true,
      "token": "YOUR_BOT_TOKEN",
      "allowFrom": ["YOUR_USER_ID"],
      "groupPolicy": "mention"
    }
  }
}
```

> `groupPolicy` 控制机器人在群组频道中的响应方式：
> - `"mention"`（默认）— 仅在被 @ 提及时响应
> - `"open"` — 响应所有消息
> 当发送者在 `allowFrom` 中时，私信始终会响应。

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
<summary><b>Matrix (Element)</b></summary>

首先安装 Matrix 依赖：

```bash
pip install nanobot-ai[matrix]
```

**1. 创建/选择 Matrix 账户**

- 在你的家庭服务器上创建或重用 Matrix 账户（例如 `matrix.org`）。
- 确认你可以使用 Element 登录。

**2. 获取凭据**

- 你需要：
  - `userId`（例如：`@nanobot:matrix.org`）
  - `accessToken`
  - `deviceId`（推荐，以便跨重启恢复同步令牌）
- 你可以从家庭服务器登录 API（`/_matrix/client/v3/login`）或客户端的高级会话设置中获取这些信息。

**3. 配置**

```json
{
  "channels": {
    "matrix": {
      "enabled": true,
      "homeserver": "https://matrix.org",
      "userId": "@nanobot:matrix.org",
      "accessToken": "syt_xxx",
      "deviceId": "NANOBOT01",
      "e2eeEnabled": true,
      "allowFrom": ["@your_user:matrix.org"],
      "groupPolicy": "open",
      "groupAllowFrom": [],
      "allowRoomMentions": false,
      "maxMediaBytes": 20971520
    }
  }
}
```

> 保持持久的 `matrix-store` 和稳定的 `deviceId` — 如果这些在重启之间发生变化，加密会话状态将丢失。

| 选项 | 描述 |
|--------|-------------|
| `allowFrom` | 允许交互的用户 ID。为空则拒绝所有；使用 `["*"]` 允许所有人。 |
| `groupPolicy` | `open`（默认）、`mention` 或 `allowlist`。 |
| `groupAllowFrom` | 房间白名单（策略为 `allowlist` 时使用）。 |
| `allowRoomMentions` | 在提及模式下接受 `@room` 提及。 |
| `e2eeEnabled` | 端到端加密支持（默认 `true`）。设置为 `false` 则仅使用明文。 |
| `maxMediaBytes` | 最大附件大小（默认 `20MB`）。设置为 `0` 可阻止所有媒体。 |



**4. 运行**

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
# 使用 WhatsApp 扫描二维码 → 设置 → 关联设备
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

> WhatsApp 桥接更新不会自动应用于现有安装。
> 升级 nanobot 后，使用以下命令重建本地桥接：
> `rm -rf ~/.nanobot/bridge && nanobot channels login`

</details>

<details>
<summary><b>飞书 (Feishu)</b></summary>

使用 **WebSocket** 长连接 — 无需公网 IP。

**1. 创建飞书机器人**
- 访问[飞书开放平台](https://open.feishu.cn/app)
- 创建新应用 → 启用**机器人**能力
- **权限**：添加 `im:message`（发送消息）和 `im:message.p2p_msg:readonly`（接收消息）
- **事件**：添加 `im.message.receive_v1`（接收消息）
  - 选择**长连接**模式（需要先运行 nanobot 建立连接）
- 从"凭证与基本信息"获取**App ID**和**App Secret**
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
      "allowFrom": ["ou_YOUR_OPEN_ID"]
    }
  }
}
```

> 长连接模式下 `encryptKey` 和 `verificationToken` 是可选的。
> `allowFrom`：添加你的 open_id（向机器人发送消息时可在 nanobot 日志中找到）。使用 `["*"]` 允许所有用户。

**3. 运行**

```bash
nanobot gateway
```

> [!TIP]
> 飞书使用 WebSocket 接收消息 — 无需 Webhook 或公网 IP！

</details>

<details>
<summary><b>QQ (QQ单聊)</b></summary>

使用 **botpy SDK** 和 WebSocket — 无需公网 IP。目前**仅支持私聊**。

**1. 注册并创建机器人**
- 访问 [QQ 开放平台](https://q.qq.com) → 注册成为开发者（个人或企业）
- 创建新的机器人应用
- 进入**开发设置** → 复制 **AppID** 和 **AppSecret**

**2. 设置沙箱进行测试**
- 在机器人管理控制台中，找到**沙箱配置**
- 在**消息列表配置**下，点击**添加成员**并添加你自己的 QQ 号
- 添加后，使用手机 QQ 扫描机器人的二维码 → 打开机器人资料 → 点击"发消息"开始聊天

**3. 配置**

> - `allowFrom`：添加你的 openid（向机器人发送消息时可在 nanobot 日志中找到）。使用 `["*"]` 公开访问。
> - 生产环境：在机器人控制台中提交审核并发布。完整发布流程请参阅 [QQ 机器人文档](https://bot.q.qq.com/wiki/)。

```json
{
  "channels": {
    "qq": {
      "enabled": true,
      "appId": "YOUR_APP_ID",
      "secret": "YOUR_APP_SECRET",
      "allowFrom": ["YOUR_OPENID"]
    }
  }
}
```

**4. 运行**

```bash
nanobot gateway
```

现在从 QQ 向机器人发送消息 — 它应该会回复！

</details>

<details>
<summary><b>钉钉 (DingTalk)</b></summary>

使用**流式模式** — 无需公网 IP。

**1. 创建钉钉机器人**
- 访问[钉钉开放平台](https://open-dev.dingtalk.com/)
- 创建新应用 → 添加**机器人**能力
- **配置**：
  - 打开**流式模式**开关
- **权限**：添加发送消息所需的权限
- 从"凭证"中获取**AppKey**（Client ID）和**AppSecret**（Client Secret）
- 发布应用

**2. 配置**

```json
{
  "channels": {
    "dingtalk": {
      "enabled": true,
      "clientId": "YOUR_APP_KEY",
      "clientSecret": "YOUR_APP_SECRET",
      "allowFrom": ["YOUR_STAFF_ID"]
    }
  }
}
```

> `allowFrom`：添加你的员工 ID。使用 `["*"]` 允许所有用户。

**3. 运行**

```bash
nanobot gateway
```

</details>

<details>
<summary><b>Slack</b></summary>

使用**Socket 模式** — 无需公共 URL。

**1. 创建 Slack 应用**
- 访问 [Slack API](https://api.slack.com/apps) → **创建新应用** → "从头开始"
- 选择名称和工作区

**2. 配置应用**
- **Socket 模式**：打开开关 → 生成具有 `connections:write` 范围的**应用级令牌** → 复制（`xapp-...`）
- **OAuth 和权限**：添加机器人范围：`chat:write`、`reactions:write`、`app_mentions:read`
- **事件订阅**：打开开关 → 订阅机器人事件：`message.im`、`message.channels`、`app_mention` → 保存更改
- **应用首页**：滚动到**显示标签页** → 启用**消息标签页** → 勾选**"允许用户从消息标签页发送斜杠命令和消息"**
- **安装应用**：点击**安装到工作区** → 授权 → 复制**机器人令牌**（`xoxb-...`）

**3. 配置 nanobot**

```json
{
  "channels": {
    "slack": {
      "enabled": true,
      "botToken": "xoxb-...",
      "appToken": "xapp-...",
      "allowFrom": ["YOUR_SLACK_USER_ID"],
      "groupPolicy": "mention"
    }
  }
}
```

**4. 运行**

```bash
nanobot gateway
```

直接私信机器人或在频道中 @ 提及它 — 它应该会回复！

> [!TIP]
> - `groupPolicy`：`"mention"`（默认 — 仅在被 @ 提及时响应）、`"open"`（响应所有频道消息）或 `"allowlist"`（限制为特定频道）。
> - 私信策略默认为开放。设置 `"dm": {"enabled": false}` 可禁用私信。

</details>

<details>
<summary><b>Email</b></summary>

给 nanobot 一个自己的邮箱账户。它通过 **IMAP** 轮询接收邮件并通过 **SMTP** 回复 — 就像一个个人邮件助手。

**1. 获取凭据（Gmail 示例）**
- 为你的机器人创建一个专用 Gmail 账户（例如 `my-nanobot@gmail.com`）
- 启用两步验证 → 创建[应用密码](https://myaccount.google.com/apppasswords)
- 将此应用密码用于 IMAP 和 SMTP

**2. 配置**

> - `consentGranted` 必须为 `true` 才能允许邮箱访问。这是一个安全门 — 设置为 `false` 可完全禁用。
> - `allowFrom`：添加你的邮箱地址。使用 `["*"]` 接受任何人的邮件。
> - `smtpUseTls` 和 `smtpUseSsl` 默认分别为 `true` / `false`，这对 Gmail（端口 587 + STARTTLS）是正确的。无需显式设置。
> - 如果你只想阅读/分析邮件而不发送自动回复，设置 `"autoReplyEnabled": false`。

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

## 🌐 Agent 社交网络

🐈 nanobot 可以连接到 Agent 社交网络（Agent 社区）。**只需发送一条消息，你的 nanobot 就会自动加入！**

| 平台 | 如何加入（向你的机器人发送此消息） |
|----------|-------------|
| [**Moltbook**](https://www.moltbook.com/) | `Read https://moltbook.com/skill.md and follow the instructions to join Moltbook` |
| [**ClawdChat**](https://clawdchat.ai/) | `Read https://clawdchat.ai/skill.md and follow the instructions to join ClawdChat` |

只需将上述命令发送给你的 nanobot（通过 CLI 或任何聊天频道），它会处理剩下的事情。

## ⚙️ 配置

配置文件：`~/.nanobot/config.json`

### 提供商

> [!TIP]
> - **Groq** 通过 Whisper 提供免费的语音转文字。如果配置了，Telegram 语音消息将自动转录。
> - **智谱编码计划**：如果你使用智谱的编码计划，请在 zhipu 提供商配置中设置 `"apiBase": "https://open.bigmodel.cn/api/coding/paas/v4"`。
> - **MiniMax（中国大陆）**：如果你的 API 密钥来自 MiniMax 的中国大陆平台（minimaxi.com），请在 minimax 提供商配置中设置 `"apiBase": "https://api.minimaxi.com/v1"`。
> - **火山引擎编码计划**：如果你使用火山引擎的编码计划，请在 volcengine 提供商配置中设置 `"apiBase": "https://ark.cn-beijing.volces.com/api/coding/v3"`。
> - **阿里云编码计划**：如果你使用阿里云编码计划（百炼），请在 dashscope 提供商配置中设置 `"apiBase": "https://coding.dashscope.aliyuncs.com/v1"`。

| 提供商 | 用途 | 获取 API 密钥 |
|----------|---------|-------------|
| `custom` | 任何 OpenAI 兼容端点（直接连接，不通过 LiteLLM） | — |
| `openrouter` | LLM（推荐，访问所有模型） | [openrouter.ai](https://openrouter.ai) |
| `anthropic` | LLM（Claude 直连） | [console.anthropic.com](https://console.anthropic.com) |
| `azure_openai` | LLM（Azure OpenAI） | [portal.azure.com](https://portal.azure.com) |
| `openai` | LLM（GPT 直连） | [platform.openai.com](https://platform.openai.com) |
| `deepseek` | LLM（DeepSeek 直连） | [platform.deepseek.com](https://platform.deepseek.com) |
| `groq` | LLM + **语音转文字**（Whisper） | [console.groq.com](https://console.groq.com) |
| `gemini` | LLM（Gemini 直连） | [aistudio.google.com](https://aistudio.google.com) |
| `minimax` | LLM（MiniMax 直连） | [platform.minimaxi.com](https://platform.minimaxi.com) |
| `aihubmix` | LLM（API 网关，访问所有模型） | [aihubmix.com](https://aihubmix.com) |
| `siliconflow` | LLM（SiliconFlow/硅基流动） | [siliconflow.cn](https://siliconflow.cn) |
| `volcengine` | LLM（VolcEngine/火山引擎） | [volcengine.com](https://www.volcengine.com) |
| `dashscope` | LLM（通义/Qwen） | [dashscope.console.aliyun.com](https://dashscope.console.aliyun.com) |
| `moonshot` | LLM（Moonshot/Kimi） | [platform.moonshot.cn](https://platform.moonshot.cn) |
| `zhipu` | LLM（智谱 GLM） | [open.bigmodel.cn](https://open.bigmodel.cn) |
| `vllm` | LLM（本地，任何 OpenAI 兼容服务器） | — |
| `openai_codex` | LLM（Codex，OAuth） | `nanobot provider login openai-codex` |
| `github_copilot` | LLM（GitHub Copilot，OAuth） | `nanobot provider login github-copilot` |

<details>
<summary><b>OpenAI Codex (OAuth)</b></summary>

Codex 使用 OAuth 而不是 API 密钥。需要 ChatGPT Plus 或 Pro 账户。

**1. 登录：**
```bash
nanobot provider login openai-codex
```

**2. 设置模型**（合并到 `~/.nanobot/config.json`）：
```json
{
  "agents": {
    "defaults": {
      "model": "openai-codex/gpt-5.1-codex"
    }
  }
}
```

**3. 聊天：**
```bash
nanobot agent -m "Hello!"

# 本地定位到特定工作区/配置
nanobot agent -c ~/.nanobot-telegram/config.json -m "Hello!"

# 在该配置之上进行一次性工作区覆盖
nanobot agent -c ~/.nanobot-telegram/config.json -w /tmp/nanobot-telegram-test -m "Hello!"
```

> Docker 用户：使用 `docker run -it` 进行交互式 OAuth 登录。

</details>

<details>
<summary><b>自定义提供商（任何 OpenAI 兼容 API）</b></summary>

直接连接任何 OpenAI 兼容端点 — LM Studio、llama.cpp、Together AI、Fireworks、Azure OpenAI 或任何自托管服务器。绕过 LiteLLM；模型名称按原样传递。

```json
{
  "providers": {
    "custom": {
      "apiKey": "your-api-key",
      "apiBase": "https://api.your-provider.com/v1"
    }
  },
  "agents": {
    "defaults": {
      "model": "your-model-name"
    }
  }
}
```

> 对于不需要密钥的本地服务器，将 `apiKey` 设置为任何非空字符串（例如 `"no-key"`）。

</details>

<details>
<summary><b>vLLM（本地 / OpenAI 兼容）</b></summary>

使用 vLLM 或任何 OpenAI 兼容服务器运行你自己的模型，然后添加到配置：

**1. 启动服务器**（示例）：
```bash
vllm serve meta-llama/Llama-3.1-8B-Instruct --port 8000
```

**2. 添加到配置**（部分 — 合并到 `~/.nanobot/config.json`）：

*提供商*（密钥可以是本地任何非空字符串）：
```json
{
  "providers": {
    "vllm": {
      "apiKey": "dummy",
      "apiBase": "http://localhost:8000/v1"
    }
  }
}
```

*模型：*
```json
{
  "agents": {
    "defaults": {
      "model": "meta-llama/Llama-3.1-8B-Instruct"
    }
  }
}
```

</details>

<details>
<summary><b>添加新提供商（开发者指南）</b></summary>

nanobot 使用**提供商注册表**（`nanobot/providers/registry.py`）作为单一真实来源。
添加新提供商只需 **2 步** — 无需触及 if-elif 链。

**步骤 1.** 在 `nanobot/providers/registry.py` 的 `PROVIDERS` 中添加 `ProviderSpec` 条目：

```python
ProviderSpec(
    name="myprovider",                   # 配置字段名
    keywords=("myprovider", "mymodel"),  # 模型名称关键字用于自动匹配
    env_key="MYPROVIDER_API_KEY",        # LiteLLM 的环境变量
    display_name="My Provider",          # 显示在 `nanobot status` 中
    litellm_prefix="myprovider",         # 自动前缀：model → myprovider/model
    skip_prefixes=("myprovider/",),      # 不重复添加前缀
)
```

**步骤 2.** 在 `nanobot/config/schema.py` 的 `ProvidersConfig` 中添加字段：

```python
class ProvidersConfig(BaseModel):
    ...
    myprovider: ProviderConfig = ProviderConfig()
```

就这样！环境变量、模型前缀、配置匹配和 `nanobot status` 显示都会自动工作。

**常见 `ProviderSpec` 选项：**

| 字段 | 描述 | 示例 |
|-------|-------------|---------|
| `litellm_prefix` | 为 LiteLLM 自动添加模型名称前缀 | `"dashscope"` → `dashscope/qwen-max` |
| `skip_prefixes` | 如果模型已以此开头则不添加前缀 | `("dashscope/", "openrouter/")` |
| `env_extras` | 要设置的额外环境变量 | `(("ZHIPUAI_API_KEY", "{api_key}"),)` |
| `model_overrides` | 每个模型的参数覆盖 | `(("kimi-k2.5", {"temperature": 1.0}),)` |
| `is_gateway` | 可以路由任何模型（如 OpenRouter） | `True` |
| `detect_by_key_prefix` | 通过 API 密钥前缀检测网关 | `"sk-or-"` |
| `detect_by_base_keyword` | 通过 API 基本 URL 检测网关 | `"openrouter"` |
| `strip_model_prefix` | 在重新添加前缀之前去除现有前缀 | `True`（用于 AiHubMix） |

</details>


### MCP（模型上下文协议）

> [!TIP]
> 配置格式与 Claude Desktop / Cursor 兼容。你可以直接从任何 MCP 服务器的 README 复制 MCP 服务器配置。

nanobot 支持 [MCP](https://modelcontextprotocol.io/) — 连接外部工具服务器并将它们用作原生 Agent 工具。

将 MCP 服务器添加到你的 `config.json`：

```json
{
  "tools": {
    "mcpServers": {
      "filesystem": {
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-filesystem", "/path/to/dir"]
      },
      "my-remote-mcp": {
        "url": "https://example.com/mcp/",
        "headers": {
          "Authorization": "Bearer xxxxx"
        }
      }
    }
  }
}
```

支持两种传输模式：

| 模式 | 配置 | 示例 |
|------|--------|---------|
| **Stdio** | `command` + `args` | 通过 `npx` / `uvx` 的本地进程 |
| **HTTP** | `url` + `headers`（可选） | 远程端点（`https://mcp.example.com/sse`） |

使用 `toolTimeout` 覆盖慢服务器的默认每次调用 30 秒超时：

```json
{
  "tools": {
    "mcpServers": {
      "my-slow-server": {
        "url": "https://example.com/mcp/",
        "toolTimeout": 120
      }
    }
  }
}
```

MCP 工具在启动时自动发现和注册。LLM 可以将它们与内置工具一起使用 — 无需额外配置。



### 安全性

> [!TIP]
> 对于生产部署，在配置中设置 `"restrictToWorkspace": true"` 以沙箱化 Agent。
> 在 `v0.1.4.post3` 及更早版本中，空的 `allowFrom` 允许所有发送者。自 `v0.1.4.post4` 起，空的 `allowFrom` 默认拒绝所有访问。要允许所有发送者，设置 `"allowFrom": ["*"]`。

| 选项 | 默认值 | 描述 |
|--------|---------|-------------|
| `tools.restrictToWorkspace` | `false` | 为 `true` 时，将**所有** Agent 工具（shell、文件读/写/编辑、列表）限制在工作区目录。防止路径遍历和超出范围的访问。 |
| `tools.exec.pathAppend` | `""` | 运行 shell 命令时要附加到 `PATH` 的额外目录（例如 `/usr/sbin` 用于 `ufw`）。 |
| `channels.*.allowFrom` | `[]`（拒绝所有） | 用户 ID 白名单。为空则拒绝所有；使用 `["*"]` 允许所有人。 |


## 🧩 多实例

使用单独的配置和运行时数据同时运行多个 nanobot 实例。使用 `--config` 作为主入口点，可以选择使用 `--workspace` 覆盖特定运行的工作区。

### 快速开始

```bash
# 实例 A - Telegram 机器人
nanobot gateway --config ~/.nanobot-telegram/config.json

# 实例 B - Discord 机器人
nanobot gateway --config ~/.nanobot-discord/config.json

# 实例 C - 飞书机器人，自定义端口
nanobot gateway --config ~/.nanobot-feishu/config.json --port 18792
```

### 路径解析

使用 `--config` 时，nanobot 从配置文件位置派生其运行时数据目录。工作区仍然来自 `agents.defaults.workspace`，除非你用 `--workspace` 覆盖。

要针对这些实例之一在本地打开 CLI 会话：

```bash
nanobot agent -c ~/.nanobot-telegram/config.json -m "Hello from Telegram instance"
nanobot agent -c ~/.nanobot-discord/config.json -m "Hello from Discord instance"

# 可选的一次性工作区覆盖
nanobot agent -c ~/.nanobot-telegram/config.json -w /tmp/nanobot-telegram-test
```

> `nanobot agent` 使用所选工作区/配置启动本地 CLI Agent。它不会附加到或代理到已运行的 `nanobot gateway` 进程。

| 组件 | 解析来源 | 示例 |
|-----------|---------------|---------|
| **配置** | `--config` 路径 | `~/.nanobot-A/config.json` |
| **工作区** | `--workspace` 或配置 | `~/.nanobot-A/workspace/` |
| **Cron 任务** | 配置目录 | `~/.nanobot-A/cron/` |
| **媒体 / 运行时状态** | 配置目录 | `~/.nanobot-A/media/` |

### 工作原理

- `--config` 选择要加载的配置文件
- 默认情况下，工作区来自该配置中的 `agents.defaults.workspace`
- 如果你传递 `--workspace`，它会覆盖配置文件中的工作区

### 最小设置

1. 将基础配置复制到新的实例目录。
2. 为该实例设置不同的 `agents.defaults.workspace`。
3. 使用 `--config` 启动实例。

示例配置：

```json
{
  "agents": {
    "defaults": {
      "workspace": "~/.nanobot-telegram/workspace",
      "model": "anthropic/claude-sonnet-4-6"
    }
  },
  "channels": {
    "telegram": {
      "enabled": true,
      "token": "YOUR_TELEGRAM_BOT_TOKEN"
    }
  },
  "gateway": {
    "port": 18790
  }
}
```

启动单独的实例：

```bash
nanobot gateway --config ~/.nanobot-telegram/config.json
nanobot gateway --config ~/.nanobot-discord/config.json
```

需要时覆盖一次性运行的工作区：

```bash
nanobot gateway --config ~/.nanobot-telegram/config.json --workspace /tmp/nanobot-telegram-test
```

### 常见用例

- 为 Telegram、Discord、飞书等平台运行单独的机器人
- 保持测试和生产实例隔离
- 为不同团队使用不同的模型或提供商
- 使用单独的配置和运行时数据服务多个租户

### 注意事项

- 如果同时运行，每个实例必须使用不同的端口
- 如果你想隔离内存、会话和技能，每个实例使用不同的工作区
- `--workspace` 覆盖配置文件中定义的工作区
- Cron 任务和运行时媒体/状态从配置目录派生

## 💻 CLI 参考

| 命令 | 描述 |
|---------|-------------|
| `nanobot onboard` | 初始化配置和工作区 |
| `nanobot agent -m "..."` | 与 Agent 聊天 |
| `nanobot agent -w <workspace>` | 针对特定工作区聊天 |
| `nanobot agent -w <workspace> -c <config>` | 针对特定工作区/配置聊天 |
| `nanobot agent` | 交互式聊天模式 |
| `nanobot agent --no-markdown` | 显示纯文本回复 |
| `nanobot agent --logs` | 聊天期间显示运行时日志 |
| `nanobot gateway` | 启动网关 |
| `nanobot status` | 显示状态 |
| `nanobot provider login openai-codex` | 提供商 OAuth 登录 |
| `nanobot channels login` | 链接 WhatsApp（扫描二维码） |
| `nanobot channels status` | 显示通道状态 |

交互模式退出：`exit`、`quit`、`/exit`、`/quit`、`:q` 或 `Ctrl+D`。

<details>
<summary><b>心跳（周期性任务）</b></summary>

网关每 30 分钟唤醒一次并检查工作区中的 `HEARTBEAT.md` 文件（`~/.nanobot/workspace/HEARTBEAT.md`）。如果文件有任务，Agent 会执行它们并将结果发送到你最近活跃的聊天频道。

**设置：**编辑 `~/.nanobot/workspace/HEARTBEAT.md`（由 `nanobot onboard` 自动创建）：

```markdown
## 周期性任务

- [ ] 检查天气预报并发送摘要
- [ ] 扫描收件箱中的紧急邮件
```

Agent 也可以自己管理此文件 — 要求它"添加周期性任务"，它会为你更新 `HEARTBEAT.md`。

> **注意：**网关必须正在运行（`nanobot gateway`），并且你必须至少与机器人聊天一次，这样它才知道要发送到哪个频道。

</details>

## 🐳 Docker

> [!TIP]
> `-v ~/.nanobot:/root/.nanobot` 标志将本地配置目录挂载到容器中，因此你的配置和工作区在容器重启之间保持持久。

### Docker Compose

```bash
docker compose run --rm nanobot-cli onboard   # 首次设置
vim ~/.nanobot/config.json                     # 添加 API 密钥
docker compose up -d nanobot-gateway           # 启动网关
```

```bash
docker compose run --rm nanobot-cli agent -m "Hello!"   # 运行 CLI
docker compose logs -f nanobot-gateway                   # 查看日志
docker compose down                                      # 停止
```

### Docker

```bash
# 构建镜像
docker build -t nanobot .

# 初始化配置（仅首次）
docker run -v ~/.nanobot:/root/.nanobot --rm nanobot onboard

# 在主机上编辑配置以添加 API 密钥
vim ~/.nanobot/config.json

# 运行网关（连接到启用的通道，例如 Telegram/Discord/Mochat）
docker run -v ~/.nanobot:/root/.nanobot -p 18790:18790 nanobot gateway

# 或运行单个命令
docker run -v ~/.nanobot:/root/.nanobot --rm nanobot agent -m "Hello!"
docker run -v ~/.nanobot:/root/.nanobot --rm nanobot status
```

## 🐧 Linux 服务

将网关作为 systemd 用户服务运行，使其自动启动并在失败时重启。

**1. 找到 nanobot 二进制路径：**

```bash
which nanobot   # 例如 /home/user/.local/bin/nanobot
```

**2. 在 `~/.config/systemd/user/nanobot-gateway.service` 创建服务文件**（如需要请替换 `ExecStart` 路径）：

```ini
[Unit]
Description=Nanobot Gateway
After=network.target

[Service]
Type=simple
ExecStart=%h/.local/bin/nanobot gateway
Restart=always
RestartSec=10
NoNewPrivileges=yes
ProtectSystem=strict
ReadWritePaths=%h

[Install]
WantedBy=default.target
```

**3. 启用并启动：**

```bash
systemctl --user daemon-reload
systemctl --user enable --now nanobot-gateway
```

**常用操作：**

```bash
systemctl --user status nanobot-gateway        # 检查状态
systemctl --user restart nanobot-gateway       # 配置更改后重启
journalctl --user -u nanobot-gateway -f        # 跟踪日志
```

如果编辑 `.service` 文件本身，请在重启之前运行 `systemctl --user daemon-reload`。

> **注意：**用户服务仅在登录时运行。要在登出后保持网关运行，启用 lingering：
>
> ```bash
> loginctl enable-linger $USER
> ```

## 📁 项目结构

```
nanobot/
├── agent/          # 🧠 核心 Agent 逻辑
│   ├── loop.py     #    Agent 循环（LLM ↔ 工具执行）
│   ├── context.py  #    提示构建器
│   ├── memory.py   #    持久化内存
│   ├── skills.py   #    技能加载器
│   ├── subagent.py #    后台任务执行
│   └── tools/      #    内置工具（包括 spawn）
├── skills/         # 🎯 捆绑技能（github、weather、tmux...）
├── channels/       # 📱 聊天通道集成
├── bus/            # 🚌 消息路由
├── cron/           # ⏰ 定时任务
├── heartbeat/      # 💓 主动唤醒
├── providers/      # 🤖 LLM 提供商（OpenRouter 等）
├── session/        # 💬 会话会话
├── config/         # ⚙️ 配置
└── cli/            # 🖥️ 命令
```

## 🤝 贡献与路线图

欢迎 PR！代码库故意保持小巧和易读。🤗

**路线图** — 选择一项并[打开 PR](https://github.com/HKUDS/nanobot/pulls)！

- [ ] **多模态** — 看见和听见（图像、语音、视频）
- [ ] **长期记忆** — 永不忘记重要上下文
- [ ] **更好的推理** — 多步规划和反思
- [ ] **更多集成** — 日历等
- [ ] **自我改进** — 从反馈和错误中学习

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
  <sub>nanobot 仅用于教育、研究和技术交流目的</sub>
</p>
