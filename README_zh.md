<div align="center">
  <img src="nanobot_logo.png" alt="nanobot" width="500">
  <h1>nanobot: 超轻量级个人 AI 助手</h1>
  <p>
    <a href="https://pypi.org/project/nanobot-ai/"><img src="https://img.shields.io/pypi/v/nanobot-ai" alt="PyPI"></a>
    <a href="https://pepy.tech/project/nanobot-ai"><img src="https://static.pepy.tech/badge/nanobot-ai" alt="Downloads"></a>
    <img src="https://img.shields.io/badge/python-≥3.11-blue" alt="Python">
    <img src="https://img.shields.io/badge/license-MIT-green" alt="License">
    <a href="./COMMUNICATION.md"><img src="https://img.shields.io/badge/Feishu-Group-E9DBFC?style=flat&logo=feishu&logoColor=white" alt="Feishu"></a>
    <a href="./COMMUNICATION.md"><img src="https://img.shields.io/badge/WeChat-Group-C5EAB4?style=flat&logo=wechat&logoColor=white" alt="WeChat"></a>
    <a href="https://discord.gg/MnCvHqpUGB"><img src="https://img.shields.io/badge/Discord-Community-5865F2?style=flat&logo=discord&logoColor=white" alt="Discord"></a>
    <br>
    <a href="./README.md">English</a>
  </p>
</div>

