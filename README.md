<picture>
  <source media="(prefers-color-scheme: dark)" srcset="./images/readme-cover-dark.png">
  <img alt="nanobot README cover" src="./images/readme-cover-light.png">
</picture>

<div align="center">
  <p>
    <a href="https://nanobot.wiki/docs/latest/getting-started/nanobot-overview">English</a> |
    <a href="https://nanobot.wiki/cn/docs/latest/getting-started/nanobot-overview">简体中文</a> |
    <a href="https://nanobot.wiki/zh-Hant/docs/latest/getting-started/nanobot-overview">繁體中文</a> |
    <a href="https://nanobot.wiki/es/docs/latest/getting-started/nanobot-overview">Español</a> |
    <a href="https://nanobot.wiki/fr/docs/latest/getting-started/nanobot-overview">Français</a> |
    <a href="https://nanobot.wiki/id/docs/latest/getting-started/nanobot-overview">Bahasa Indonesia</a> |
    <a href="https://nanobot.wiki/ja/docs/latest/getting-started/nanobot-overview">日本語</a> |
    <a href="https://nanobot.wiki/ko/docs/latest/getting-started/nanobot-overview">한국어</a> |
    <a href="https://nanobot.wiki/ru/docs/latest/getting-started/nanobot-overview">Русский</a> |
    <a href="https://nanobot.wiki/vi/docs/latest/getting-started/nanobot-overview">Tiếng Việt</a>
  </p>
  <p>
    <a href="https://pypi.org/project/nanobot-ai/"><img src="https://img.shields.io/pypi/v/nanobot-ai" alt="PyPI"></a>
    <a href="https://pepy.tech/project/nanobot-ai"><img src="https://static.pepy.tech/badge/nanobot-ai" alt="Downloads"></a>
    <img src="https://img.shields.io/badge/python-≥3.11-blue" alt="Python">
    <img src="https://img.shields.io/badge/license-MIT-green" alt="License">
    <a href="https://github.com/HKUDS/nanobot/graphs/commit-activity" target="_blank">
        <img alt="Commits last month" src="https://img.shields.io/github/commit-activity/m/HKUDS/nanobot?labelColor=%20%2332b583&color=%20%2312b76a"></a>
    <a href="https://github.com/HKUDS/nanobot/issues?q=is%3Aissue%20is%3Aclosed" target="_blank">
        <img alt="Issues closed" src="https://img.shields.io/github/issues-search?query=repo%3AHKUDS%2Fnanobot%20is%3Aissue%20is%3Aclosed&label=issues%20closed&labelColor=%20%237d89b0&color=%20%235d6b98"></a>
    <a href="https://twitter.com/intent/follow?screen_name=nanobot_project" target="_blank">
        <img src="https://img.shields.io/twitter/follow/nanobot_project?logo=X&color=%20%23f5f5f5" alt="follow on X(Twitter)"></a>
    <a href="https://nanobot.wiki/docs/latest/getting-started/nanobot-overview"><img src="https://img.shields.io/badge/Docs-nanobot.wiki-blue?style=flat&logo=readthedocs&logoColor=white" alt="Docs"></a>
    <a href="./COMMUNICATION.md"><img src="https://img.shields.io/badge/Feishu-Group-E9DBFC?style=flat&logo=feishu&logoColor=white" alt="Feishu"></a>
    <a href="./COMMUNICATION.md"><img src="https://img.shields.io/badge/WeChat-Group-C5EAB4?style=flat&logo=wechat&logoColor=white" alt="WeChat"></a>
    <a href="https://discord.gg/MnCvHqpUGB"><img src="https://img.shields.io/badge/Discord-Community-5865F2?style=flat&logo=discord&logoColor=white" alt="Discord"></a>
  </p>
</div>

🐈 **nanobot** is an open-source personal AI agent you can run on your own computer or server. Use it from a browser, terminal, or chat app; give it tools, memory, and scheduled work without giving up control of your data and runtime.

## Get a Reply in Your Browser

You need Python 3.11 or newer and access to an AI provider account, company endpoint, or local model.

