# 项目整体介绍

# nanobot 项目文档详解

这是 **nanobot** 项目的 `README.md` 文件，即 GitHub 仓库首页的展示文档。下面按章节逐一详解。

---

## 一、项目头部（徽章与定位）

```html
<div align="center">
  <img src="nanobot_logo.png" alt="nanobot" width="500">
  <h1>nanobot: Ultra-Lightweight Personal AI Assistant</h1>
```

### 徽章（Badges）含义

| 徽章 | 含义 |
|------|------|
| `PyPI v*` | 已发布到 Python 包管理平台，可 `pip install` |
| `Downloads` | 累计下载量统计 |
| `python ≥3.11` | 最低 Python 版本要求 |
| `license MIT` | MIT 开源协议（最宽松的协议之一） |
| `Feishu / WeChat / Discord` | 社区沟通渠道入口 |

### 核心定位（三句话概括项目）

```
🐈 nanobot 是受 OpenClaw 启发的超轻量级个人 AI 助手
⚡️ 用比 OpenClaw 少 99% 的代码实现核心 Agent 功能
📏 可随时运行脚本验证代码行数
```

> **本质**：这是一个 OpenClaw 的**极简复刻版**，强调代码少、易理解、易扩展。

---

## 二、新闻动态（News）

```markdown
- **2026-03-08** 🚀 Released v0.1.4.post4 ...
- **2026-03-07** 🚀 Azure OpenAI provider...
```

这是**按时间倒序排列的更新日志**，展示项目活跃度。关键信息：

| 时间线 | 重要里程碑 |
|--------|-----------|
| 2026-02-02 | 项目正式上线 |
| 2026-02-14 | 支持 MCP 协议 |
| 2026-02-17 | v0.1.4 发布（MCP + 流式输出） |
| 2026-03-08 | v0.1.4.post4（最新稳定版） |

> 用 `<details>` 标签折叠了早期新闻，保持页面简洁。

---

## 三、核心特性（Key Features）

```
🪶 Ultra-Lightweight  — 超轻量，比 OpenClaw 小 99%
🔬 Research-Ready     — 代码清晰，适合学术研究和二次开发
⚡️ Lightning Fast     — 启动快、资源少、迭代快
💎 Easy-to-Use        — 一键部署即可使用
```

---

## 四、架构图（Architecture）

```
nanobot_arch.png
```

虽然图片无法直接查看，但根据代码结构可以推断架构：

```
┌─────────────────────────────────────────────────────┐
│                    用户交互层                         │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌────────┐ │
│  │ CLI 终端  │ │ Telegram │ │ Discord  │ │ 更多... │ │
│  └────┬─────┘ └────┬─────┘ └────┬─────┘ └───┬────┘ │
│       └─────────────┴────────────┴───────────┘      │
│                        ↕                             │
│              ┌─────────────────┐                     │
│              │   Message Bus   │  ← 消息总线(发布-订阅)│
│              └────────┬────────┘                     │
│                       ↕                              │
│  ┌────────────────────────────────────────────┐      │
│  │              Agent Core                     │     │
│  │  ┌────────┐ ┌────────┐ ┌────────┐          │     │
│  │  │ Loop   │ │Context │ │ Memory │          │     │
│  │  │(主循环) │ │(上下文) │ │(记忆)  │          │     │
│  │  └────────┘ └────────┘ └────────┘          │     │
│  └────────────────────┬───────────────────────┘     │
│                       ↕                              │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐             │
│  │ Tools    │ │ MCP      │ │ Skills   │             │
│  │(内置工具) │ │(外部工具) │ │(技能包)  │             │
│  └──────────┘ └──────────┘ └──────────┘             │
│                       ↕                              │
│  ┌──────────────────────────────────────────────┐   │
│  │           Providers (LLM 提供商)               │   │
│  │  OpenRouter│Anthropic│OpenAI│DeepSeek│Ollama  │   │
│  └──────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────┘
```

---

## 五、功能展示（Features）

展示了 4 个典型使用场景：

| 场景 | 说明 |
|------|------|
| 📈 **24/7 实时市场分析** | 搜索发现 → 洞察分析 → 趋势追踪 |
| 🚀 **全栈软件工程师** | 开发 → 部署 → 扩展 |
| 📅 **智能日程管理** | 排程 → 自动化 → 组织 |
| 📚 **个人知识助手** | 学习 → 记忆 → 推理 |

> 每个场景都配有 GIF 动画演示。

---

## 六、安装（Install）

提供了 **3 种安装方式**：

