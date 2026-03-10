<div align="center">
  <img src="nanobot_logo.png" alt="nanobot" width="500">
  <h1>nanobot：超轻量个人 AI 助手</h1>
  <p>
    <a href="https://pypi.org/project/nanobot-ai/"><img src="https://img.shields.io/pypi/v/nanobot-ai" alt="PyPI"></a>
    <a href="https://pepy.tech/project/nanobot-ai"><img src="https://static.pepy.tech/badge/nanobot-ai" alt="Downloads"></a>
    <img src="https://img.shields.io/badge/python->=3.11-blue" alt="Python">
    <img src="https://img.shields.io/badge/license-MIT-green" alt="License">
  </p>
</div>

<p align="center">
  <b>语言:</b> <a href="./README.md">English</a> | 简体中文
</p>

`nanobot` 是一个受 [OpenClaw](https://github.com/openclaw/openclaw) 启发的超轻量个人 AI 助手框架。
它强调代码简洁、部署直接、可快速扩展，适合个人使用和研究实验。

## 核心特性

- 超轻量：核心 Agent 代码量小，启动和迭代快。
- 易扩展：Provider、Channel、Tool 设计清晰，便于二次开发。
- 多平台接入：支持 Telegram、Discord、Slack、QQ、Feishu、WhatsApp 等。
- MCP 支持：可与 MCP Server 连接，扩展工具能力。
- 默认更安全：支持工作区限制，降低越权读写风险。

## 安装

从源码安装（开发推荐）：

```bash
git clone https://github.com/HKUDS/nanobot.git
cd nanobot
pip install -e .
```

使用 `uv` 安装（快速稳定）：

```bash
uv tool install nanobot-ai
```

从 PyPI 安装：

```bash
pip install nanobot-ai
```

升级到最新版本：

```bash
pip install -U nanobot-ai
nanobot --version
```

## 快速开始

1. 初始化工作区：

```bash
nanobot onboard
```

2. 编辑配置文件 `~/.nanobot/config.json`，至少设置 API Key 和模型：

```json
{
  "providers": {
    "openrouter": {
      "apiKey": "sk-or-v1-xxx"
    }
  },
  "agents": {
    "defaults": {
      "model": "anthropic/claude-opus-4-5",
      "provider": "openrouter"
    }
  },
  "tools": {
    "restrictToWorkspace": true
  }
}
```

3. 启动对话：

```bash
nanobot agent
```

## 聊天平台支持

| 平台 | 需要准备 |
| --- | --- |
| Telegram | Bot Token（@BotFather） |
| Discord | Bot Token + Message Content Intent |
| WhatsApp | 扫码登录 |
| Feishu | App ID + App Secret |
| Mochat | Claw Token |
| DingTalk | App Key + App Secret |
| Slack | Bot Token + App-Level Token |
| Email | IMAP/SMTP 凭据 |
| QQ | App ID + App Secret |

详细配置示例和字段说明请查看英文主文档。

## 常用命令

```bash
# 交互式运行
nanobot agent

# 指定配置文件
nanobot agent -c ~/.nanobot/config.json

# 渠道登录向导（如 Telegram/WhatsApp 等）
nanobot channels login
```

## 文档导航

- 完整项目说明：[`README.md`](./README.md)
- 安全策略：[`SECURITY.md`](./SECURITY.md)
- 社群与沟通：[`COMMUNICATION.md`](./COMMUNICATION.md)

## 许可证

本项目基于 MIT 许可证发布。