**1. Install and run the setup wizard**

macOS / Linux:

```bash
curl -fsSL https://raw.githubusercontent.com/HKUDS/nanobot/main/scripts/install.sh | sh
```

Windows PowerShell:

```powershell
irm https://raw.githubusercontent.com/HKUDS/nanobot/main/scripts/install.ps1 | iex
```

The installer uses an isolated environment when needed and opens `nanobot onboard --wizard`. Choose **Quick Start**, then enter the provider, model, and credential details requested by the wizard.

**2. Open nanobot**

```bash
nanobot webui
```

This starts the local gateway and opens `http://127.0.0.1:8765`. Send `Hello!`. A normal reply means installation, model access, and the WebUI are working.

If terminals, Python, API keys, or configuration files are new to you, follow the [beginner walkthrough](./docs/start-without-technical-background.md). For installation alternatives and first-run checks, use the [full quick start](./docs/quick-start.md).

Repository docs describe current `main`, while the stable package can lag behind it. If a linked WebUI screen is not present in your installed version, use the manual path on that page or install the current source version.

## Choose Your Next Step

Once the first browser reply works, change one thing at a time:

| You want to... | Start here |
|---|---|
| Connect Telegram, Discord, Slack, Feishu, WeChat, Email, or another chat app | Open **Settings → Channels** in the WebUI, then use the [chat app guide](./docs/chat-apps.md) for platform prerequisites |
| Change providers, models, voice, image, or web search | Open **Settings** in the WebUI; use the [provider cookbook](./docs/provider-cookbook.md) when you need a copyable recipe |
| Add an App or MCP server | Open **Apps** in the WebUI, or follow the [MCP guide](./docs/guides/configure-mcp-tools.md) |
| Schedule reminders or background checks | Read [Automations](./docs/automations.md) |
| Run a local model | Follow the [Ollama](./docs/providers.md#ollama) or [local OpenAI-compatible](./docs/providers.md#vllm-or-other-local-openai-compatible-server) setup |
| Call nanobot from code | Use the [Python SDK](./docs/python-sdk.md) or [OpenAI-compatible API](./docs/openai-api.md) |
| Keep nanobot running on a server | Read [Deployment](./docs/deployment.md) |
| Fix a setup or runtime problem | Follow [Troubleshooting](./docs/troubleshooting.md) in order |

## What You Can Do

- Work in persistent browser or terminal chats with visible tool activity.
- Connect the same agent to chat platforms and approve new users through pairing.
- Read and edit files, run shell commands, search or fetch the web, and attach MCP tools.
- Keep session history and consolidate useful long-term memory with Dream.
- Run sustained goals, scheduled automations, heartbeat checks, and local triggers.
- Switch between hosted, OAuth, company, and local models with fallback chains.
- Generate images, transcribe voice, expose an API, or embed nanobot through Python.

The WebUI is included in the published package; no frontend build is needed.

<p align="center">
  <img src="images/nanobot_webui.png" alt="nanobot WebUI showing a chat and agent activity" width="900">
</p>

See the [WebUI guide](./docs/webui.md) for workspaces, access modes, Apps, Skills, Automations, settings, and LAN access.

## Other Installation Methods

The commands above install the stable PyPI release. You can also choose one of these methods:

**uv**

```bash
uv tool install nanobot-ai
nanobot onboard --wizard
```

**pip in a virtual environment**

```bash
python -m pip install nanobot-ai
nanobot onboard --wizard
```

**Current source**

`bun` or `npm` must be available so the source build can bundle the WebUI. From an activated virtual environment:

```bash
git clone https://github.com/HKUDS/nanobot.git
cd nanobot
python -m pip install .
nanobot onboard --wizard
```

On Windows, if `python -m pip install .` reports that it cannot launch `npm`, run `cd webui`, `npm.cmd install --package-lock=false`, `npm.cmd run build`, and `cd ..` in order, then retry the install.

Use a source install when you want current `main` behavior or plan to test unreleased features. Use PyPI, `uv`, or `pipx` for a stable day-to-day install; those packages already contain the WebUI and do not need Node.js or Bun. Contributors who need an editable checkout should follow [`CONTRIBUTING.md`](./CONTRIBUTING.md) and [`webui/README.md`](./webui/README.md).

Useful first checks:

```bash
nanobot --version
nanobot status
nanobot agent -m "Hello!"
```

If `nanobot` is not on `PATH`, use `python -m nanobot` in the same commands. See [Install and Quick Start](./docs/quick-start.md) for updates, source installs, and operating-system notes.

## Documentation

The [documentation index](./docs/README.md) is organized by user task:

- **Start:** [beginner walkthrough](./docs/start-without-technical-background.md) · [quick start](./docs/quick-start.md)
- **Use:** [WebUI](./docs/webui.md) · [chat apps](./docs/chat-apps.md) · [automations](./docs/automations.md) · [image generation](./docs/image-generation.md)
- **Configure:** [provider cookbook](./docs/provider-cookbook.md) · [providers and models](./docs/providers.md) · [configuration reference](./docs/configuration.md)
- **Integrate:** [Python SDK](./docs/python-sdk.md) · [OpenAI-compatible API](./docs/openai-api.md) · [WebSocket protocol](./docs/websocket.md)
- **Operate:** [deployment](./docs/deployment.md) · [multiple instances](./docs/multiple-instances.md) · [troubleshooting](./docs/troubleshooting.md)
- **Contribute:** [architecture](./docs/architecture.md) · [development](./docs/development.md) · [contribution guide](./CONTRIBUTING.md)

Repository docs track the current source tree. For the latest published release, visit [nanobot.wiki](https://nanobot.wiki/docs/latest/getting-started/nanobot-overview).

## Release and Project Links

The latest tagged release is [v0.2.2 — Durability Release](https://github.com/HKUDS/nanobot/releases/tag/v0.2.2). See [GitHub Releases](https://github.com/HKUDS/nanobot/releases) for release notes and the [release archive](./docs/release-archive.md) for development highlights.

## Open Source Partners

<p align="center">
  <a href="https://platform.kimi.com?aff=nanobot"><picture><source media="(prefers-color-scheme: dark)" srcset="https://kimi-file.moonshot.cn/prod-chat-kimi/kfs/4/1/2026-06-05/1d8h69mt3v89kkekg24gg"><img alt="Kimi Open Source Friends" height="44" src="https://kimi-file.moonshot.cn/prod-chat-kimi/kfs/4/1/2026-06-05/1d8h69fudcmosb3pipls0"></picture></a>
  <a href="https://platform.minimaxi.com/subscribe/token-plan?code=GILTJpMTqZ&source=link"><img alt="MiniMax" height="40" src="https://mintcdn.com/minimax-zh/1UjvBcdoC6r0UeyA/logo/light.svg?fit=max&auto=format&n=1UjvBcdoC6r0UeyA&q=85&s=672d724b639b2d88d0702fae329ea4f8"></a>
</p>

## Contributing and Community

Issues and pull requests are welcome. Start with [CONTRIBUTING.md](./CONTRIBUTING.md) for setup, testing, and review guidance.

- [GitHub Issues](https://github.com/HKUDS/nanobot/issues)
- [GitHub Discussions](https://github.com/HKUDS/nanobot/discussions)
- [Discord](https://discord.gg/MnCvHqpUGB)
- [Feishu and WeChat groups](./COMMUNICATION.md)

This project was started by [Xubin Ren](https://github.com/re-bin) as a personal open-source project and continues to be maintained with contributions from the community. For questions, ideas, or collaboration, contact [xubinrencs@gmail.com](mailto:xubinrencs@gmail.com).

### Contributors

<a href="https://github.com/HKUDS/nanobot/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=HKUDS/nanobot&max=100&columns=12&updated=20260210" alt="Contributors" />
</a>

<p align="center">
  <em>Thanks for visiting ✨ nanobot!</em><br><br>
  <img src="https://visitor-badge.laobi.icu/badge?page_id=HKUDS.nanobot&style=for-the-badge&color=00d4ff" alt="Views">
</p>
