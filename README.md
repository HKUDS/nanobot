<picture>
  <source media="(prefers-color-scheme: dark)" srcset="./images/readme-cover-dark.png">
  <img alt="blackcat README cover" src="./images/readme-cover-light.png">
</picture>

<div align="center">
  <p>
    <a href="https://blackcat.wiki/docs/latest/getting-started/blackcat-overview">English</a> |
    <a href="https://blackcat.wiki/cn/docs/latest/getting-started/blackcat-overview">简体中文</a> |
    <a href="https://blackcat.wiki/zh-Hant/docs/latest/getting-started/blackcat-overview">繁體中文</a> |
    <a href="https://blackcat.wiki/es/docs/latest/getting-started/blackcat-overview">Español</a> |
    <a href="https://blackcat.wiki/fr/docs/latest/getting-started/blackcat-overview">Français</a> |
    <a href="https://blackcat.wiki/id/docs/latest/getting-started/blackcat-overview">Bahasa Indonesia</a> |
    <a href="https://blackcat.wiki/ja/docs/latest/getting-started/blackcat-overview">日本語</a> |
    <a href="https://blackcat.wiki/ko/docs/latest/getting-started/blackcat-overview">한국어</a> |
    <a href="https://blackcat.wiki/ru/docs/latest/getting-started/blackcat-overview">Русский</a> |
    <a href="https://blackcat.wiki/vi/docs/latest/getting-started/blackcat-overview">Tiếng Việt</a>
  </p>
  <p>
    <a href="https://pypi.org/project/blackcat-ai/"><img src="https://img.shields.io/pypi/v/blackcat-ai" alt="PyPI"></a>
    <a href="https://pepy.tech/project/blackcat-ai"><img src="https://static.pepy.tech/badge/blackcat-ai" alt="Downloads"></a>
    <img src="https://img.shields.io/badge/python-≥3.11-blue" alt="Python">
    <img src="https://img.shields.io/badge/license-MIT-green" alt="License">
    <a href="https://github.com/HKUDS/blackcat/graphs/commit-activity" target="_blank">
        <img alt="Commits last month" src="https://img.shields.io/github/commit-activity/m/HKUDS/blackcat?labelColor=%20%2332b583&color=%20%2312b76a"></a>
    <a href="https://github.com/HKUDS/blackcat/issues?q=is%3Aissue%20is%3Aclosed" target="_blank">
        <img alt="Issues closed" src="https://img.shields.io/github/issues-search?query=repo%3AHKUDS%2Fblackcat%20is%3Aissue%20is%3Aclosed&label=issues%20closed&labelColor=%20%237d89b0&color=%20%235d6b98"></a>
    <a href="https://twitter.com/intent/follow?screen_name=blackcat_project" target="_blank">
        <img src="https://img.shields.io/twitter/follow/blackcat_project?logo=X&color=%20%23f5f5f5" alt="follow on X(Twitter)"></a>
    <a href="https://blackcat.wiki/docs/latest/getting-started/blackcat-overview"><img src="https://img.shields.io/badge/Docs-blackcat.wiki-blue?style=flat&logo=readthedocs&logoColor=white" alt="Docs"></a>
    <a href="./COMMUNICATION.md"><img src="https://img.shields.io/badge/Feishu-Group-E9DBFC?style=flat&logo=feishu&logoColor=white" alt="Feishu"></a>
    <a href="./COMMUNICATION.md"><img src="https://img.shields.io/badge/WeChat-Group-C5EAB4?style=flat&logo=wechat&logoColor=white" alt="WeChat"></a>
    <a href="https://discord.gg/MnCvHqpUGB"><img src="https://img.shields.io/badge/Discord-Community-5865F2?style=flat&logo=discord&logoColor=white" alt="Discord"></a>
  </p>
</div>

🐈 **blackcat** is an open-source, ultra-lightweight personal AI agent you can truly own. It keeps the agent core small and readable while giving you the practical pieces for real long-running work: WebUI, chat channels, tools, memory, MCP, model routing, automation, and deployment.

## Start Here