🐈 **nanobot** 是一个受 [Clawdbot](https://github.com/openclaw/openclaw) 启发的**超轻量级**个人 AI 助手。

⚡️ 仅用 **~4,000** 行代码即可提供核心 Agent 功能 — 比 Clawdbot 的 430k+ 行代码**小 99%**。

📏 实时代码行数：**3,422 行** (随时运行 `bash core_agent_lines.sh` 进行验证)

## 📢 最新动态

- **2026-02-06** ✨ 新增 Moonshot/Kimi 提供商、Discord 集成，并增强了安全性！
- **2026-02-05** ✨ 新增飞书 (Feishu) 渠道、DeepSeek 提供商，并增强了定时任务支持！
- **2026-02-04** 🚀 发布 v0.1.3.post4，支持多提供商和 Docker！详情请查看 [发布说明](https://github.com/HKUDS/nanobot/releases/tag/v0.1.3.post4)。
- **2026-02-03** ⚡ 集成 vLLM 以支持本地 LLM，并改进了自然语言任务调度！
- **2026-02-02** 🎉 nanobot 正式发布！欢迎试用 🐈 nanobot！

## nanobot 的核心特性：

🪶 **超轻量级**：核心 Agent 代码仅 ~4,000 行 — 比 Clawdbot 小 99%。

🔬 **易于研究**：代码整洁易读，便于理解、修改和扩展，适合研究用途。

⚡️ **闪电般快速**：极小的占用空间意味着更快的启动速度、更低的资源消耗和更快的迭代。

💎 **简单易用**：一键部署，即刻使用。

## 🏗️ 架构

<p align="center">
  <img src="nanobot_arch.png" alt="nanobot architecture" width="800">
</p>

## ✨ 功能

<table align="center">
  <tr align="center">
    <th><p align="center">📈 24/7 实时市场分析</p></th>
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
> 请在 `~/.nanobot/config.json` 中设置您的 API 密钥。
> 获取 API 密钥：[OpenRouter](https://openrouter.ai/keys) (全球通用) · [DashScope](https://dashscope.console.aliyun.com) (Qwen) · [Brave Search](https://brave.com/search/api/) (可选，用于网络搜索)

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

**3. 聊天**

```bash
nanobot agent -m "2+2 等于几？"
```

就是这样！您在 2 分钟内就拥有了一个可工作的 AI 助手。

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
nanobot agent -m "你好，来自我的本地 LLM！"
```

> [!TIP]
> 对于不需要身份验证的本地服务器，`apiKey` 可以是任何非空字符串。

## 💬 聊天应用

通过 Telegram、Discord、WhatsApp 或飞书与您的 nanobot 交谈 — 随时随地。

| 渠道 | 设置难度 |
|---------|-------|
| **Telegram** | 简单 (仅需 token) |
| **Discord** | 简单 (bot token + intents) |
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

> 从 Telegram 上的 `@userinfobot` 获取您的用户 ID。

**3. 运行**

```bash
nanobot gateway
```

</details>

<details>
<summary><b>Discord</b></summary>

**1. 创建机器人**
- 前往 https://discord.com/developers/applications
- 创建应用 → Bot → Add Bot
- 复制 bot token

**2. 启用 Intents**
- 在 Bot 设置中，启用 **MESSAGE CONTENT INTENT**
- (可选) 如果您计划根据成员数据使用白名单，请启用 **SERVER MEMBERS INTENT**

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
- 打开生成的邀请 URL 并将机器人添加到您的服务器

**6. 运行**

```bash
nanobot gateway
```

</details>

<details>
<summary><b>WhatsApp</b></summary>

需要 **Node.js ≥18**。

**1. 关联设备**

```bash
nanobot channels login
# 使用 WhatsApp 扫描二维码 → 设置 → 已关联设备
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

**1. 创建飞书机器人**
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

> 长连接模式下 `encryptKey` 和 `verificationToken` 是可选的。
> `allowFrom`：留空以允许所有用户，或添加 `["ou_xxx"]` 以限制访问。

**3. 运行**

```bash
nanobot gateway
```

> [!TIP]
> 飞书使用 WebSocket 接收消息 — 无需 webhook 或公网 IP！

</details>

## ⚙️ 配置

配置文件：`~/.nanobot/config.json`

### 提供商 (Providers)

> [!NOTE]
> Groq 通过 Whisper 提供免费的语音转录。如果配置了，Telegram 语音消息将自动转录。

| 提供商 | 用途 | 获取 API 密钥 |
|----------|---------|-------------|
| `openrouter` | LLM (推荐，可访问所有模型) | [openrouter.ai](https://openrouter.ai) |
| `anthropic` | LLM (Claude 直连) | [console.anthropic.com](https://console.anthropic.com) |
| `openai` | LLM (GPT 直连) | [platform.openai.com](https://platform.openai.com) |
| `deepseek` | LLM (DeepSeek 直连) | [platform.deepseek.com](https://platform.deepseek.com) |
| `groq` | LLM + **语音转录** (Whisper) | [console.groq.com](https://console.groq.com) |
| `gemini` | LLM (Gemini 直连) | [aistudio.google.com](https://aistudio.google.com) |
| `aihubmix` | LLM (API 网关，可访问所有模型) | [aihubmix.com](https://aihubmix.com) |
| `dashscope` | LLM (Qwen) | [dashscope.console.aliyun.com](https://dashscope.console.aliyun.com) |


### 安全

> [!TIP]
> 对于生产环境部署，请在配置中设置 `"restrictToWorkspace": true` 以沙箱化 Agent。

| 选项 | 默认值 | 描述 |
|--------|---------|-------------|
| `tools.restrictToWorkspace` | `false` | 为 `true` 时，将**所有** Agent 工具 (shell, 文件读/写/编辑, 列表) 限制在工作区目录中。防止路径遍历和越权访问。 |
| `channels.*.allowFrom` | `[]` (允许所有) | 用户 ID 白名单。空 = 允许所有人；非空 = 仅列出的用户可以交互。 |


## CLI 参考

| 命令 | 描述 |
|---------|-------------|
| `nanobot onboard` | 初始化配置和工作区 |
| `nanobot agent -m "..."` | 与 Agent 聊天 |
| `nanobot agent` | 交互式聊天模式 |
| `nanobot gateway` | 启动网关 |
| `nanobot status` | 显示状态 |
| `nanobot channels login` | 关联 WhatsApp (扫码) |
| `nanobot channels status` | 显示渠道状态 |

<details>
<summary><b>定时任务 (Cron)</b></summary>

```bash
# 添加任务
nanobot cron add --name "daily" --message "早上好！" --cron "0 9 * * *"
nanobot cron add --name "hourly" --message "检查状态" --every 3600

# 列出任务
nanobot cron list

# 移除任务
nanobot cron remove <job_id>
```

</details>

## 🐳 Docker

> [!TIP]
> `-v ~/.nanobot:/root/.nanobot` 标志将您的本地配置目录挂载到容器中，因此您的配置和工作区在容器重启后仍然存在。

在容器中构建并运行 nanobot：

```bash
# 构建镜像
docker build -t nanobot .

# 初始化配置 (仅第一次)
docker run -v ~/.nanobot:/root/.nanobot --rm nanobot onboard

# 在主机上编辑配置以添加 API 密钥
vim ~/.nanobot/config.json

# 运行网关 (连接到 Telegram/WhatsApp)
docker run -v ~/.nanobot:/root/.nanobot -p 18790:18790 nanobot gateway

# 或者运行单个命令
docker run -v ~/.nanobot:/root/.nanobot --rm nanobot agent -m "你好！"
docker run -v ~/.nanobot:/root/.nanobot --rm nanobot status
```

## 📁 项目结构

```
nanobot/
├── agent/          # 🧠 核心 Agent 逻辑
│   ├── loop.py     #    Agent 循环 (LLM ↔ 工具执行)
│   ├── context.py  #    Prompt 构建器
│   ├── memory.py   #    持久化记忆
│   ├── skills.py   #    技能加载器
│   ├── subagent.py #    后台任务执行
│   └── tools/      #    内置工具 (包括 spawn)
├── skills/         # 🎯 捆绑技能 (github, weather, tmux...)
├── channels/       # 📱 WhatsApp 集成
├── bus/            # 🚌 消息路由
├── cron/           # ⏰ 定时任务
├── heartbeat/      # 💓 主动唤醒
├── providers/      # 🤖 LLM 提供商 (OpenRouter 等)
├── session/        # 💬 会话 session
├── config/         # ⚙️ 配置
└── cli/            # 🖥️ 命令
```

## 🤝 贡献与路线图

欢迎提交 PR！代码库有意保持小巧且可读。🤗

**路线图** — 挑选一项并 [提交 PR](https://github.com/HKUDS/nanobot/pulls)!

- [x] **语音转录** — 支持 Groq Whisper (Issue #13)
- [ ] **多模态** — 视觉和听觉 (图像, 语音, 视频)
- [ ] **长期记忆** — 永不遗忘重要上下文
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
