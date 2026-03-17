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

## 继续：Provider 系统详解

### 添加新 Provider 只需 2 步（续）

**步骤 1**：在 `registry.py` 添加 `ProviderSpec`：
```python
ProviderSpec(
    name="my_provider",           # 提供商名称
    env_var="MY_PROVIDER_KEY",    # 环境变量名
    model_prefix="my_provider/",  # 模型前缀（litellm 路由用）
    default_model="my_provider/gpt-4o",  # 默认模型
)
```

**步骤 2**：在 `.env` 中配置 API Key：
```bash
MY_PROVIDER_KEY=sk-xxxxxxxxxxxx
```

> **为什么这么简单**：底层统一使用 `litellm` 库，它已经兼容了 100+ 模型 API 格式，nanobot 只需做一层薄薄的注册映射。

---

## 八、频道系统（Channels）

文档中支持的频道（即用户交互渠道）：

```
┌──────────────┬──────────────────────────────────────┐
│ 类别          │ 支持的频道                             │
├──────────────┼──────────────────────────────────────┤
│ 即时通讯      │ Telegram, Discord, Slack,             │
│              │ 飞书(Feishu), 企业微信(WeCom),         │
│              │ WhatsApp, Matrix, QQ                  │
├──────────────┼──────────────────────────────────────┤
│ 终端          │ CLI（命令行交互）                       │
├──────────────┼──────────────────────────────────────┤
│ Web API      │ Gateway HTTP 接口                      │
└──────────────┴──────────────────────────────────────┘
```

### 频道的统一架构

```
用户消息 → Channel Adapter → MessageBus → Agent → MessageBus → Channel Adapter → 回复用户
```

每个频道只需实现一个 **Adapter（适配器）**：
- `on_message()` — 接收消息，发布到消息总线
- `send_reply()` — 从消息总线订阅回复，发送给用户

> **设计亮点**：所有频道共享同一个 Agent 内核，新增频道不影响核心逻辑。

---

## 九、MCP 协议支持

```
MCP = Model Context Protocol（模型上下文协议）
```

这是 Anthropic 提出的**工具调用标准协议**，让 AI 可以调用外部工具：

```
┌─────────┐     MCP协议      ┌─────────────────┐
│  Agent   │ ←──────────────→ │  MCP Server      │
│ (nanobot)│   stdio / SSE    │ (外部工具服务)     │
└─────────┘                   │ - 文件系统操作     │
                              │ - 数据库查询       │
                              │ - 网页浏览         │
                              │ - 代码执行         │
                              └─────────────────┘
```

### 配置方式

在 `nanobot.yaml` 中：
```yaml
mcp:
  servers:
    filesystem:
      command: "npx"
      args: ["-y", "@anthropic/mcp-filesystem"]
    browser:
      command: "npx"
      args: ["-y", "@anthropic/mcp-browser"]
```

> nanobot 支持两种 MCP 传输方式：**stdio**（本地进程通信）和 **SSE**（远程 HTTP 流式通信）。

---

## 十、技能系统（Skills）

```yaml
skills:
  - name: "web_search"
    description: "搜索互联网获取最新信息"
  - name: "code_interpreter"
    description: "执行 Python 代码"
```

Skills 与 MCP Tools 的区别：

| 对比项 | Skills | MCP Tools |
|--------|--------|-----------|
| 定义位置 | nanobot 内置 | 外部 MCP Server |
| 调用方式 | 直接函数调用 | 通过 MCP 协议 |
| 适用场景 | 简单、高频操作 | 复杂、需要隔离的操作 |

---

## 十一、定时任务（Cron）

```yaml
cron:
  tasks:
    - name: "daily_summary"
      schedule: "0 9 * * *"        # 每天早上9点
      action: "总结昨天的重要新闻"
    - name: "weather_reminder"
      schedule: "0 8 * * *"        # 每天早上8点
      action: "查看今天天气并提醒"
```

> 使用标准 **cron 表达式**，支持 AI 自主执行定时任务。

---

## 十二、安装与快速启动

