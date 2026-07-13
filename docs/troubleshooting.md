# Troubleshooting

Use this page to isolate where a failure lives. Start with the smallest surface that proves the most: local CLI first, then gateway, then WebUI or chat apps.

## Fast Diagnosis Order

Run these in order:

```bash
nanobot --version
nanobot status
nanobot agent -m "Hello!"
```

Then, only if the CLI works:

```bash
nanobot gateway
```

This separates failures into layers:

| Layer | What it proves |
|---|---|
| `nanobot --version` | Install and shell command discovery |
| `nanobot status` | Config path, workspace path, active model, and provider summary |
| `nanobot agent -m "Hello!"` | Config loading, provider/model access, workspace writes, and agent loop |
| `nanobot gateway` | Channel startup, cron system jobs, heartbeat, WebUI/WebSocket, and health endpoint |

If `nanobot agent -m "Hello!"` fails, fix that before debugging WebUI, Telegram, Discord, Docker, systemd, or any chat app.

## How to Read `nanobot status`

`nanobot status` does not call a model. It only checks whether nanobot can find the selected config, selected workspace, active model or preset, and provider setup summary.

The output has this shape:

```text
nanobot Status

Config: /path/to/config.json ✓
Workspace: /path/to/workspace ✓
Model: provider/model-name (preset: primary)
Provider A: not set
Provider B: ✓
Local Provider: ✓ http://localhost:11434/v1
OAuth Provider: ✓ (OAuth)
```

Read it like this:

| Line | Good sign | What to do if it looks wrong |
|---|---|---|
| `Config` | It points to the config file you meant to use and shows `✓`. | Run `nanobot onboard`, or pass `--config` to `nanobot agent`, `gateway`, or `serve` when testing a non-default instance. |
| `Workspace` | It points to the workspace you meant to use and shows `✓`. | Run `nanobot onboard`, create the folder, fix permissions, or pass `--workspace` on commands that support it. |
| `Model` | It shows the active model or the preset name you expect. | Set `agents.defaults.modelPreset` to the intended preset, or check `/model` if you changed models during a chat session. |
| Provider rows | The provider used by the active preset shows `✓`, an OAuth marker, or a local URL. | Configure only the active provider first. It is normal for unused providers to say `not set`. |

