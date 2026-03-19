# Getting Started Guide

Welcome to **nanobot** — an ultra-lightweight personal AI assistant framework that supports 16+ chat platforms, multiple LLM providers, and MCP integration.

This section guides you from installation to your first conversation with your AI assistant in just a few minutes.

---

## Contents

<div class="grid cards" markdown>

-   :material-download-box:{ .lg .middle } **Installation**

    ---

    System requirements, installation methods (pip / uv / source / Docker), and common troubleshooting.

    [:octicons-arrow-right-24: Installation Guide](installation.md)

-   :material-rocket-launch:{ .lg .middle } **Quick Start**

    ---

    Complete setup in 5 minutes and get nanobot running on Telegram or CLI.

    [:octicons-arrow-right-24: Quick Start](quick-start.md)

-   :material-wizard-hat:{ .lg .middle } **Onboarding Wizard**

    ---

    Learn each step of the `nanobot onboard` wizard in depth, and how to customize workspace templates.

    [:octicons-arrow-right-24: Onboarding Wizard](onboarding.md)

</div>

---

## Learning Path

```
Install nanobot
    ↓
Run nanobot onboard (initialize config and workspace)
    ↓
Edit ~/.nanobot/config.json (set API keys and model)
    ↓
nanobot agent (chat in CLI)
    ↓
Connect chat channels (Telegram / Discord / Slack, etc.)
    ↓
nanobot gateway (start gateway and receive real-time messages)
```

## Prerequisites

Before you start, make sure you have:

| Requirement | Description |
|------|------|
| **Python 3.11+** | nanobot requires Python 3.11 or newer |
| **uv** (recommended) or **pip** | Python package manager |
| **LLM API key** | Such as OpenRouter, Anthropic, OpenAI, etc. |
| **(Optional) Chat platform Bot Token** | Such as Telegram Bot Token, if you want to connect chat platforms |

!!! tip "Recommended for beginners"
    If you are not sure where to get an API key, we recommend [OpenRouter](https://openrouter.ai/keys). It supports mainstream models worldwide and offers a free tier.

## Most Common Questions

**Q: Which LLMs does nanobot support?**

It supports 20+ LLM providers, including OpenAI, Anthropic Claude, Google Gemini, DeepSeek, Qwen, local Ollama, and more. See [Providers docs](../providers/index.md) for details.

**Q: Do I need a public IP?**

No. Most chat channels (Telegram, Discord, Feishu, DingTalk, Slack) use long-lived WebSocket connections or Socket Mode and do not require a public IP.

**Q: How many resources does nanobot use?**

Very little. nanobot core has only around 16,000 lines of Python code, with fast startup and very low memory usage.