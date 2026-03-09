# QuantBot - 量化研究员配置

<div align="center">
  <h1>QuantBot</h1>
  <p>将 <a href="https://github.com/HKUDS/nanobot">nanobot</a> 定制化为量化研究员专用 AI 助手</p>
</div>

## 核心特性

| 特性 | 说明 |
|------|------|
| 📊 数据获取 | 实时 A 股行情、北向资金、行业板块、融资融券数据 |
| 📈 回测验证 | 基于 Qlib 的策略回测框架 |
| 💹 模拟交易 | 虚拟组合实时跟踪绩效 |
| 📝 版本管理 | 策略变更历史记录与回滚 |
| 🧠 专业 Skills | 10+ 量化研究专用技能（因子研究、风险管理、回测规范等） |
| 💬 多渠道接入 | 支持 Telegram、飞书、钉钉、Discord、微信等 9 个聊天平台 |
| 🔌 MCP 支持 | 接入 Model Context Protocol 外部工具服务器 |
| ⏰ 定时任务 | 自然语言创建定时任务，自动更新数据 |

---

## 安装

> [!TIP]
> QuantBot 使用 **uv** 管理 Python 环境，推荐使用 uv 安装。

**1. 安装 uv（如未安装）**

```bash
# macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# Windows (PowerShell)
irm https://astral.sh/uv/install.ps1 | iex
```

**2. 使用 uv 安装 nanobot**

```bash
uv tool install nanobot-ai
```

**3. 验证安装**

```bash
nanobot --version
```

### 更新版本

```bash
uv tool upgrade nanobot-ai
nanobot --version
```

---

## 快速开始

> [!TIP]
> 配置 API Key 于 `~/.nanobot/config.json`。
> 获取 API Key: [OpenRouter](https://openrouter.ai/keys)（推荐）或 [硅基流动](https://siliconflow.cn)

**1. 初始化**

```bash
nanobot onboard
```

**2. 配置** (`~/.nanobot/config.json`)

添加 API Key（以 OpenRouter 为例）:

```json
{
  "providers": {
    "openrouter": {
      "apiKey": "sk-or-v1-xxx"
    }
  }
}
```

可选：设置默认模型:

```json
{
  "agents": {
    "defaults": {
      "model": "anthropic/claude-sonnet-4-6",
      "provider": "openrouter"
    }
  }
}
```

**3. 添加量化研究 Skills**

```bash
# 复制内置 skills 到工作空间
cp -r /path/to/QuantBot/nanobot/skills/* ~/.nanobot/workspace/

# 复制 Agent 配置模板
cp /path/to/QuantBot/nanobot/templates/SOUL.md ~/.nanobot/workspace/
cp /path/to/QuantBot/nanobot/templates/AGENTS.md ~/.nanobot/workspace/
```

**4. 安装外部 Skills（可选）**

通过 ClawHub 安装更多量化研究 Skills：

```bash
npx --yes clawhub@latest install multi-search-engine --workdir ~/.nanobot/workspace
npx --yes clawhub@latest install stock-technical-analysis --workdir ~/.nanobot/workspace
npx --yes clawhub@latest install quiver --workdir ~/.nanobot/workspace
npx --yes clawhub@latest install akshare-stock --workdir ~/.nanobot/workspace
npx --yes clawhub@latest install akshare-finance --workdir ~/.nanobot/workspace
npx --yes clawhub@latest install fundamental-stock-analysis --workdir ~/.nanobot/workspace
```

| Skill                      | 说明                 |
| -------------------------- | -------------------- |
| multi-search-engine        | 多引擎联网搜索       |
| stock-technical-analysis   | 股票技术分析         |
| quiver                     | 美国国会议员持仓追踪 |
| akshare-stock              | A股量化数据          |
| akshare-finance            | 金融财经数据         |
| fundamental-stock-analysis | 基本面分析           |

**5. 启动**

```bash
nanobot gateway
```

即可开始与量化研究员 AI 助手对话！

---

## 💬 接入聊天渠道

将 QuantBot 接入你的聊天平台，随时随地进行量化研究对话。

| 渠道 | 所需凭证 |
|------|---------|
| **Telegram** | @BotFather 生成的 Bot token |
| **飞书 (Feishu)** | App ID + App Secret |
| **钉钉 (DingTalk)** | App Key + App Secret |
| **Discord** | Bot token + Message Content intent |
| **WhatsApp** | 扫码绑定设备 |
| **Slack** | Bot token + App-Level token |
| **QQ** | App ID + App Secret |
| **Email** | IMAP/SMTP 邮箱凭证 |
| **Matrix** | userId + accessToken |

<details>
<summary><b>Telegram（推荐）</b></summary>

**1. 创建 Bot**
- 打开 Telegram，搜索 `@BotFather`
- 发送 `/newbot`，按提示操作
- 复制 Bot token

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

> 在 Telegram 设置中可以找到你的 User ID（格式为 `@yourUserId`），填入时**不含 `@` 符号**。

**3. 启动**

```bash
nanobot gateway
```

</details>

<details>
<summary><b>飞书 (Feishu)</b></summary>

使用 **WebSocket** 长连接，无需公网 IP。

**1. 创建飞书应用**
- 访问[飞书开放平台](https://open.feishu.cn/app)
- 创建新应用 → 开启 **机器人** 能力
- **权限**: 添加 `im:message`（发送消息）和 `im:message.p2p_msg:readonly`（接收消息）
- **事件**: 添加 `im.message.receive_v1`，选择**长连接**模式
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
      "allowFrom": ["ou_YOUR_OPEN_ID"]
    }
  }
}
```

> `allowFrom` 中填入你的 open_id（首次给 Bot 发消息后在 nanobot 日志中可以找到）。用 `["*"]` 允许所有用户。

**3. 启动**

```bash
nanobot gateway
```

</details>

<details>
<summary><b>钉钉 (DingTalk)</b></summary>

使用 **Stream 模式**，无需公网 IP。

**1. 创建钉钉机器人**
- 访问[钉钉开放平台](https://open-dev.dingtalk.com/)
- 创建新应用 → 添加**机器人**能力 → 开启 **Stream 模式**
- 添加发送消息所需权限
- 从"凭证信息"获取 **AppKey** 和 **AppSecret**
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

**3. 启动**

```bash
nanobot gateway
```

</details>

<details>
<summary><b>Discord</b></summary>

**1. 创建 Bot**
- 访问 https://discord.com/developers/applications
- 创建应用 → Bot → Add Bot，复制 token

**2. 开启权限**
- 在 Bot 设置中，开启 **MESSAGE CONTENT INTENT**

**3. 配置**

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

> `groupPolicy`: `"mention"`（默认，仅 @ 时回复）或 `"open"`（响应所有消息）。

**4. 启动**

```bash
nanobot gateway
```

</details>

<details>
<summary><b>WhatsApp</b></summary>

需要 **Node.js ≥18**。

**1. 绑定设备**

```bash
nanobot channels login
# 用 WhatsApp → 设置 → 已关联设备 → 扫码
```

**2. 配置**

```json
{
  "channels": {
    "whatsapp": {
      "enabled": true,
      "allowFrom": ["+8613xxxxxxxxx"]
    }
  }
}
```

**3. 启动**（需两个终端）

```bash
# 终端 1
nanobot channels login

