![cover-v5-optimized](./images/GitHub_README.png)

<div align="center">
  <p>
    <a href="https://pypi.org/project/nanobot-ai/"><img src="https://img.shields.io/pypi/v/nanobot-ai" alt="PyPI"></a>
    <a href="https://pepy.tech/project/nanobot-ai"><img src="https://static.pepy.tech/badge/nanobot-ai" alt="Downloads"></a>
    <img src="https://img.shields.io/badge/python-≥3.11-blue" alt="Python">
    <img src="https://img.shields.io/badge/license-MIT-green" alt="License">
    <img src="https://img.shields.io/badge/platform-Windows-blue" alt="Windows">
    <a href="https://github.com/launchswitch/nanobot-for-windows/graphs/commit-activity" target="_blank">
        <img alt="Commits last month" src="https://img.shields.io/github/commit-activity/m/launchswitch/nanobot-for-windows?labelColor=%20%2332b583&color=%20%2312b76a"></a>
    <a href="https://github.com/launchswitch/nanobot-for-windows/issues?q=is%3Aissue%20is%3Aclosed" target="_blank">
        <img alt="Issues closed" src="https://img.shields.io/github/issues-search?query=repo%3Alaunchswitch%2Fnanobot-for-windows%20is%3Aissue%20is%3Aclosed&label=issues%20closed&labelColor=%20%237d89b0&color=%20%235d6b98"></a>
    <a href="https://nanobot.wiki/docs/latest/getting-started/nanobot-overview"><img src="https://img.shields.io/badge/Docs-nanobot.wiki-blue?style=flat&logo=readthedocs&logoColor=white" alt="Docs"></a>
    <a href="https://discord.gg/MnCvHqpUGB"><img src="https://img.shields.io/badge/Discord-Community-5865F2?style=flat&logo=discord&logoColor=white" alt="Discord"></a>
  </p>
</div>