| You want to... | Go to |
|---|---|
| Install blackcat with no terminal/config background | [Start Without Technical Background](./docs/start-without-technical-background.md) |
| Install quickly and get one CLI reply | [Install](#-install) and [Quick Start](#-quick-start) |
| Open the bundled browser UI after the CLI works | [WebUI](#-webui) |
| Connect Telegram, Discord, WeChat, Slack, Email, or another chat app | [Chat Apps](./docs/chat-apps.md) |
| Configure providers, fallback models, Langfuse, MCP, web tools, or security | [Docs](./docs/README.md) and [Configuration](./docs/configuration.md) |
| Understand or extend the internals | [Architecture](./docs/architecture.md) and [Development](./docs/development.md) |

## Open Source Partners

<p align="center">
  <a href="https://platform.kimi.com?aff=blackcat"><picture><source media="(prefers-color-scheme: dark)" srcset="https://kimi-file.moonshot.cn/prod-chat-kimi/kfs/4/1/2026-06-05/1d8h69mt3v89kkekg24gg"><img alt="Kimi Open Source Friends" height="44" src="https://kimi-file.moonshot.cn/prod-chat-kimi/kfs/4/1/2026-06-05/1d8h69fudcmosb3pipls0"></picture></a>
  <a href="https://platform.minimaxi.com/subscribe/token-plan?code=GILTJpMTqZ&source=link"><img alt="MiniMax" height="40" src="https://mintcdn.com/minimax-zh/1UjvBcdoC6r0UeyA/logo/light.svg?fit=max&auto=format&n=1UjvBcdoC6r0UeyA&q=85&s=672d724b639b2d88d0702fae329ea4f8"></a>
</p>

## 📢 News

- **2026-06-01** 🚀 Released **v0.2.1** — **The Workbench Release** turns the packaged WebUI into a daily agent workbench: clearer Thought/response timelines, live file-edit activity, project workspaces, model and context controls, steadier sustained goals, CLI Apps + MCP extensions, and broader provider/channel support. Please see [release notes](https://github.com/HKUDS/blackcat/releases/tag/v0.2.1) for details.
- **2026-05-30** 🔐 Safer Matrix verification, bounded media downloads, clearer WebUI model timeline.
- **2026-05-29** 🧩 Extension registry, context-window tuning, document extraction controls.
- **2026-05-28** 🗂️ Project workspaces, access controls, steadier goals and streaming.
- **2026-05-27** ⏱️ Codex streams respect idle timeouts during long runs.
- **2026-05-26** 📡 Telegram webhooks, refreshed Kagi search, cleaner transport errors.
- **2026-05-25** 🔌 Unified CLI Apps and MCP, Step Plan support, steadier sustained goals.
- **2026-05-24** 🧰 MCP presets, richer slash actions, configurable OpenAI-compatible requests.
- **2026-05-23** 🖼️ Zhipu image generation, longer exec windows, cleaner transcription config.
- **2026-05-22** 🛠️ CLI Apps, more image providers, safer web redirects and edits.

<details>
<summary>Earlier news</summary>

- **2026-05-21** ⚡ Novita provider, faster sidebar, smoother coding tools and Weixin replies.
- **2026-05-20** 📶 Signal channel, faster gateway startup, multilingual README links.
- **2026-05-19** 🎨 Image provider registry, StepFun and Skywork, stronger WebUI controls.
- **2026-05-18** 🖌️ Gemini and MiniMax images, Ant Ling, live file-edit activity.
- **2026-05-17** 🌊 Smoother WebUI streaming, AutoCompact fixes, buffered CLI reasoning.
- **2026-05-16** 🧠 Atomic Chat provider, goal-aware timeouts, safer exec URL handling.
- **2026-05-15** 🚀 Released **v0.2.0** — **`/goal`** holds sustained objectives across turns, WebUI now ships inside the wheel, image generation end to end, 5 new providers with `fallback_models`, and a real agent-loop refactor. Please see [release notes](https://github.com/HKUDS/blackcat/releases/tag/v0.2.0) for details.
- **2026-05-14** 🎯 **`/goal`** for long-term objectives, visible multi-step progress, long-horizon missions in chat.
- **2026-05-13** 🧠 Streaming reasoning before answers, automatic backup models, smoother plug-in reconnects.
- **2026-05-12** 🎛️ Saved model presets with WebUI badge, simpler plug-in tools, quieter Feishu topic threads.
- **2026-05-11** 🖥️ NVIDIA NIM support, terminal bot name and icon, streamed reasoning and MiMo toggle clarity.
- **2026-05-09** 🖼️ Sharper image replay, BYO web-search keys in Settings, Feishu threads routed cleanly.
- **2026-05-08** ✨ Inline chat image, redesigned Settings and keys, Dream memory aligned with visible history.
- **2026-05-07** 📜 Locale-aware slash palette in WebUI, LAN login, faithful HTTP streaming responses.
- **2026-05-06** 🧩 Tunable tool hint, steadier voice and plug-in startups, schedules and reminders that stick.
- **2026-05-05** 🛡️ Quiet deny for unknown Telegram chats, Dream cleanup, fuller automation summaries.
- **2026-05-04** 🔐 Safer DingTalk outbound media links, durable cron persistence, DeepSeek polish.
- **2026-05-03** ⚙️ Predictable shell allow-list behavior, isolated chats mid-reply, cleaner interactive retries.
- **2026-05-02** 🐈 LongCat support, smarter token sizing hints, clearer bundled upgrade guidance.
- **2026-05-01** ☁️ Native AWS Bedrock provider, tighter helper handoffs and scoped session files.
- **2026-04-30** 💬 Feishu threads that honor replies and topics, WhatsApp bridge refresh on source edits.
- **2026-04-29** 🚀 Released **v0.1.5.post3** — Smarter threads on Feishu, Discord, Slack, and Teams; **DeepSeek-V4**; Hugging Face & Olostep; choices, `/history`, and steadier long chats. Please see [release notes](https://github.com/HKUDS/blackcat/releases/tag/v0.1.5.post3) for details.
- **2026-04-28** 🌐 Olostep web search, Hugging Face provider, safer workspace-tool interruptions.
- **2026-04-27** 💬 `/history` command, smarter session replay caps, smoother Discord / Slack threads.
- **2026-04-26** 🧭 Natural cron reminders, thread-aware restarts, safer local provider and shell behavior.
- **2026-04-25** 🧩 `ask_user` choices, macOS LaunchAgent deployment, MSTeams stale-reference cleanup.
- **2026-04-24** 🎥 Video attachments for channels, DeepSeek thinking control, faster document startup.
- **2026-04-23** 🧵 Discord thread sessions, Telegram inline buttons, structured tool progress updates.
- **2026-04-22** 🔎 GitHub Copilot GPT-5 / o-series support, configurable web fetch, WebUI image uploads.
- **2026-04-21** 🚀 Released **v0.1.5.post2** — Windows & Python 3.14 support, Office document reading, SSE streaming for the OpenAI-compatible API, and stronger reliability across sessions, memory, and channels. Please see [release notes](https://github.com/HKUDS/blackcat/releases/tag/v0.1.5.post2) for details.
- **2026-04-20** 🎨 Kimi K2.6 support, Telegram long-message split, WebUI typography & dark-mode polish.
- **2026-04-19** 🌐 WebUI i18n locale switcher, atomic session writes with auto-repair.
- **2026-04-18** 🧪 Initial WebUI chat, smarter setup wizard menus, WebSocket multi-chat multiplexing.
- **2026-04-17** 🪟 Windows & Python 3.14 CI, Dream line-age memory, email self-loop guard.
- **2026-04-16** 📡 SSE streaming for OpenAI-compatible API, Discord channel allow-list.
- **2026-04-15** 🎛️ LM Studio & nullable API keys, MiniMax thinking endpoint, runtime SelfTool.
- **2026-04-14** 🚀 Released **v0.1.5.post1** — Dream skill discovery, mid-turn follow-up injection, WebSocket channel, and deeper channel integrations. Please see [release notes](https://github.com/HKUDS/blackcat/releases/tag/v0.1.5.post1) for details.
- **2026-04-13** 🛡️ Agent turn hardened — user messages persisted early, auto-compact skips active tasks.
- **2026-04-12** 🔒 Lark global domain support, Dream learns discovered skills, shell sandbox tightened.
- **2026-04-11** ⚡ Context compact shrinks sessions on the fly; Kagi web search; QQ & WeCom full media.
- **2026-04-10** 📓 Multiple MCP servers, Feishu streaming & done-emoji.
- **2026-04-09** 🔌 WebSocket channel, unified cross-channel session, `disabled_skills` config.
- **2026-04-08** 📤 API file uploads, OpenAI reasoning auto-routing with Responses fallback.
- **2026-04-07** 🧠 Anthropic adaptive thinking, MCP resources & prompts exposed as tools.
- **2026-04-06** 🛰️ Langfuse observability, unified Whisper transcription, email attachments.
- **2026-04-05** 🚀 Released **v0.1.5** — sturdier long-running tasks, Dream two-stage memory, production-ready sandboxing and programming Agent SDK. Please see [release notes](https://github.com/HKUDS/blackcat/releases/tag/v0.1.5) for details.
- **2026-04-04** 🚀 Jinja2 response templates, Dream memory hardened, smarter retry handling.
- **2026-04-03** 🧠 Xiaomi MiMo provider, chain-of-thought reasoning visible, Telegram UX polish.
- **2026-04-02** 🧱 Long-running tasks run more reliably — core runtime hardening.
- **2026-04-01** 🔑 GitHub Copilot auth restored; stricter workspace paths; OpenRouter Claude caching fix.
- **2026-03-31** 🛰️ WeChat multimodal alignment, Discord/Matrix polish, Python SDK facade, MCP and tool fixes.
- **2026-03-30** 🧩 OpenAI-compatible API tightened; composable agent lifecycle hooks.
- **2026-03-29** 💬 WeChat voice, typing, QR/media resilience; fixed-session OpenAI-compatible API.
- **2026-03-28** 📚 Provider docs refresh; skill template wording fix.
- **2026-03-27** 🚀 Released **v0.1.4.post6** — architecture decoupling, litellm removal, end-to-end streaming, WeChat channel, and a security fix. Please see [release notes](https://github.com/HKUDS/blackcat/releases/tag/v0.1.4.post6) for details.
- **2026-03-26** 🏗️ Agent runner extracted and lifecycle hooks unified; stream delta coalescing at boundaries.
- **2026-03-25** 🌏 StepFun provider, configurable timezone, Gemini thought signatures.
- **2026-03-24** 🔧 WeChat compatibility, Feishu CardKit streaming, test suite restructured.
- **2026-03-23** 🔧 Command routing refactored for plugins, WhatsApp/WeChat media, unified channel login CLI.
- **2026-03-22** ⚡ End-to-end streaming, WeChat channel, Anthropic cache optimization, `/status` command.
- **2026-03-21** 🔒 Replace `litellm` with native `openai` + `anthropic` SDKs. Please see [commit](https://github.com/HKUDS/blackcat/commit/3dfdab7).
- **2026-03-20** 🧙 Interactive setup wizard — pick your provider, model autocomplete, and you're good to go.
- **2026-03-19** 💬 Telegram gets more resilient under load; Feishu now renders code blocks properly.
- **2026-03-18** 📷 Telegram can now send media via URL. Cron schedules show human-readable details.
- **2026-03-17** ✨ Feishu formatting glow-up, Slack reacts when done, custom endpoints support extra headers, and image handling is more reliable.
- **2026-03-16** 🚀 Released **v0.1.4.post5** — a refinement-focused release with stronger reliability and channel support, and a more dependable day-to-day experience. Please see [release notes](https://github.com/HKUDS/blackcat/releases/tag/v0.1.4.post5) for details.
- **2026-03-15** 🧩 DingTalk rich media, smarter built-in skills, and cleaner model compatibility.
- **2026-03-14** 💬 Channel plugins, Feishu replies, and steadier MCP, QQ, and media handling.
- **2026-03-13** 🌐 Multi-provider web search, LangSmith, and broader reliability improvements.
- **2026-03-12** 🚀 VolcEngine support, Telegram reply context, `/restart`, and sturdier memory.
- **2026-03-11** 🔌 WeCom, Ollama, cleaner discovery, and safer tool behavior.
- **2026-03-10** 🧠 Token-based memory, shared retries, and cleaner gateway and Telegram behavior.
- **2026-03-09** 💬 Slack thread polish and better Feishu audio compatibility.
- **2026-03-08** 🚀 Released **v0.1.4.post4** — a reliability-packed release with safer defaults, better multi-instance support, sturdier MCP, and major channel and provider improvements. Please see [release notes](https://github.com/HKUDS/blackcat/releases/tag/v0.1.4.post4) for details.
- **2026-03-07** 🚀 Azure OpenAI provider, WhatsApp media, QQ group chats, and more Telegram/Feishu polish.
- **2026-03-06** 🪄 Lighter providers, smarter media handling, and sturdier memory and CLI compatibility.
- **2026-03-05** ⚡️ Telegram draft streaming, MCP SSE support, and broader channel reliability fixes.
- **2026-03-04** 🛠️ Dependency cleanup, safer file reads, and another round of test and Cron fixes.
- **2026-03-03** 🧠 Cleaner user-message merging, safer multimodal saves, and stronger Cron guards.
- **2026-03-02** 🛡️ Safer default access control, sturdier Cron reloads, and cleaner Matrix media handling.
- **2026-03-01** 🌐 Web proxy support, smarter Cron reminders, and Feishu rich-text parsing improvements.
- **2026-02-28** 🚀 Released **v0.1.4.post3** — cleaner context, hardened session history, and smarter agent. Please see [release notes](https://github.com/HKUDS/blackcat/releases/tag/v0.1.4.post3) for details.
- **2026-02-27** 🧠 Experimental thinking mode support, DingTalk media messages, Feishu and QQ channel fixes.
- **2026-02-26** 🛡️ Session poisoning fix, WhatsApp dedup, Windows path guard, Mistral compatibility.
- **2026-02-25** 🧹 New Matrix channel, cleaner session context, auto workspace template sync.
- **2026-02-24** 🚀 Released **v0.1.4.post2** — a reliability-focused release with a redesigned heartbeat, prompt cache optimization, and hardened provider & channel stability. See [release notes](https://github.com/HKUDS/blackcat/releases/tag/v0.1.4.post2) for details.
- **2026-02-23** 🔧 Virtual tool-call heartbeat, prompt cache optimization, Slack mrkdwn fixes.
- **2026-02-22** 🛡️ Slack thread isolation, Discord typing fix, agent reliability improvements.
- **2026-02-21** 🎉 Released **v0.1.4.post1** — new providers, media support across channels, and major stability improvements. See [release notes](https://github.com/HKUDS/blackcat/releases/tag/v0.1.4.post1) for details.
- **2026-02-20** 🐦 Feishu now receives multimodal files from users. More reliable memory under the hood.
- **2026-02-19** ✨ Slack now sends files, Discord splits long messages, and subagents work in CLI mode.
- **2026-02-18** ⚡️ blackcat now supports VolcEngine, MCP custom auth headers, and Anthropic prompt caching.
- **2026-02-17** 🎉 Released **v0.1.4** — MCP support, progress streaming, new providers, and multiple channel improvements. Please see [release notes](https://github.com/HKUDS/blackcat/releases/tag/v0.1.4) for details.
- **2026-02-16** 🦞 blackcat now integrates a [ClawHub](https://clawhub.ai) skill — search and install public agent skills.
- **2026-02-15** 🔑 blackcat now supports OpenAI Codex provider with OAuth login support.
- **2026-02-14** 🔌 blackcat now supports MCP! See [MCP section](./docs/configuration.md#mcp-model-context-protocol) for details.
- **2026-02-13** 🎉 Released **v0.1.3.post7** — includes security hardening and multiple improvements. **Please upgrade to the latest version to address security issues**. See [release notes](https://github.com/HKUDS/blackcat/releases/tag/v0.1.3.post7) for more details.
- **2026-02-12** 🧠 Redesigned memory system — Less code, more reliable. Join the [discussion](https://github.com/HKUDS/blackcat/discussions/566) about it!
- **2026-02-11** ✨ Enhanced CLI experience and added MiniMax support!
- **2026-02-10** 🎉 Released **v0.1.3.post6** with improvements! Check the updates [notes](https://github.com/HKUDS/blackcat/releases/tag/v0.1.3.post6) and our [roadmap](https://github.com/HKUDS/blackcat/discussions/431).
- **2026-02-09** 💬 Added Slack, Email, and QQ support — blackcat now supports multiple chat platforms!
- **2026-02-08** 🔧 Refactored Providers—adding a new LLM provider now takes just 2 simple steps! Check [here](./docs/configuration.md#providers).
- **2026-02-07** 🚀 Released **v0.1.3.post5** with Qwen support & several key improvements! Check [here](https://github.com/HKUDS/blackcat/releases/tag/v0.1.3.post5) for details.
- **2026-02-06** ✨ Added Moonshot/Kimi provider, Discord integration, and enhanced security hardening!
- **2026-02-05** ✨ Added Feishu channel, DeepSeek provider, and enhanced scheduled tasks support!
- **2026-02-04** 🚀 Released **v0.1.3.post4** with multi-provider & Docker support! Check [here](https://github.com/HKUDS/blackcat/releases/tag/v0.1.3.post4) for details.
- **2026-02-03** ⚡ Integrated vLLM for local LLM support and improved natural language task scheduling!
- **2026-02-02** 🎉 blackcat officially launched! Welcome to try 🐈 blackcat!

</details>


## 💡 Why blackcat

- **Persistent workflows**: goals, memory, tools, and chat context survive long-running work.
- **Chat-native reach**: WebUI, API, Telegram, Feishu, Slack, Discord, Teams, and email.
- **Model freedom**: OpenAI-compatible APIs, local LLMs, image generation, search, and fallbacks.
- **Small core**: readable internals with MCP, memory, deployment, and automation built in.
- **Own your stack**: inspect, customize, self-host, and extend without a giant platform.

## 📦 Install

> [!IMPORTANT]
> If you want the newest features and experiments, install from source. 
> 
> If you want the most stable day-to-day experience, install from PyPI or with `uv`.

Pick **one** install method:

Prerequisites: Python 3.11 or newer. Git is only needed for a source install; Node.js/Bun are only needed if you are developing the WebUI itself.

If terminals, API keys, or config files are new to you, use the guided zero-background walkthrough in [Start Without Technical Background](./docs/start-without-technical-background.md) instead of this compact README path.

**One-command setup**

macOS / Linux:

```bash
curl -fsSL https://raw.githubusercontent.com/HKUDS/blackcat/main/scripts/install.sh | sh
```

Windows PowerShell:

```powershell
irm https://raw.githubusercontent.com/HKUDS/blackcat/main/scripts/install.ps1 | iex
```

The default command installs or upgrades `blackcat-ai` from PyPI, then starts `blackcat onboard --wizard`. It avoids system-wide pip installs by using an active virtual environment, `uv`, `pipx`, or a managed venv under `~/.blackcat/venv`. If you finish the wizard and save the config, skip the manual initialize/configure steps below and go straight to **Test one message**.

To preview the plan without changing your environment, pass `--dry-run`; combine it with `--dev` when you want to preview the main-branch install.

```bash
curl -fsSL https://raw.githubusercontent.com/HKUDS/blackcat/main/scripts/install.sh | sh -s -- --dry-run
```

```powershell
& ([scriptblock]::Create((irm https://raw.githubusercontent.com/HKUDS/blackcat/main/scripts/install.ps1))) --dry-run
```

To install the current `main` branch instead, pass `--dev`:

```bash
curl -fsSL https://raw.githubusercontent.com/HKUDS/blackcat/main/scripts/install.sh | sh -s -- --dev
```

```powershell
& ([scriptblock]::Create((irm https://raw.githubusercontent.com/HKUDS/blackcat/main/scripts/install.ps1))) --dev
```

If you prefer to inspect the script first, open [`scripts/install.sh`](./scripts/install.sh) or [`scripts/install.ps1`](./scripts/install.ps1).

**Install with `uv`**

```bash
uv tool install blackcat-ai
```

**Install from PyPI with pip**

```bash
python -m pip install blackcat-ai
```

If pip reports `externally-managed-environment` on macOS or Linux, use the one-command installer, `uv tool install blackcat-ai`, `pipx install blackcat-ai`, or install inside a virtual environment.

**Install from source**

```bash
git clone https://github.com/HKUDS/blackcat.git
cd blackcat
python -m pip install -e .
```

Verify the install:

```bash
blackcat --version
```

## 🚀 Quick Start

**1. Initialize**

Skip this step if the one-command setup already started the wizard and you saved the config there.

```bash
blackcat onboard
```

Use `blackcat onboard --wizard` if you prefer an interactive setup.

**2. Configure** (`~/.blackcat/config.json`)

Skip this step if you already configured provider and model settings in the wizard.

`blackcat onboard` creates `~/.blackcat/config.json` and `~/.blackcat/workspace/`. Configure these **two parts** in the config file. Add or merge the following blocks into the existing file instead of replacing the whole file.

The example below uses [OpenRouter](https://openrouter.ai/keys) only so the JSON has concrete names. Provider examples are recipes, not rankings or endorsements. If you use another provider, replace the provider config key, API key, preset provider name, and model ID together.

*Set your API key*:

```json
{
  "providers": {
    "openrouter": {
      "apiKey": "sk-or-v1-xxx"
    }
  }
}
```

*Set a model preset and make it active*:

```json
{
  "modelPresets": {
    "primary": {
      "label": "Primary",
      "provider": "openrouter",
      "model": "anthropic/claude-opus-4.5",
      "maxTokens": 8192,
      "contextWindowTokens": 65536,
      "temperature": 0.1
    }
  },
  "agents": {
    "defaults": {
      "modelPreset": "primary"
    }
  }
}
```

Direct `agents.defaults.provider` and `agents.defaults.model` still work for existing configs, but named presets are the recommended path because they also power `/model` switching and `fallbackModels`.

For another provider, the same config shape still applies:

| Replace | Where |
|---|---|
| Provider config key | `providers.<provider>` |
| API key | `providers.<provider>.apiKey` |
| Preset provider name | `modelPresets.primary.provider` |
| Model ID | `modelPresets.primary.model` |
| Endpoint URL, only when needed | `providers.<provider>.apiBase` |

**3. Test one message**

```bash
blackcat status
blackcat agent -m "Hello!"
```

In `blackcat status`, it is normal for most providers to say `not set`. The active preset's provider should be configured, and `Config` plus `Workspace` should show check marks.

If that works, start an interactive chat:

```bash
blackcat agent
```

Need help with `PATH`, API keys, provider/model matching, or JSON errors? See the fuller [Install and Quick Start](./docs/quick-start.md) and [Troubleshooting](./docs/troubleshooting.md).

- Want a pasteable provider setup? See [Provider Cookbook](./docs/provider-cookbook.md)
- Want to understand provider/model matching? See [Providers and Models](./docs/providers.md)
- Want web search, MCP, security settings, or more config options? See [Configuration](./docs/configuration.md)
- Want to run locally? See [Ollama](./docs/providers.md#ollama), [vLLM or another local OpenAI-compatible server](./docs/providers.md#vllm-or-other-local-openai-compatible-server), and the full [provider reference](./docs/configuration.md#providers).
- Want to run blackcat in chat apps like Telegram, Discord, WeChat or Feishu? See [Chat Apps](./docs/chat-apps.md)
- Want Docker or Linux service deployment? See [Deployment](./docs/deployment.md)

## 🌐 WebUI

The WebUI ships **inside the published wheel** — no extra build step. Just enable the WebSocket channel and open it in your browser.

<p align="center">
  <img src="images/blackcat_webui.png" alt="blackcat webui preview" width="900">
</p>

**1. Enable the WebSocket channel in `~/.blackcat/config.json`**

Merge this block into your existing config:

```json
{ "channels": { "websocket": { "enabled": true } } }
```

**2. Start the gateway**

```bash
blackcat gateway
```

**3. Open the WebUI**

Visit [`http://127.0.0.1:8765`](http://127.0.0.1:8765) in your browser. To open it from another device on your LAN, see [WebUI docs → LAN access](./webui/README.md#access-from-another-device-lan).

The WebUI is served by the WebSocket channel on port `8765` by default. The gateway's `18790` port is for the health endpoint, not the browser UI.

> [!TIP]
> Working on the WebUI itself? Check out [`webui/README.md`](./webui/README.md) for the Vite dev server (HMR) workflow.

## 🏗️ Architecture

<p align="center">
  <img src="images/blackcat_arch.png" alt="blackcat architecture" width="800">
</p>

🐈 blackcat stays lightweight by centering everything around a small agent loop: messages come in from chat apps, the LLM decides when tools are needed, and memory or skills are pulled in only as context instead of becoming a heavy orchestration layer. That keeps the core path readable and easy to extend, while still letting you add channels, tools, memory, and deployment options without turning the system into a monolith.

## ✨ Features

<table align="center">
  <tr align="center">
    <th><p align="center">📈 24/7 Real-Time Market Analysis</p></th>
    <th><p align="center">🚀 Full-Stack Software Engineer</p></th>
    <th><p align="center">📅 Smart Daily Routine Manager</p></th>
    <th><p align="center">📚 Personal Knowledge Assistant</p></th>
  </tr>
  <tr>
    <td align="center"><p align="center"><img src="case/search.gif" width="180" height="400"></p></td>
    <td align="center"><p align="center"><img src="case/code.gif" width="180" height="400"></p></td>
    <td align="center"><p align="center"><img src="case/schedule.gif" width="180" height="400"></p></td>
    <td align="center"><p align="center"><img src="case/memory.gif" width="180" height="400"></p></td>
  </tr>
  <tr>
    <td align="center">Discovery • Insights • Trends</td>
    <td align="center">Develop • Deploy • Scale</td>
    <td align="center">Schedule • Automate • Organize</td>
    <td align="center">Learn • Memory • Reasoning</td>
  </tr>
</table>

## 📚 Docs

Browse the [repo docs](./docs/README.md) for the latest features and GitHub development version, or visit [blackcat.wiki](https://blackcat.wiki/docs/latest/getting-started/blackcat-overview) for the stable release documentation.

- Start with no technical background: [Start Without Technical Background](./docs/start-without-technical-background.md)
- Start from zero with developer basics: [Install and Quick Start](./docs/quick-start.md)
- Understand the runtime model: [Concepts](./docs/concepts.md)
- Read the source-level map: [Architecture](./docs/architecture.md)
- Choose a provider/model: [Providers and Models](./docs/providers.md)
- Copy provider setup recipes: [Provider Cookbook](./docs/provider-cookbook.md)
- Debug setup and runtime failures: [Troubleshooting](./docs/troubleshooting.md)
- Talk to your blackcat with familiar chat apps: [Chat Apps](./docs/chat-apps.md)
- Configure providers, web search, MCP, and runtime behavior: [Configuration](./docs/configuration.md)
- Integrate blackcat with local tools and automations: [OpenAI-Compatible API](./docs/openai-api.md) · [Python SDK](./docs/python-sdk.md)
- Run blackcat with Docker or as a Linux service: [Deployment](./docs/deployment.md)

## 🤝 Contribute & Roadmap

PRs welcome! The codebase is intentionally small and readable. 🤗

### Contribution Flow

See [CONTRIBUTING.md](./CONTRIBUTING.md) for setup, review, and contribution guidelines.

**Roadmap** — Pick an item and [open a PR](https://github.com/HKUDS/blackcat/pulls)!

- **Multi-modal** — See and hear (images, voice, video)
- **Long-term memory** — Never forget important context
- **Better reasoning** — Multi-step planning and reflection
- **More integrations** — Calendar and more
- **Self-improvement** — Learn from feedback and mistakes

## Contact

This project was started by [Xubin Ren](https://github.com/re-bin) as a personal open-source project and continues to be maintained in an individual capacity using personal resources, with contributions from the open-source community. Feel free to contact [xubinrencs@gmail.com](mailto:xubinrencs@gmail.com) for questions, ideas, or collaboration.

### Contributors

<a href="https://github.com/HKUDS/blackcat/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=HKUDS/blackcat&max=100&columns=12&updated=20260210" alt="Contributors" />
</a>


## ⭐ Star History

<div align="center">
  <a href="https://star-history.com/#HKUDS/blackcat&Date">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/svg?repos=HKUDS/blackcat&type=Date&theme=dark" />
      <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/svg?repos=HKUDS/blackcat&type=Date" />
      <img alt="Star History Chart" src="https://api.star-history.com/svg?repos=HKUDS/blackcat&type=Date" style="border-radius: 15px; box-shadow: 0 0 30px rgba(0, 217, 255, 0.3);" />
    </picture>
  </a>
</div>

<p align="center">
  <em> Thanks for visiting ✨ blackcat!</em><br><br>
  <img src="https://visitor-badge.laobi.icu/badge?page_id=HKUDS.blackcat&style=for-the-badge&color=00d4ff" alt="Views">
</p>