# 终端 2
nanobot gateway
```

> 升级 nanobot 后需重建本地桥接：`rm -rf ~/.nanobot/bridge && nanobot channels login`

</details>

<details>
<summary><b>Slack</b></summary>

使用 **Socket Mode**，无需公网 URL。

**1. 创建 Slack 应用**
- 访问 [Slack API](https://api.slack.com/apps) → **Create New App** → "From scratch"

**2. 配置应用**
- **Socket Mode**: 开启 → 生成带 `connections:write` scope 的 App-Level Token（`xapp-...`）
- **OAuth & Permissions**: 添加 bot scope: `chat:write`, `reactions:write`, `app_mentions:read`
- **Event Subscriptions**: 开启 → 订阅 `message.im`, `message.channels`, `app_mention`
- **Install App**: 安装到工作区，复制 Bot Token（`xoxb-...`）

**3. 配置**

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

**4. 启动**

```bash
nanobot gateway
```

</details>

<details>
<summary><b>QQ</b></summary>

使用 **botpy SDK** + WebSocket，无需公网 IP。目前仅支持私聊。

**1. 注册并创建 Bot**
- 访问 [QQ 开放平台](https://q.qq.com) → 注册开发者 → 创建机器人应用
- 进入**开发设置**，复制 **AppID** 和 **AppSecret**

**2. 沙箱测试配置**
- 在机器人控制台找到**沙箱配置** → 添加你的 QQ 号
- 用手机 QQ 扫描机器人二维码，点"发消息"开始测试

**3. 配置**

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

**4. 启动**

```bash
nanobot gateway
```

</details>

<details>
<summary><b>Email（邮件）</b></summary>

为 Bot 配置独立邮箱，通过 IMAP 轮询接收邮件，SMTP 回复。

**1. 获取凭证（Gmail 示例）**
- 创建专用 Gmail 账号，开启两步验证
- 创建 [App Password](https://myaccount.google.com/apppasswords)

**2. 配置**

```json
{
  "channels": {
    "email": {
      "enabled": true,
      "consentGranted": true,
      "imapHost": "imap.gmail.com",
      "imapPort": 993,
      "imapUsername": "my-bot@gmail.com",
      "imapPassword": "your-app-password",
      "smtpHost": "smtp.gmail.com",
      "smtpPort": 587,
      "smtpUsername": "my-bot@gmail.com",
      "smtpPassword": "your-app-password",
      "fromAddress": "my-bot@gmail.com",
      "allowFrom": ["your-email@gmail.com"]
    }
  }
}
```

> `consentGranted` 必须为 `true` 才能访问邮箱。设置 `"autoReplyEnabled": false` 可关闭自动回复。

**3. 启动**

```bash
nanobot gateway
```

</details>

<details>
<summary><b>Matrix (Element)</b></summary>

**1. 安装 Matrix 依赖**

```bash
pip install nanobot-ai[matrix]
```

**2. 获取凭证**

需要 `userId`、`accessToken`、`deviceId`（建议固定，避免 E2EE 会话丢失）。可从 `/_matrix/client/v3/login` API 或客户端高级设置中获取。

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
      "groupPolicy": "open"
    }
  }
}
```

