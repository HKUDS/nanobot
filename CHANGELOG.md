# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **Token Usage Tracking**: New `nanobot/usage/` module to track LLM API token consumption and costs
  - `UsageTracker` class for recording and querying usage data
  - `UsageRecord` and `DailySummary` data models
  - Automatic cost extraction from LiteLLM responses (uses live pricing from api.litellm.ai)
  - Daily JSON storage in `~/.nanobot/usage/YYYY-MM-DD.json`

- **Usage CLI Command**: New `nanobot usage` command to view token usage statistics
  - `nanobot usage` - Show today's usage and last 7 days summary
  - `nanobot usage --today` - Show today's usage only
  - `nanobot usage --days N` - Show usage for the last N days
  - Daily breakdown table for multi-day queries

### Changed

- `LLMResponse` dataclass now includes `cost_usd` field for per-request cost tracking
- `LiteLLMProvider` now extracts response cost from LiteLLM's hidden params
- `AgentLoop` now records usage after each LLM API call

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
