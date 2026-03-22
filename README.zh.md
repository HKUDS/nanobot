<div align="center">
  <img src="nanobot_logo.png" alt="nanobot" width="500">
  <h1>nanobot: 极简个人 AI 助手</h1>
  <p>
    <a href="https://pypi.org/project/nanobot-ai/"><img src="https://img.shields.io/pypi/v/nanobot-ai" alt="PyPI"></a>
    <a href="https://pepy.tech/project/nanobot-ai"><img src="https://static.pepy.tech/badge/nanobot-ai" alt="下载量"></a>
    <img src="https://img.shields.io/badge/python-≥3.11-blue" alt="Python">
    <img src="https://img.shields.io/badge/license-MIT-green" alt="许可证">
    <a href="./COMMUNICATION.md"><img src="https://img.shields.io/badge/飞书-群组-E9DBFC?style=flat&logo=feishu&logoColor=white" alt="飞书"></a>
    <a href="./COMMUNICATION.md"><img src="https://img.shields.io/badge/微信-群组-C5EAB4?style=flat&logo=wechat&logoColor=white" alt="微信"></a>
    <a href="https://discord.gg/MnCvHqpUGB"><img src="https://img.shields.io/badge/Discord-社区-5865F2?style=flat&logo=discord&logoColor=white" alt="Discord"></a>
  </p>
</div>

