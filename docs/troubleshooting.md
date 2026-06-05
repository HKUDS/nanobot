# Troubleshooting

Use this page to isolate where a failure lives. Start with the smallest
surface that proves the most: local CLI first, then gateway, then WebUI or chat
apps.

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

If `nanobot agent -m "Hello!"` fails, fix that before debugging WebUI,
Telegram, Discord, Docker, systemd, or any chat app.

## Installation Problems

| Symptom | Check |
|---|---|
| `nanobot: command not found` | Use `python -m nanobot ...`, reinstall with `python -m pip install -U nanobot-ai`, or add the Python scripts directory to `PATH`. |
| `No module named nanobot` | You are running a different Python than the one used for installation. Run `python -m pip show nanobot-ai`. |
| Editable source install does not update | From the repo root, run `python -m pip install -e .` again and check `nanobot --version`. |
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

`nanobot status` reads the default config. Use explicit paths on commands that
support them when debugging multiple instances:

```bash
nanobot agent --config ./bot-a/config.json --workspace ./bot-a/workspace -m "Hello"
nanobot gateway --config ./bot-a/config.json --workspace ./bot-a/workspace
```

Common config mistakes:

| Symptom | Check |
|---|---|
| JSON parse error | Validate commas, braces, and quotes. Most docs examples are partial snippets to merge. |
| Unknown or missing provider | Use provider registry names such as `openrouter`, `anthropic`, `openai`, `ollama`, `vllm`, `lm_studio`. |
| snake_case vs camelCase confusion | Both are accepted, but docs use camelCase because nanobot writes config with aliases such as `apiKey`, `modelPresets`, `intervalS`. |
| Environment variable error | `${VAR_NAME}` references are resolved at startup. Set the variable before running nanobot. |
| Edited config but behavior did not change | Restart `nanobot gateway`; long-running processes read config at startup. |

To refresh missing defaults without overwriting existing settings, run:

```bash
nanobot onboard
```

When prompted about overwriting the config, choose the option that keeps current
values and merges missing defaults.

## Provider and Model Problems

First prove the provider in the CLI:

```bash
nanobot agent -m "Hello!"
```

Then compare your config against [`providers.md`](./providers.md).

| Symptom | Likely cause |
|---|---|
| 401, unauthorized, invalid API key | Key is missing, expired, pasted with whitespace, or under the wrong provider key. |
| Model not found | The model ID belongs to a different provider or gateway. |
| Provider cannot be inferred | Pin `agents.defaults.provider` instead of using `"auto"`. |
| Local model connection refused | Ollama, vLLM, LM Studio, or another local server is not running, or `apiBase` points to the wrong port. |
| Bedrock validation error | Check AWS region, credentials, model access, model ID, and whether the model supports Converse. |
| OAuth provider fails | Run `nanobot provider login openai-codex` or `nanobot provider login github-copilot`, then select the provider explicitly. |

## Gateway Problems

`nanobot gateway` is required for WebUI, chat apps, heartbeat, Dream, and
long-running channel connections.

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

If accessing from another device, bind the WebSocket channel to `0.0.0.0` and
set `token` or `tokenIssueSecret`. The WebSocket channel refuses public binds
without a token or token issue secret.

See [`../webui/README.md`](../webui/README.md) for LAN and development setup.

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
- sanitized config snippets, especially provider, model, channel, and tool
  settings;
- gateway logs from `nanobot gateway --verbose`;
- whether `nanobot agent -m "Hello!"` works.

Never paste real API keys, bot tokens, OAuth tokens, or private chat IDs into
public issues.