```bash
# 方式1：源码安装（开发推荐）
git clone https://github.com/HKUDS/nanobot.git
cd nanobot
pip install -e .    # -e 表示"可编辑模式"，改代码立即生效

# 方式2：uv 安装（快速）
uv tool install nanobot-ai

# 方式3：PyPI 安装（稳定）
pip install nanobot-ai
```

> **注意**：包名是 `nanobot-ai`（PyPI 上），命令行工具名是 `nanobot`。

---

## 七、快速开始（Quick Start）

**三步上手**：

### 步骤 1：初始化
```bash
nanobot onboard
# 创建 ~/.nanobot/ 目录结构和默认配置
```

### 步骤 2：配置 API Key

```json
// ~/.nanobot/config.json
{
  "providers": {
    "openrouter": {
      "apiKey": "sk-or-v1-xxx"    // ← 填入你的 API Key
    }
  },
  "agents": {
    "defaults": {
      "model": "anthropic/claude-opus-4-5",  // ← 选择模型
      "provider": "openrouter"                // ← 指定提供商
    }
  }
}
```

### 步骤 3：开始对话
```bash
nanobot agent
```

> 整个过程号称 **2 分钟完成**。

---

## 八、聊天平台集成（Chat Apps）

这是文档**最大的章节之一**，支持 **10+ 个聊天平台**：

### 支持的平台一览

```
┌─────────────────────────────────────────────┐
│              支持的聊天平台                    │
├──────────────┬──────────────────────────────┤
│ Telegram     │ Bot Token（@BotFather 创建）   │
│ Discord      │ Bot Token + Message Intent    │
│ WhatsApp     │ 扫码登录（需 Node.js ≥18）     │
│ 飞书 Feishu   │ App ID + Secret（WebSocket）  │
│ Mochat       │ Claw Token（可自动配置！）      │
│ 钉钉 DingTalk │ App Key + Secret（Stream）    │
│ Slack        │ Bot Token + App Token         │
│ Email        │ IMAP/SMTP 账号密码             │
│ QQ           │ App ID + Secret               │
│ 企业微信 Wecom │ Bot ID + Secret（WebSocket）  │
│ Matrix       │ Access Token + Device ID      │
└──────────────┴──────────────────────────────┘
```

### 每个平台的配置模式都相同：

```
1. 在对应平台创建 Bot
2. 获取凭证（Token/Key/Secret）
3. 写入 config.json
4. 运行 nanobot gateway
```

### Telegram 配置示例（最推荐）

```json
{
  "channels": {
    "telegram": {
      "enabled": true,                    // 启用
      "token": "YOUR_BOT_TOKEN",          // Bot Token
      "allowFrom": ["YOUR_USER_ID"]       // 白名单（安全控制）
    }
  }
}
```

### Mochat 的特别之处

Mochat 支持**一句话自动配置**：
```
Read https://raw.githubusercontent.com/HKUDS/MoChat/refs/heads/main/skills/nanobot/skill.md 
and register on MoChat. My Email account is xxx@xxx 
Bind me as your owner and DM me on MoChat.
```

> 直接发给 nanobot，它会**自动注册、配置、连接**——完全零手动操作。

### 安全机制：`allowFrom`

```json
"allowFrom": ["YOUR_USER_ID"]   // 只允许指定用户
"allowFrom": ["*"]              // 允许所有人
"allowFrom": []                 // 拒绝所有人（v0.1.4.post4+ 默认行为）
```

---

## 九、Agent 社交网络

```markdown
| 平台        | 加入方式                                    |
|------------|-------------------------------------------|
| Moltbook   | 发消息让 bot 读取 skill.md 并自动加入         |
| ClawdChat  | 发消息让 bot 读取 skill.md 并自动加入         |
```

> 这是一个**AI Agent 社区**概念——你的 nanobot 可以加入公共平台，与其他 Agent 交互。

---

## 十、配置详解（Configuration）

### 10.1 Providers（LLM 提供商）

支持 **17+ 个 LLM 提供商**：

```
┌──────────────────────────────────────────────────────┐
│                  Provider 分类                        │
├──────────────┬───────────────────────────────────────┤
│ 通用网关      │ openrouter, aihubmix（一个 key 用所有模型）│
│ 云端直连      │ openai, anthropic, deepseek, gemini...  │
│ 国内厂商      │ dashscope(通义), moonshot(Kimi),         │
│              │ zhipu(智谱), volcengine(火山), minimax    │
│ 本地部署      │ ollama, vllm, custom（任何 OpenAI 兼容）  │
│ OAuth 登录   │ openai_codex, github_copilot             │
└──────────────┴───────────────────────────────────────┘
```

### 添加新 Provider 只需 2 步

**步骤 1**：在 `registry.py` 添加 `ProviderSpec`：
```python
ProviderSpec(
    name="
```