### 安装方式

```bash
# 方式一：pip 安装（推荐）
pip install nanobot-ai

# 方式二：源码安装（开发用）
git clone https://github.com/HKUDS/nanobot.git
cd nanobot
pip install -e ".[all]"
```

### 初始化

```bash
nanobot onboard
```

这个命令会：
```
1. 创建 ~/.nanobot/ 工作空间目录
2. 生成 nanobot.yaml 配置文件模板
3. 生成 .env 环境变量文件模板
4. 复制默认的 system prompt 模板
```

### 启动对话

```bash
# CLI 直接对话
nanobot agent

# 启动网关服务器（供频道接入）
nanobot gateway
```

---

## 十三、配置文件结构

```
~/.nanobot/                      # 工作空间根目录
├── nanobot.yaml                 # 主配置文件
├── .env                         # API Keys 等敏感信息
├── templates/                   # 系统 prompt 模板
│   └── system_prompt.md
├── memory/                      # 持久化记忆存储
│   └── *.json
├── sessions/                    # 会话历史
│   └── *.json
└── logs/                        # 运行日志
    └── nanobot.log
```

### `nanobot.yaml` 核心配置项

```yaml
# AI 提供商配置
provider:
  name: openai                   # 使用哪个提供商
  model: gpt-4o                  # 默认模型

# 频道配置
channels:
  telegram:
    enabled: true
    token: ${TELEGRAM_BOT_TOKEN}  # 引用 .env 变量
  discord:
    enabled: false

# Agent 行为配置
agent:
  max_turns: 20                  # 单次对话最大轮数
  temperature: 0.7               # 生成温度
  streaming: true                # 是否流式输出

# MCP 工具
mcp:
  servers: { ... }

# 定时任务
cron:
  tasks: [ ... ]
```

---

## 十四、与 OpenClaw 的对比

这是文档反复强调的核心卖点：

```
┌─────────────────┬────────────┬────────────────┐
│ 对比维度         │ OpenClaw   │ nanobot        │
├─────────────────┼────────────┼────────────────┤
│ 核心代码行数     │ ~数万行     │ ~数百行         │
│ 代码精简比       │ 100%       │ ~1%            │
│ 功能覆盖         │ 企业级全面  │ 核心功能完整    │
│ 上手难度         │ 较高       │ 极低            │
│ 适合场景         │ 生产部署   │ 学习/研究/个人  │
│ 依赖复杂度       │ 高         │ 低              │
│ 启动速度         │ 较慢       │ 极快            │
└─────────────────┴────────────┴────────────────┘
```

> **核心理念**：用 99% 更少的代码实现 80% 的核心功能。

---

## 十五、项目元信息

### 许可证

```
MIT License — 最宽松的开源协议
✓ 可商用  ✓ 可修改  ✓ 可分发  ✓ 无需开源衍生作品
```

### 目标受众

```
📚 学生/研究者  — 学习 AI Agent 架构
🔧 开发者      — 快速搭建个人 AI 助手
🧪 实验者      — 测试各种 LLM 提供商和工具
```

### Star History

```
文档底部的 Star History 图表展示 GitHub star 数量的增长趋势，
用于体现项目热度和社区关注度。
```

---

## 十六、总结：文档的写作技巧

这份 README 是**开源项目文档的优秀范例**，值得学习的技巧：

| 技巧 | 体现 |
|------|------|
| **一句话定位** | "Ultra-Lightweight Personal AI Assistant" |
| **数字说话** | "99% fewer lines of code" |
| **可验证** | 提供 `core_agent_lines.sh` 脚本 |
| **渐进式信息** | 徽章 → 简介 → 特性 → 架构 → 安装 → 配置 → 高级用法 |
| **视觉化** | Logo、架构图、表格、emoji |
| **活跃度展示** | 密集的 News 更新日志 |
| **社区引导** | 飞书/微信/Discord 多渠道 |
| **折叠长内容** | `<details>` 标签隐藏历史新闻 |
| **免责声明** | "for educational, research purposes only" |
