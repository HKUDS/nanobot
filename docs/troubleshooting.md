# Troubleshooting

Start at the top and follow the first step that matches your problem. This isolates installation or model errors before you debug the browser or a chat app.

## Fast Diagnosis Order

1. **`nanobot` is not found or will not start:** Run `nanobot --version` and see [Installation Problems](#installation-problems).
2. **nanobot starts, but setup looks incomplete:** Run `nanobot status`. It checks your config, workspace, and active provider locally without calling a model.
3. **`nanobot status` looks healthy, but replies fail:** Run `nanobot agent -m "Hello!"`. If that fails, fix [Provider and Model Problems](#provider-and-model-problems) before testing the WebUI or chat apps.
4. **CLI replies work, but the browser or chat app does not:** Start `nanobot gateway` and check [Gateway Problems](#gateway-problems), [WebUI Problems](#webui-problems), or [Chat App Problems](#chat-app-problems).

## How to Read `nanobot status`

```text
nanobot Status

Config: /path/to/config.json ✓
Workspace: /path/to/workspace ✓
Model: provider/model-name (preset: primary)
Agent: ✓ provider/model configuration is ready
Provider A: not set
Provider B: ✓
```

| Line | What you want | If it looks wrong |
|---|---|---|
| `Config` | Points to your expected config file with `✓` | Run `nanobot onboard`, or pass `--config` when using multiple instances |
| `Workspace` | Points to your expected workspace with `✓` | Run `nanobot onboard`, check folder permissions, or pass `--workspace` |
| `Model` | Shows your expected model or preset | Update it in **Settings → Models** or check `/model` in chat |
| `Agent` | Says `provider/model configuration is ready` | Follow the printed setup instructions, then re-run `nanobot status` |
| Providers | Your active provider shows `✓`, OAuth, or a local URL | Unused providers showing `not set` is normal |

## Installation Problems

| Symptom | Fix |
|---|---|
| `python: command not found` | Try `python3 --version` (macOS/Linux) or `py --version` (Windows), and use that command consistently |
| `curl` or `irm` not found, or GitHub blocked | Install directly from PyPI with `uv tool install nanobot-ai`, `pipx install nanobot-ai`, or `pip` inside a virtual environment |
| `nanobot: command not found` | Reuse the full command printed at the end of the official installer output; for `uv`/`pipx`/`pip`, run from that same environment |
| `No module named nanobot` | You are using a different Python than the one where nanobot was installed—check with `python -m pip show nanobot-ai` |
| `externally-managed-environment` | Use the official installer, `uv tool install nanobot-ai`, `pipx install nanobot-ai`, or a virtual environment (do not force a system-wide install) |
| Installer picked the wrong Python | Set `PYTHON` first: `PYTHON=python3` on macOS/Linux or `$env:PYTHON="py"` in PowerShell |
| WebUI build tools missing | Packaged installs already include the WebUI; build tools are only needed for frontend development |

## Config Problems

Default locations: `~/.nanobot/config.json` and `~/.nanobot/workspace/`. If you run multiple instances, pass the same `--home` (or `--config` and `--workspace`) to every command.

| Symptom | Fix |
|---|---|
| JSON parse error | Check commas, quotes, and braces—most doc examples are snippets to merge into `config.json` |
| Unknown or missing provider | Use a built-in provider name (`openrouter`, `anthropic`, `openai`, `ollama`, `vllm`, `lm_studio`, etc.) or match the exact custom provider key you defined |
| Environment variable error | `${VAR_NAME}` values are resolved at startup—set the variable before launching nanobot |
| Config changes had no effect | Restart `nanobot gateway` (long-running processes read config at startup) |
| Missing new default fields | Run `nanobot onboard --refresh` to add missing defaults without overwriting existing settings |

## Provider and Model Problems

Test in the terminal first:

```bash
nanobot agent -m "Hello!"
```

Compare your setup against [Providers and Models](./providers.md) or grab a working recipe from the [Provider Cookbook](./provider-cookbook.md).

| Symptom | Likely cause and fix |
|---|---|
| `401`, unauthorized, or invalid API key | Key is missing, expired, has extra whitespace, or belongs to a different provider |
| Model not found | Model ID is misspelled or unavailable on the selected provider |
| Provider cannot be inferred | Pin the provider explicitly inside your model preset instead of leaving it on `"auto"` |
| Local model connection refused | Start Ollama, vLLM, or LM Studio first and verify `apiBase` points to the right port |
| Bedrock validation error | Verify AWS region, credentials, model access, and that the model supports Converse |
| OAuth login fails | Run `nanobot provider login openai-codex`, `xai-grok`, or `github-copilot` (usually with `--set-main`) |
| OAuth login on a remote/headless machine | Sign in in your local browser; when the `localhost` redirect fails to load, copy the full URL from your browser's address bar and paste it into the WebUI dialog or CLI prompt |
| OAuth login in Docker | Start the container interactively with `docker run -it` |
| Codex or xAI needs a proxy | Set **Settings → Advanced → Shared proxy** (`network.proxy`) and enable **Use proxy** on that provider before signing in |
| Codex rejects an `openai/...` model | Use provider `openai_codex` with a Codex model (e.g. `openai-codex/gpt-5.6-sol`), not a direct API `openai/...` model |
| xAI returns `403` / access denied | Confirm your account has an active X Premium / Grok subscription, then sign in again with `nanobot provider login xai-grok` |
| Codex TLS / certificate error | Check the host's system clock and corporate proxy certificate chain; if your organization uses a private CA, set `SSL_CERT_FILE` (or `SSL_CERT_DIR`) in the gateway environment and restart |

## Gateway Problems

`nanobot gateway` powers the WebUI, chat apps, automations, heartbeat, and Dream. Run `nanobot gateway --verbose` to inspect live logs.

Default ports: **WebUI** `http://127.0.0.1:8765` · **Gateway health** `http://127.0.0.1:18790/health`.

| Symptom | Fix |
|---|---|
| Port already in use | Change `gateway.port`, `channels.websocket.port`, or pass `--port` |
| Port `18790` shows no WebUI | Open port `8765`—`18790` is only the health endpoint |
| Config changes ignored | Restart the gateway (`nanobot gateway restart`) |
| Startup pauses at `Installing optional feature` | An enabled chat channel is installing its missing Python dependencies; if PyPI is slow, set `PIP_INDEX_URL` to a trusted mirror |
| Heartbeat never runs | Keep the gateway running, add tasks under `## Active Tasks` in `<workspace>/HEARTBEAT.md`, and verify `gateway.heartbeat.enabled` is `true` |
| Scheduled jobs missing after switching workspaces | Automations are stored per workspace—confirm you are running the intended workspace |

## WebUI Problems

Run `nanobot webui` to start the gateway and open your browser.

| Symptom | Fix |
|---|---|
| Browser does not sign in | Copy the **complete login link** printed by `nanobot webui` (including everything after `#`)—the bare `http://127.0.0.1:8765` URL will not sign a new browser in |
| Cannot open from another device on LAN | Bind WebSocket `host` to `"0.0.0.0"` and set `tokenIssueSecret` (or `token`); see [LAN Access](./webui.md#lan-access) |
| Temporary chat disappeared after reload | Expected—temporary chats are not saved and end on reload or disconnect; use a regular topic for work you want to keep |
| Settings stay disabled after a restart | Reload the affected browser tab |
| `skills.sh` says `npx` is required | Install Node.js (which includes `npx`) on the gateway machine, or use SkillHub skills instead |
| Remote browser says installs are disabled | Install optional packages or skills from a local WebUI, or explicitly enable `tools.webuiAllowRemotePackageInstall` on trusted private deployments |

## Chat App Problems

First confirm the CLI works and check channel status:

```bash
nanobot agent -m "Hello!"
nanobot channels status
nanobot gateway
```

| Symptom | Fix |
|---|---|
| Bot never replies | Confirm the gateway is running, the channel is enabled, and the bot token/credentials are valid |
| Unknown sender ignored | Approve their pairing code (`/pairing approve <code>`) or add them to `allowFrom` |
| Telegram saves token but live check fails | Confirm the gateway can reach `api.telegram.org`, or configure a shared proxy and enable **Use proxy** in Telegram settings |
| Discord replies missing | Enable **Message Content Intent** in the Discord Developer Portal and verify bot permissions |
| WhatsApp or WeChat login expired | Re-run `nanobot channels login whatsapp` or `nanobot channels login weixin` |

See [Chat Apps](./chat-apps.md) for platform-specific setup.

## Tools, Workspace, and Memory Problems

| Symptom | Fix |
|---|---|
| File access denied | Check whether the topic is in **Restricted** mode and the file is inside the active workspace |
| Shell commands fail in Docker | Sandbox mode may need extra container capabilities; see [Deployment](./deployment.md) |
| Web fetch blocked | Built-in SSRF protection blocks private/internal URLs; add trusted private hosts to `tools.ssrfWhitelist` only if intended |
| MCP tools missing | Check **Apps → MCP** (or `tools.mcpServers`), startup commands, and required environment variables |
| Memory does not update right away | Dream runs periodically (or when you run `/dream`); recent turns stay in session history until compacted |
| Startup reports session storage overlaps the workspace | Keep `config.json` and `sessions/` outside the workspace folder (e.g. `bot/config.json`, `bot/sessions/`, `bot/workspace/`), stop nanobot, back up both directories, and move config + sessions out of the workspace |
| Sessions disappeared after moving config or workspace | Keep `sessions/` alongside your config directory and keep `.nanobot/workspace-id` inside your workspace when moving or backing up |

## Collect Useful Evidence

When opening an issue or asking for help, include:

- Your OS, Python version, install method, and `nanobot --version`.
- The exact command you ran and the exact error message.
- `nanobot status` output and whether `nanobot agent -m "Hello!"` works.
- Relevant `nanobot gateway --verbose` logs and sanitized config snippets.

> [!CAUTION]
> Always remove real API keys, bot tokens, OAuth tokens, passwords, and private chat IDs before posting logs or configs.

Found a doc error or confusing step? Please [open an issue](https://github.com/HKUDS/nanobot/issues).