**4. 启动**

```bash
nanobot gateway
```

</details>

---

## ⚙️ 配置说明

配置文件路径：`~/.nanobot/config.json`

### LLM Provider 配置

> [!TIP]
> - **OpenRouter** 是最推荐的选项，可接入所有主流模型，支持国内外。
> - **Groq** 提供免费的 Whisper 语音转写，配置后 Telegram 语音消息可自动转文字。
> - **硅基流动** 适合国内用户，支持 DeepSeek、Qwen 等国产模型。

| Provider | 用途 | 获取 API Key |
|----------|------|-------------|
| `openrouter` | LLM（推荐，接入所有模型） | [openrouter.ai](https://openrouter.ai) |
| `anthropic` | LLM（Claude 直连） | [console.anthropic.com](https://console.anthropic.com) |
| `openai` | LLM（GPT 直连） | [platform.openai.com](https://platform.openai.com) |
| `deepseek` | LLM（DeepSeek 直连） | [platform.deepseek.com](https://platform.deepseek.com) |
| `siliconflow` | LLM（硅基流动） | [siliconflow.cn](https://siliconflow.cn) |
| `groq` | LLM + 语音转写（Whisper） | [console.groq.com](https://console.groq.com) |
| `gemini` | LLM（Gemini 直连） | [aistudio.google.com](https://aistudio.google.com) |
| `dashscope` | LLM（通义千问） | [dashscope.console.aliyun.com](https://dashscope.console.aliyun.com) |
| `moonshot` | LLM（Moonshot/Kimi） | [platform.moonshot.cn](https://platform.moonshot.cn) |
| `zhipu` | LLM（智谱 GLM） | [open.bigmodel.cn](https://open.bigmodel.cn) |
| `volcengine` | LLM（火山引擎） | [volcengine.com](https://www.volcengine.com) |
| `azure_openai` | LLM（Azure OpenAI） | [portal.azure.com](https://portal.azure.com) |
| `aihubmix` | LLM（API 聚合网关） | [aihubmix.com](https://aihubmix.com) |
| `minimax` | LLM（MiniMax） | [platform.minimaxi.com](https://platform.minimaxi.com) |
| `vllm` | LLM（本地/OpenAI 兼容服务） | — |
| `custom` | 任意 OpenAI 兼容接口 | — |

<details>
<summary><b>使用自定义 / 本地模型</b></summary>

连接任意 OpenAI 兼容接口（LM Studio、llama.cpp、vLLM 等）：

```json
{
  "providers": {
    "custom": {
      "apiKey": "no-key",
      "apiBase": "http://localhost:8000/v1"
    }
  },
  "agents": {
    "defaults": {
      "model": "your-model-name"
    }
  }
}
```

</details>

### MCP（模型上下文协议）

nanobot 支持 [MCP](https://modelcontextprotocol.io/)，可接入外部工具服务器，配置格式与 Claude Desktop / Cursor 兼容。

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

| 模式 | 配置 | 说明 |
|------|------|------|
| **Stdio** | `command` + `args` | 通过 `npx` / `uvx` 启动本地进程 |
| **HTTP** | `url` + `headers`（可选） | 连接远程 MCP 端点 |

MCP 工具启动时自动发现并注册，LLM 可与内置工具一同调用，无需额外配置。

### 安全配置

> [!TIP]
> 生产环境建议设置 `"restrictToWorkspace": true` 对 Agent 进行沙箱隔离。
> 自 v0.1.4.post4 起，空的 `allowFrom` 默认**拒绝所有**访问。如需允许所有用户，设置 `"allowFrom": ["*"]`。

| 选项 | 默认值 | 说明 |
|------|--------|------|
| `tools.restrictToWorkspace` | `false` | 为 `true` 时，将 Shell/文件工具限制在工作空间目录内，防止路径穿越 |
| `tools.exec.pathAppend` | `""` | 执行 Shell 命令时追加到 `PATH` 的目录 |
| `channels.*.allowFrom` | `[]`（拒绝所有） | 允许访问的用户 ID 白名单；`["*"]` 允许所有人 |

---

## 💻 CLI 命令参考

| 命令 | 说明 |
|------|------|
| `nanobot onboard` | 初始化配置和工作空间 |
| `nanobot agent -m "..."` | 与 Agent 对话（单次） |
| `nanobot agent` | 交互式对话模式 |
| `nanobot agent -w <workspace>` | 指定工作空间对话 |
| `nanobot agent --no-markdown` | 纯文本输出模式 |
| `nanobot agent --logs` | 对话时显示运行日志 |
| `nanobot gateway` | 启动网关（连接所有启用的渠道）|
| `nanobot status` | 显示状态信息 |
| `nanobot provider login openai-codex` | OAuth 登录（Codex 等） |
| `nanobot channels login` | 绑定渠道（如 WhatsApp 扫码）|
| `nanobot channels status` | 显示渠道状态 |

交互模式退出命令：`exit`、`quit`、`/exit`、`/quit`、`:q` 或 `Ctrl+D`。

---

## 🧩 多实例运行

使用 `--config` 同时运行多个 QuantBot 实例，各实例拥有独立配置和数据目录。

```bash
# 实例 A - Telegram
nanobot gateway --config ~/.nanobot-telegram/config.json

# 实例 B - 飞书
nanobot gateway --config ~/.nanobot-feishu/config.json

# 实例 C - 指定端口
nanobot gateway --config ~/.nanobot-discord/config.json --port 18792
```

**最简配置示例（`~/.nanobot-telegram/config.json`）：**

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

> 各实例需使用不同端口；每实例独立 workspace 可隔离记忆、会话和 Skills。

---

## 💓 Heartbeat（周期性任务）

Gateway 每 30 分钟自动检查工作空间中的 `HEARTBEAT.md`，执行其中的任务并将结果发送到最近活跃的聊天渠道。

编辑 `~/.nanobot/workspace/HEARTBEAT.md`：

```markdown
## Periodic Tasks

- [ ] 检查 A 股市场今日行情摘要
- [ ] 监控关注股票的异动信号
- [ ] 推送北向资金最新动向
```

也可以直接告诉 Agent："帮我添加一个每天早盘前检查大盘情绪的定时任务"，Agent 会自动更新 `HEARTBEAT.md`。

> Gateway 必须保持运行（`nanobot gateway`），且与 Bot 至少交互过一次，才能确定发送目标渠道。

---

## 🐳 Docker 部署

```bash
# 首次初始化
docker compose run --rm nanobot-cli onboard
vim ~/.nanobot/config.json   # 填入 API Key

# 启动 Gateway
docker compose up -d nanobot-gateway

# 查看日志
docker compose logs -f nanobot-gateway
```

---

## 🐧 Linux 系统服务（systemd）

将 Gateway 注册为 systemd 用户服务，开机自启、崩溃自动重启。

**1. 查找 nanobot 路径**

```bash
which nanobot   # 例如 /home/user/.local/bin/nanobot
```

**2. 创建服务文件** `~/.config/systemd/user/nanobot-gateway.service`

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

**3. 启用并启动**

```bash
systemctl --user daemon-reload
systemctl --user enable --now nanobot-gateway
```

**常用操作**

```bash
systemctl --user status nanobot-gateway    # 查看状态
systemctl --user restart nanobot-gateway   # 重启（修改配置后）
journalctl --user -u nanobot-gateway -f    # 实时查看日志
```

> 注销后如需保持运行：`loginctl enable-linger $USER`

---

## Python 运行环境

QuantBot 使用 **uv** 管理 Python 环境，所有依赖都运行在 uv 创建的工具环境中。

```bash
# 查看已安装的工具
uv tool list

# 查看 nanobot 详细信息
uv tool show nanobot-ai

# 卸载 nanobot
uv tool uninstall nanobot-ai
```

### Agent 运行 Python 程序

当 Agent 需要执行 Python 程序（如数据更新脚本、回测程序等）时：

```bash
# 推荐：使用 uv run，自动使用工具环境
uv run python scripts/db_daily_update.py
```

> Agent 在执行 Python 程序时会自动使用 `uv run` 调用，无需额外配置。

---

## 配置文件

### SOUL.md - 量化研究员人格定义

路径: `~/.nanobot/workspace/SOUL.md`

定义量化研究员的核心角色和价值观：

- **角色**: 兼具学术严谨与实践智慧的专业量化研究员
- **价值观**: 数据驱动、理性客观、风险意识、持续学习
- **沟通风格**: 专业但易懂、结论先行、逻辑清晰
- **边界**: 不提供具体买卖建议、不承诺收益、不替代人工决策
- **交互原则**: "确认优先" - 任何写操作需用户确认

### AGENTS.md - 工作风格指引

路径: `~/.nanobot/workspace/AGENTS.md`

定义量化研究的工作规范：

- **代码规范**: PEP 8 标准、变量命名规则、注释要求
- **回测规范**: 数据要求、成本假设、评估指标
- **研究流程**: 因子挖掘 → 验证 → 组合 → 回测 → 实盘
- **偏好设置**: 工具选择、输出格式、学习来源

---

## 内置 Skills

| Skill | 说明 |
|-------|------|
| quant_fundamentals | 量化基础知识 - EMH, MPT, CAPM, 因子模型 |
| a_share_rules | A股特有规则 - T+1, 涨跌停, 融资融券 |
| backtest_standards | 回测规范 - 防过拟合, 成本假设, 评估指标 |
| strategy_design | 策略设计方法论 - 趋势/均值回归/套利 |
| market_analysis | 市场分析框架 - 宏观周期, 行业轮动, 资金流向 |
| us_to_ashare_signal | 美股→A股信号传导 |
| risk_management | 风险管理 - VaR, CVaR, 仓位管理 |
| factor_research | 因子研究 - IC, ICIR, 因子正交化 |
| ml_quant | ML量化方法论 - 特征工程, 过拟合防范 |
| portfolio_optimization | 组合优化 - Markowitz, 风险平价 |

---

## 配套工具

QuantBot 提供以下内置工具，辅助量化研究工作：

| 工具 | 说明 |
|------|------|
| quant_data | 实时获取 A 股行情、北向资金、行业板块、融资融券等数据 |
| quant_tech | 技术分析 - K线形态、均线交叉、MACD/KDJ/RSI/BOLL 指标 |
| quant_ipo | 新股新债 - 申购日历、上市日历、打新收益率统计 |
| quant_etf | ETF/REITs - ETF行情、溢价率、LOF套利机会 |
| quant_fund | 资金流向 - 主力资金、龙虎榜、机构买卖、北向资金 |
| quant_financial | 基本面 - 财报指标、业绩预告、分红送转、PE/PB估值 |
| quant_futures | 期货期权 - 股指期货、期权行情、Greeks计算 |
| quant_export | 数据导出 - 批量查询、CSV/Excel导出 |
| db_reader | 从本地 SQLite 数据库读取历史数据（每日自动更新） |
| qlib_backtest | 基于 Qlib 的策略回测框架 |
| paper_trading | 模拟交易，实时监控策略绩效 |
| strategy_git | 策略版本管理，记录变更历史 |

### 本地数据库

数据存储在项目目录 `config/data/market_data.db`，每日 20:00 自动更新：

```bash
# 手动更新数据
cd /path/to/QuantBot && python3 scripts/db_daily_update.py
```

**数据库表结构：**

| 表名 | 内容 |
|------|------|
| `daily_quotes` | 个股日行情 |
| `index_quotes` | 指数日行情 |
| `north_fund_flow` | 北向资金流向 |
| `margin_trading` | 融资融券 |
| `industry_quotes` | 行业板块涨跌 |

### Cron 定时任务

配置定时数据更新（编辑 crontab）：

```bash
# 每日 20:00 更新市场数据（周一至周五）
0 20 * * 1-5 cd $QUANTBOT_DIR && python3 scripts/db_daily_update.py
```

参考配置见 `config/crontab.example`。

### 策略开发流程

```
quant_data（获取数据）→ qlib_backtest（回测验证）→ paper_trading（模拟交易）→ strategy_git（版本管理）
```

---

## 相关链接

- 原始项目: [https://github.com/HKUDS/nanobot](https://github.com/HKUDS/nanobot)
- ClawHub Skills 市场: [https://clawhub.ai](https://clawhub.ai)