> **Windows-focused fork of [HKUDS/nanobot](https://github.com/HKUDS/nanobot)** — an open-source, ultra-lightweight AI agent with chat channels, memory, MCP support, and practical deployment paths.

## What this fork adds

This fork tracks upstream closely and layers on Windows-native improvements:

- **Windows-first shell handling** — configurable shell (`cmd.exe`, PowerShell, WSL), `PATHEXT` passthrough so Windows subprocesses resolve `.ps1`, `.bat`, `.cmd` scripts correctly, and Job Object process groups for clean subprocess teardown
- **Device path hardening** — blocks `\\?\` and UNC device paths from sandbox escape
- **Console restore on exit** — terminal settings are restored even after crashes
- **Cross-platform path handling** — all internal paths work correctly on both Windows and Unix
- **Platform-aware prompts** — the agent adapts its instructions based on the host OS
- **winget manifest** — ready-to-submit three-file package manifest for the Windows Package Manager (see `manifests/h/HKUDS/nanobot/0.2.0/`)
- **Windows deployment docs** — NSSM service, Task Scheduler, firewall rules, long-path support, and corporate proxy setup

See [docs/deployment.md](./docs/deployment.md) for the full Windows deployment guide and [manifests/](./manifests/h/HKUDS/nanobot/0.2.0/) for the winget manifest.

## News

- **2026-05-18** Synced with upstream **v0.2.0** — WebUI bundled in wheel (no source checkout), model presets, `/goal` for long-term objectives, image generation (Gemini/MiniMax), streaming reasoning, NVIDIA NIM support, Ant Ling provider, pairing-based access control, and 292 upstream commits. Windows fork layers preserved: configurable shell, Job Objects, device path hardening, console restore, cross-platform paths, winget manifest, and Windows deployment docs.
- **2026-04-29** Synced with upstream **v0.1.5.post3** — DeepSeek-V4, Hugging Face & Olostep providers, thread sessions for Feishu/Discord/Slack/Teams, `ask_user` tool, `/history` command, per-channel progress controls, atomic history writes, and LLM request timeouts. Notable for Windows: upstream now includes a WinError 193 fix for MCP stdio launchers and Matrix user-id sanitization for Windows-safe filenames.
- **2026-04-21** Upstream **v0.1.5.post2** added Windows & Python 3.14 CI, Office document reading, SSE streaming, and stronger session/memory reliability.

For the full upstream changelog, see [upstream releases](https://github.com/HKUDS/nanobot/releases).

## Install

> [!IMPORTANT]
> This fork installs from source. The PyPI package (`nanobot-ai`) tracks the upstream [HKUDS/nanobot](https://github.com/HKUDS/nanobot) releases.

```bash
git clone https://github.com/launchswitch/nanobot-for-windows.git
cd nanobot-for-windows
pip install -e .
```

**Prerequisites:** Python >= 3.11. PowerShell 7 or Windows Terminal recommended for the best interactive experience. Config is stored at `%APPDATA%\nanobot\config.json` (not `~/.nanobot`).

## Quick Start

**1. Initialize**

```bash
nanobot onboard
```

**2. Configure** (`%APPDATA%\nanobot\config.json`)

Add your API key (e.g. [OpenRouter](https://openrouter.ai/keys), recommended for global users):

```json
{
  "providers": {
    "openrouter": {
      "apiKey": "sk-or-v1-xxx"
    }
  }
}
```

Optionally pin a provider and model:

```json
{
  "agents": {
    "defaults": {
      "provider": "openrouter",
      "model": "anthropic/claude-opus-4-6"
    }
  }
}
```

**3. Chat**

```bash
nanobot agent
```

> [!TIP]
> Using **Windows Terminal**? Merge [`windows-terminal-profile.json`](./windows-terminal-profile.json) into your `settings.json` `profiles.list` for a dedicated nanobot tab.

- Different LLM providers, web search, MCP, security settings: [Configuration](./docs/configuration.md)
- Chat apps (Telegram, Discord, Slack, etc.): [Chat Apps](./docs/chat-apps.md)
- Docker, Windows Service, or Linux deployment: [Deployment](./docs/deployment.md)

- Want different LLM providers, web search, MCP, security settings, or more config options? See [Configuration](./docs/configuration.md)
- Want to run nanobot in chat apps like Telegram, Discord, WeChat or Feishu? See [Chat Apps](./docs/chat-apps.md)
- Want Docker, Windows Service, or Linux service deployment? See [Deployment](./docs/deployment.md)

## 🌐 WebUI

The WebUI ships **inside the published wheel** — no extra build step. Just enable the WebSocket channel and open it in your browser.

<p align="center">
  <img src="images/nanobot_webui.png" alt="nanobot webui preview" width="900">
</p>

**1. Enable WebSocket in your config** (`%APPDATA%\nanobot\config.json`):

```json
{ "channels": { "websocket": { "enabled": true } } }
```

**2. Start the gateway**

```bash
nanobot gateway
```

**3. Open the WebUI**

Visit [`http://127.0.0.1:8765`](http://127.0.0.1:8765) in your browser. To open it from another device on your LAN, see [WebUI docs → LAN access](./webui/README.md#access-from-another-device-lan).

> [!TIP]
> Working on the WebUI itself? Check out [`webui/README.md`](./webui/README.md) for the Vite dev server (HMR) workflow.

## Architecture

<p align="center">
  <img src="images/nanobot_arch.png" alt="nanobot architecture" width="800">
</p>

nanobot stays lightweight by centering everything around a small agent loop: messages come in from chat apps, the LLM decides when tools are needed, and memory or skills are pulled in only as context instead of becoming a heavy orchestration layer. That keeps the core path readable and easy to extend, while still letting you add channels, tools, memory, and deployment options without turning the system into a monolith.

## Features

<table align="center">
  <tr align="center">
    <th><p align="center">Real-Time Market Analysis</p></th>
    <th><p align="center">Full-Stack Software Engineer</p></th>
    <th><p align="center">Daily Routine Manager</p></th>
    <th><p align="center">Personal Knowledge Assistant</p></th>
  </tr>
  <tr>
    <td align="center"><p align="center"><img src="case/search.gif" width="180" height="400"></p></td>
    <td align="center"><p align="center"><img src="case/code.gif" width="180" height="400"></p></td>
    <td align="center"><p align="center"><img src="case/schedule.gif" width="180" height="400"></p></td>
    <td align="center"><p align="center"><img src="case/memory.gif" width="180" height="400"></p></td>
  </tr>
  <tr>
    <td align="center">Discovery &middot; Insights &middot; Trends</td>
    <td align="center">Develop &middot; Deploy &middot; Scale</td>
    <td align="center">Schedule &middot; Automate &middot; Organize</td>
    <td align="center">Learn &middot; Memory &middot; Reasoning</td>
  </tr>
</table>

## Docs

Browse the [repo docs](./docs/README.md) for the latest features and GitHub development version, or visit [nanobot.wiki](https://nanobot.wiki/docs/latest/getting-started/nanobot-overview) for the stable release documentation.

- Chat apps: [Chat Apps](./docs/chat-apps.md)
- Providers, web search, MCP, runtime: [Configuration](./docs/configuration.md)
- OpenAI-Compatible API &middot; Python SDK: [API](./docs/openai-api.md) &middot; [SDK](./docs/python-sdk.md)
- Docker, Windows Service, Linux service: [Deployment](./docs/deployment.md)

## Upstream

This repo merges changes from [HKUDS/nanobot](https://github.com/HKUDS/nanobot) regularly. For the full changelog, see [upstream releases](https://github.com/HKUDS/nanobot/releases).

## Contribute

PRs welcome! See [CONTRIBUTING.md](./CONTRIBUTING.md) for details on branching and the development workflow.

### Contributors

<a href="https://github.com/HKUDS/nanobot/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=HKUDS/nanobot&max=100&columns=12&updated=20260210" alt="Contributors" />
</a>

<p align="center">
  <em>Thanks for visiting nanobot for Windows!</em>
</p>
