# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**nanobot** is an ultra-lightweight (~4,000 lines) personal AI assistant framework that connects to multiple chat platforms (Telegram, Discord, WhatsApp, Feishu, QQ, DingTalk, Slack, Email, Matrix) and LLM providers. Designed for research and easy extension.

## Commands

```bash
# Install for development
pip install -e ".[dev]"

# Run tests
pytest

# Lint and format
ruff check .
ruff format .

# CLI commands
nanobot onboard           # Initialize config & workspace
nanobot agent -m "..."    # Chat with the agent
nanobot gateway           # Start the gateway (connects to all enabled channels)
nanobot status            # Show status
nanobot provider login openai-codex  # OAuth login
nanobot channels login    # Link WhatsApp (scan QR)
nanobot channels status   # Show channel status
```

## Architecture

```
nanobot/
├── agent/           # Core agent logic
│   ├── loop.py      # LLM ↔ tool execution loop
│   ├── context.py   # Prompt builder with caching
│   ├── memory.py    # Persistent conversation memory
│   ├── skills.py    # Skills loader
│   ├── subagent.py  # Background task execution
│   └── tools/       # Built-in tools (shell, filesystem, spawn, cron, mcp, web, message)
├── channels/        # Chat platform integrations (telegram, discord, whatsapp, feishu, etc.)
├── providers/       # LLM providers via LiteLLM
├── skills/          # Bundled skills (github, weather, tmux, cron, memory, skill-creator...)
├── bus/             # Message routing between channels and agent
├── cron/            # Scheduled task execution
├── heartbeat/       # Periodic proactive tasks (checks HEARTBEAT.md)
├── config/          # Configuration loading and schema
├── session/         # Conversation session management
└── cli/             # CLI commands (typer)
```

## Key Files

- `nanobot/providers/registry.py` - Provider registry (add new providers in 2 steps)
- `nanobot/config/schema.py` - Configuration schema (Pydantic models)
- `nanobot/channels/base.py` - Base channel class
- `nanobot/agent/loop.py` - Main agent loop
- `nanobot/agent/tools/registry.py` - Tool registration

## Adding a New Provider

Adding a new LLM provider takes **2 steps** (no if-elif chains):

1. Add a `ProviderSpec` entry to `PROVIDERS` in `nanobot/providers/registry.py`
2. Add a field to `ProvidersConfig` in `nanobot/config/schema.py`

## Important Patterns

- **Multi-instance**: Use `--config` to run multiple nanobot instances with separate configs
  ```bash
  nanobot gateway --config ~/.nanobot-telegram/config.json
  ```
- **Workspace isolation**: Use `restrictToWorkspace: true` to sandbox agent tools
- **Access control**: In v0.1.4.post3+, empty `allowFrom` denies all access — use `["*"]` to allow everyone

## Gotchas

- Empty `allowFrom` now denies all access by default (v0.1.4.post3+)
- File operations have path traversal protection
- Dangerous shell commands are blocked (rm -rf /, fork bombs, etc.)
- WhatsApp requires Node.js ≥18 for the bridge
- Matrix E2EE requires persistent deviceId and matrix-store

## Testing

Tests are in `tests/` directory. Run specific tests with:
```bash
pytest tests/test_cron_service.py -v
```

## Quant Researcher Skills

QuantBot includes specialized skills for quantitative investment research:

### Built-in Skills (in `nanobot/skills/`)

| Skill | Description |
|-------|-------------|
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

### Workspace Skills (in `~/.nanobot/workspace/`)

User-installed skills for quantitative research:
- multi-search-engine - 多引擎联网搜索
- stock-technical-analysis - 股票技术分析
- quiver - 美国国会议员持仓追踪
- akshare-stock - A股量化数据
- akshare-finance - 金融财经数据
- fundamental-stock-analysis - 基本面分析

### Configuration Files

- `~/.nanobot/workspace/SOUL.md` - 量化研究员人格定义
- `~/.nanobot/workspace/AGENTS.md` - 工作风格指引

See project README.md for detailed documentation.
