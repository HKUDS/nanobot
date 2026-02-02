# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **Token Usage Tracking**: New `nanobot/usage/` module to track LLM API token consumption and costs
  - `UsageTracker` class for recording and querying usage data
  - `UsageRecord`, `DailySummary`, and `GroupedStats` data models
  - Automatic cost extraction from LiteLLM responses (uses live pricing from api.litellm.ai)
  - Daily JSON storage in `~/.nanobot/usage/YYYY-MM-DD.json`
  - Breakdown by model and channel

- **Usage CLI Command**: New `nanobot usage` command to view token usage statistics
  - `nanobot usage` - Show today's usage and last 7 days summary
  - `nanobot usage --today` - Show today's usage only
  - `nanobot usage --days N` - Show usage for the last N days
  - `nanobot usage --by-model` - Show cost breakdown by model
  - `nanobot usage --by-channel` - Show cost breakdown by channel (cli/telegram/whatsapp)
  - Daily breakdown table for multi-day queries

- **Budget Alerts**: Configurable budget thresholds with CLI warnings
  - `usage.daily_budget_usd` - Daily spending limit
  - `usage.monthly_budget_usd` - Monthly spending limit
  - `usage.warn_at_percent` - Warning threshold percentage (default: 80%)
  - Displays warning when usage exceeds threshold
  - Displays alert when budget is exceeded

- **Proactive Budget Notifications**: Agent automatically sends budget alerts to chat channels
  - `BudgetMonitor` class monitors usage after each API call
  - Sends alerts to Telegram/WhatsApp when budget thresholds are reached
  - Cooldown mechanism prevents alert spam (1 hour between same alerts)
  - Supports both daily and monthly budget monitoring

### Changed

- `LLMResponse` dataclass now includes `cost_usd` field for per-request cost tracking
- `LiteLLMProvider` now extracts response cost from LiteLLM's hidden params
- `AgentLoop` now records usage after each LLM API call
- `Config` now includes `UsageConfig` for budget settings

## [0.1.3] - 2025-02-01

### Added

- Initial release of nanobot
- Core agent loop with tool execution
- Support for OpenRouter, Anthropic, OpenAI, and vLLM providers via LiteLLM
- Built-in tools: file operations, shell execution, web search/fetch, messaging
- Telegram and WhatsApp channel support
- Skills system with markdown-based skill definitions
- Heartbeat service for periodic task checking
- Cron service for scheduled jobs
- Session management with conversation history