If `nanobot status` looks right but `nanobot agent -m "Hello!"` fails, the install and config paths are probably fine. Continue with [Provider and Model Problems](#provider-and-model-problems).

## Installation Problems

Use the same Python command for install checks and module fallback. On macOS/Linux that may be `python3`; on Windows it may be `python` or `py`.

| Symptom | Check |
|---|---|
| `python: command not found` | Try `python3 --version` on macOS/Linux or `py --version` on Windows. Then replace `python` in docs commands with the command that worked. |
| `curl: command not found` | The macOS/Linux one-command installer could not download the script. Install curl, or use a manual isolated install such as `uv tool install nanobot-ai` or `pipx install nanobot-ai`. |
| `irm` is not recognized | PowerShell could not run the download helper. Use manual install: `uv tool install nanobot-ai`, `pipx install nanobot-ai`, or `py -m pip install nanobot-ai` inside an environment you control. |
| Could not download `raw.githubusercontent.com` | Your network, proxy, or firewall blocked the installer script download. Use manual install from PyPI, or configure your proxy and rerun the command. |
| `nanobot: command not found` | Use the module form, for example `python -m nanobot ...`, `python3 -m nanobot ...`, or `py -m nanobot ...`. Reinstall with the same Python command, or add that Python's scripts directory to `PATH`. |
| `No module named nanobot` | You are running a different Python than the one used for installation. Run `python -m pip show nanobot-ai`, `python3 -m pip show nanobot-ai`, or `py -m pip show nanobot-ai`, matching the command that installed nanobot. |
| `pip is not available` | When the installer uses a virtual environment, it tries `python -m ensurepip --upgrade`. If that fails, install pip for that Python, or use a Python installer/distribution that includes pip. |
| `externally-managed-environment` | Your system Python blocks global pip installs. Use the one-command installer, `uv tool install nanobot-ai`, `pipx install nanobot-ai`, or create a virtual environment; do not add `--break-system-packages` for nanobot. |
| Installer chose the wrong Python | Set `PYTHON` before running the installer, such as `curl -fsSL https://raw.githubusercontent.com/HKUDS/nanobot/main/scripts/install.sh | PYTHON=python3 sh` or `$env:PYTHON="py"` before the PowerShell command. |
| Editable source install does not update | From the repo root, run `python -m pip install -e .` again with the Python command used for development, then check `python -m nanobot --version` or `nanobot --version`. |
| WebUI build tools missing | They are only needed for WebUI development. Packaged installs already include the WebUI bundle. |

## Config Problems

Default config path:

```text
~/.nanobot/config.json
```

Default workspace path:

```text
~/.nanobot/workspace/
```

`nanobot status` reads the default config unless you pass explicit paths. Use the same `--config` and `--workspace` across status checks and runtime commands when debugging multiple instances:

```bash
nanobot status --config ./bot-a/config.json --workspace ./bot-a/workspace
nanobot agent --config ./bot-a/config.json --workspace ./bot-a/workspace -m "Hello"
nanobot gateway --config ./bot-a/config.json --workspace ./bot-a/workspace
```

Common config mistakes:

| Symptom | Check |
|---|---|
| JSON parse error | Validate commas, braces, and quotes. Most docs examples are partial snippets to merge. |
| Unknown or missing provider | Use provider registry names such as `openrouter`, `anthropic`, `openai`, `ollama`, `vllm`, `lm_studio`, or define a custom OpenAI-compatible provider key under `providers` and reference that exact key from the active preset. |
| snake_case vs camelCase confusion | Both are accepted, but docs use camelCase because nanobot writes config with aliases such as `apiKey`, `modelPresets`, `intervalS`. |
| Environment variable error | `${VAR_NAME}` references are resolved at startup. Set the variable before running nanobot. |
| Edited config but behavior did not change | Restart `nanobot gateway`; long-running processes read config at startup. |

To refresh missing defaults without overwriting existing settings, run:

```bash
nanobot onboard --refresh
```

For an interactive choice between resetting and refreshing, run `nanobot onboard` and choose the option that keeps current values and merges missing defaults.

## Provider and Model Problems

First prove the provider in the CLI:

```bash
nanobot agent -m "Hello!"
```

Then compare your config against [`providers.md`](./providers.md).

If you need a known-good snippet instead of diagnosis, use [`provider-cookbook.md`](./provider-cookbook.md).

| Symptom | Likely cause |
|---|---|
| 401, unauthorized, invalid API key | Key is missing, expired, pasted with whitespace, or under the wrong provider key. |
| Model not found | The model ID belongs to a different provider or gateway. |
| Provider cannot be inferred | Pin `modelPresets.<name>.provider` in the active preset instead of using `"auto"`. For legacy direct configs, pin `agents.defaults.provider`. |
| Local model connection refused | Ollama, vLLM, LM Studio, or another local server is not running, or `apiBase` points to the wrong port. |
| Bedrock validation error | Check AWS region, credentials, model access, model ID, and whether the model supports Converse. |
| OAuth provider fails | Run `nanobot provider login openai-codex` or `nanobot provider login github-copilot`, then select the provider explicitly. |

## Langfuse Problems

Langfuse tracing is optional and controlled by environment variables.

| Symptom | Check |
|---|---|
| `LANGFUSE_SECRET_KEY is set but langfuse is not installed` | Install `langfuse` in the same Python environment that runs nanobot, then restart the process. |
| No traces appear | Set `LANGFUSE_SECRET_KEY`, `LANGFUSE_PUBLIC_KEY`, and `LANGFUSE_BASE_URL` before starting nanobot. |
| Wrong Langfuse project or region | Check that the key pair and `LANGFUSE_BASE_URL` come from the same Langfuse project/region. |
| Only some providers trace | Langfuse tracing applies to OpenAI-compatible provider calls; native providers may not use that client path. |

See [`configuration.md#langfuse-observability`](./configuration.md#langfuse-observability) for setup commands.

## Gateway Problems

`nanobot gateway` is required for WebUI, chat apps, heartbeat, Dream, and long-running channel connections.

Default ports:

| Surface | Default |
|---|---|
| Gateway health endpoint | `http://127.0.0.1:18790/health` |
| WebUI/WebSocket channel | `http://127.0.0.1:8765` |
| OpenAI-compatible API (`nanobot serve`) | `http://127.0.0.1:8900` |

Common gateway checks:

```bash
nanobot gateway --verbose
```

| Symptom | Check |
|---|---|
| Port already in use | Change `gateway.port`, `channels.websocket.port`, or the `--port` CLI flag for the relevant command. |
| WebUI opened on `18790` but shows nothing useful | Open `8765`; `18790` is the health endpoint. |
| Config changes ignored | Restart the gateway. |
| Heartbeat never runs | Keep the gateway running, add tasks under `<workspace>/HEARTBEAT.md` -> `## Active Tasks`, and make sure `gateway.heartbeat.enabled` is true. |
| Cron jobs disappeared after switching workspaces | Cron jobs are workspace-scoped at `<workspace>/cron/jobs.json`; check you are using the intended workspace. |

## WebUI Problems

The packaged WebUI is served by the WebSocket channel.

Minimal config:

```json
{
  "channels": {
    "websocket": {
      "enabled": true
    }
  }
}
```

Then run:

```bash
nanobot gateway
```

Open:

```text
http://127.0.0.1:8765
```

If accessing from another device, bind the WebSocket channel to `0.0.0.0` and set `token` or `tokenIssueSecret`. The WebSocket channel refuses public binds without a token or token issue secret.

See [`webui.md#lan-access`](./webui.md#lan-access) for LAN setup and [`../webui/README.md`](../webui/README.md) for frontend development.

## Chat App Problems

Before debugging a chat app:

```bash
nanobot agent -m "Hello!"
nanobot channels status
nanobot gateway
```

Then check:

| Symptom | Check |
|---|---|
| Bot never replies | Gateway is not running, the channel is not enabled, or the bot/app token is wrong. |
| Unknown sender ignored | Configure `allowFrom`, pairing, or the channel-specific allow list. |
| Telegram fails | Confirm the BotFather token and `allowFrom` user ID. |
| Discord replies missing | Enable Message Content intent and invite the bot with the required permissions. |
| WhatsApp or WeChat login expired | Re-run `nanobot channels login whatsapp` or `nanobot channels login weixin`. |
| Chat app works but WebUI does not | The provider and gateway are likely fine; debug the WebSocket channel separately. |

See [`chat-apps.md`](./chat-apps.md) for channel-specific setup.

## Tool and Workspace Problems

| Symptom | Check |
|---|---|
| File access denied | Check `tools.restrictToWorkspace` and whether the target path is inside the active workspace. |
| Shell commands fail in Docker | Sandbox settings may need Linux capabilities; see [`deployment.md`](./deployment.md). |
| Web fetch blocked | SSRF protection blocks unsafe targets; use `tools.ssrfWhitelist` only for trusted private networks. |
| MCP tools missing | Check `tools.mcpServers`, server startup command, environment variables, and tool allow list. |
| Generated artifacts are missing | Check the active workspace and channel media directory. |

## Memory and Session Problems

| Symptom | Check |
|---|---|
| Conversation context seems wrong | Confirm the active workspace and session. WebUI chats and chat app threads may use different sessions. |
| Memory does not update immediately | Dream consolidation is periodic; recent turns still live in session history. |
| Old sessions appear after moving config | Session files are stored under `<workspace>/sessions/`; verify the workspace path. |
| You want one shared session across devices | Set `agents.defaults.unifiedSession` intentionally; otherwise keep separate sessions. |

## Collect Useful Evidence

When opening an issue or asking for help, include:

- install method and `nanobot --version`;
- operating system and Python version;
- the command you ran;
- relevant `nanobot status` output;
- sanitized config snippets, especially provider, model, channel, and tool settings;
- gateway logs from `nanobot gateway --verbose`;
- whether `nanobot agent -m "Hello!"` works.

Never paste real API keys, bot tokens, OAuth tokens, or private chat IDs into public issues.

If you find a docs mistake, outdated command, or confusing step, please open an issue: <https://github.com/HKUDS/nanobot/issues>.