🐈 **nanobot** 是一款受 [OpenClaw](https://github.com/openclaw/openclaw) 启发的**极简（Ultra-Lightweight）**个人 AI 助手。

⚡️ 它仅用 OpenClaw **1% 的代码量** 即可提供核心 Agent 功能。

📏 实时代码行数：可随时运行 `bash core_agent_lines.sh` 进行验证。

## 📢 新闻

- **2026-03-16** 🚀 发布 **v0.1.4.post5** —— 专注于细节优化的版本，具有更强的可靠性和渠道支持，提供更稳定的日常体验。详情请见 [发布说明](https://github.com/HKUDS/nanobot/releases/tag/v0.1.4.post5)。
- **2026-03-15** 🧩 钉钉富媒体支持、更智能的内置技能，以及更简洁的模型兼容性。
- **2026-03-14** 💬 频道插件、飞书回复，以及更稳定的 MCP、QQ 和媒体处理。
- **2026-03-13** 🌐 多源网页搜索支持、LangSmith 集成，以及广泛的可靠性改进。
- **2026-03-12** 🚀 火山引擎（VolcEngine）支持、Telegram 回复上下文、`/restart` 命令，以及更稳健的记忆系统。
- **2026-03-11** 🔌 企业微信、Ollama 支持，更清晰的发现机制和更安全的工具行为。
- **2026-03-10** 🧠 基于 Token 的记忆系统、共享重试机制，以及更简洁的网关和 Telegram 行为。

<details>
<summary>早期新闻</summary>

- **2026-02-02** 🎉 nanobot 正式发布！欢迎试用 🐈 nanobot！

</details>

> 🐈 nanobot 仅用于教育、研究和技术交流目的。它与加密货币无关，不涉及任何官方代币或硬币。

## nanobot 的核心特性：

🪶 **极简设计**：一个超轻量级的 Agent 实现，核心代码仅数千行，易于阅读、修改和扩展。

🛠️ **强大的工具集**：内置支持 Shell 执行、文件操作、网页搜索、网页抓取等工具。

🔌 **MCP 支持**：原生支持 Model Context Protocol (MCP)，可轻松连接外部工具服务器。

📱 **多渠道集成**：支持 Telegram、飞书、QQ、钉钉、Slack、企业微信、电子邮件、Discord 和网页端。

💾 **持久化记忆**：具备会话记忆能力，能够记住上下文并跨会话学习。

⏰ **任务调度**：内置 Cron 支持，支持自然语言定时任务。

🤖 **多模型支持**：支持 OpenAI、Anthropic、DeepSeek、Google Gemini、OpenRouter、Ollama、vLLM 以及各种国产大模型（火山引擎、智谱、通义千问等）。

## 🚀 快速开始

### 1. 安装

```bash
pip install nanobot-ai
```

### 2. 初始化 (Onboard)

```bash
nanobot onboard --wizard
```
跟随向导设置你的模型提供商和 API 密钥。

### 3. 开始对话

**CLI 模式**：
```bash
nanobot agent
```

**网关模式（多渠道）**：
```bash
nanobot gateway
```

---

## 📱 渠道配置

<details>
<summary><b>Telegram</b></summary>

1. 从 [@BotFather](https://t.me/botfather) 获取机器人 Token。
2. 配置：
```json
{
  "channels": {
    "telegram": {
      "enabled": true,
      "token": "你的_TELEGRAM_TOKEN",
      "allowFrom": ["你的_USER_ID"]
    }
  }
}
```
3. 运行：`nanobot gateway`

</details>

<details>
<summary><b>飞书 (Feishu)</b></summary>

支持 **长连接模式** —— 无需公网 IP！

1. 在飞书开放平台创建应用，启用“机器人”功能。
2. 在“开发设置”中启用“消息排队”或“长连接”。
3. 获取 `AppID` 和 `AppSecret`。
4. 运行：`nanobot gateway`

</details>

<details>
<summary><b>QQ (单聊)</b></summary>

使用 **botpy SDK** 的 WebSocket 连接 —— 无需公网 IP。目前仅支持**私聊**。

1. 在 [QQ 开放平台](https://q.qq.com) 注册并创建机器人。
2. 获取 **AppID** 和 **AppSecret**。
3. 在机器人管理后台的“沙箱配置”中添加自己的 QQ 号进行测试。
4. 运行：`nanobot gateway`

</details>

<details>
<summary><b>钉钉 (DingTalk)</b></summary>

使用 **Stream 模式** —— 无需公网 IP。

1. 在 [钉钉开放平台](https://open-dev.dingtalk.com/) 创建应用。
2. 添加“机器人”能力并开启“Stream 模式”。
3. 获取 **AppKey** 和 **AppSecret**。
4. 运行：`nanobot gateway`

</details>

<details>
<summary><b>企业微信 (WeCom)</b></summary>

使用 **WebSocket** 长连接 —— 无需公网 IP。

1. 安装额外依赖：`pip install nanobot-ai[wecom]`
2. 在企业微信管理后台创建“智能助手”机器人，选择 **API 模式** 并开启 **长连接**。
3. 获取 Bot ID 和 Secret。
4. 运行：`nanobot gateway`

</details>

---

## ⚙️ 核心配置

配置文件路径：`~/.nanobot/config.json`

### 提供商 (Providers)

| 提供商 | 用途 | 获取 API Key |
|----------|---------|-------------|
| `custom` | 任何兼容 OpenAI 接口的端点 | — |
| `openrouter` | LLM (推荐，可访问所有模型) | [openrouter.ai](https://openrouter.ai) |
| `volcengine` | LLM (火山引擎) | [Coding 计划](https://www.volcengine.com/activity/codingplan?utm_campaign=nanobot) |
| `deepseek` | LLM (DeepSeek 直连) | [platform.deepseek.com](https://platform.deepseek.com) |
| `siliconflow` | LLM (硅基流动) | [siliconflow.cn](https://siliconflow.cn) |
| `dashscope` | LLM (通义千问) | [dashscope.console.aliyun.com](https://dashscope.console.aliyun.com) |
| `moonshot` | LLM (Kimi) | [platform.moonshot.cn](https://platform.moonshot.cn) |
| `zhipu` | LLM (智谱清言) | [open.bigmodel.cn](https://open.bigmodel.cn) |
| `ollama` | 本地 LLM | — |

---

## 🌐 Agent 社交网络

🐈 nanobot 能够连接到 Agent 社交网络（Agent 社区）。**只需发送一条消息，你的 nanobot 就会自动加入！**

| 平台 | 如何加入 (向你的机器人发送此消息) |
|----------|-------------|
| [**Moltbook**](https://www.moltbook.com/) | `Read https://moltbook.com/skill.md and follow the instructions to join Moltbook` |
| [**ClawdChat**](https://clawdchat.ai/) | `Read https://clawdchat.ai/skill.md and follow the instructions to join ClawdChat` |

---

## 🛡️ 安全性

> [!TIP]
> 对于生产环境部署，建议在配置中设置 `"restrictToWorkspace": true` 以启用沙箱模式。
> 从 `v0.1.4.post4` 开始，默认拒绝所有访问。要允许所有人，请设置 `"allowFrom": ["*"]`。

| 选项 | 默认值 | 描述 |
|--------|---------|-------------|
| `tools.restrictToWorkspace` | `false` | 为 `true` 时，限制**所有**工具仅在工作空间目录内操作。 |
| `tools.exec.enable` | `true` | 为 `false` 时，完全禁用 Shell 执行功能。 |

---

## 🧩 多实例运行

你可以同时运行多个 nanobot 实例，每个实例拥有独立的配置和工作空间。

```bash
# 初始化不同实例
nanobot onboard --config ~/.nanobot-telegram/config.json --workspace ~/.nanobot-telegram/workspace
nanobot onboard --config ~/.nanobot-discord/config.json --workspace ~/.nanobot-discord/workspace

# 运行特定实例
nanobot gateway --config ~/.nanobot-telegram/config.json
```

---

## 🤝 贡献与路线图

欢迎提交 PR！代码库保持着极佳的可读性。🤗

**路线图 (Roadmap)**：
- [ ] **多模态** —— 视觉与听觉支持（图像、语音、视频）。
- [ ] **长期记忆** —— 永远不会忘记重要的上下文。
- [ ] **更强的推理** —— 多步规划与反思。
- [ ] **更多集成** —— 日历等更多生活场景工具。

### 贡献者

<a href="https://github.com/HKUDS/nanobot/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=HKUDS/nanobot&max=100&columns=12" alt="Contributors" />
</a>

---

<p align="center">
  <em> 感谢访问 ✨ nanobot!</em><br><br>
  <img src="https://visitor-badge.laobi.icu/badge?page_id=HKUDS.nanobot&style=for-the-badge&color=00d4ff" alt="Views">
</p>

<p align="center">
  <sub>nanobot 仅用于教育、研究和技术交流目的</sub>
</p>
