# How to Run a Self-Hosted AI Agent with nanobot

This guide sets up nanobot as a self-hosted AI agent runtime on your own
machine or server. The result is a gateway process that can serve the WebUI,
chat apps, automations, and API integrations.

## What you will build

- a nanobot config and workspace under your control
- a model provider connected through `config.json`
- a long-running `nanobot gateway`
- optional browser, chat app, and API access

## When to use this

Use this path when you want local or server-side ownership of the agent process,
workspace files, memory files, and provider keys. It is also the right path when
the agent must keep running after one terminal command finishes.

## Install

```bash
python -m pip install nanobot-ai
nanobot onboard --wizard
nanobot agent -m "Hello!"
```

Complete the CLI check before deploying the gateway. A deployment problem is
much easier to debug after the provider and model are known to work.

## Minimal working example

For chat apps, automations, and WebSocket delivery, start the gateway:

```bash
nanobot gateway
```

For the browser surface, use the WebUI launcher instead. It can start and manage
the local gateway for you:

```bash
nanobot webui
```

Or connect a channel in `~/.nanobot/config.json`, then keep the same gateway
process running for messages.

## Production notes

- Use Docker, systemd, or a macOS LaunchAgent when the process should survive
  terminal exits.
- Give every deployed instance a distinct config path, workspace path, and port
  set.
- Keep secrets in environment variables and start the service from the same
  environment.
- Use health checks against the gateway or API process, not chat app delivery as
  the only signal.

## Security notes

- Bind local-only services to `127.0.0.1` unless you intentionally expose them.
- Set an API key before binding the OpenAI-compatible API to a public interface.
- Keep `allowFrom` or pairing rules strict on every chat app.
- Enable `tools.restrictToWorkspace`; on Linux, use the bubblewrap sandbox for
  shell execution.

## Troubleshooting

- Run `nanobot status` with the same `--config` and `--workspace` flags used by
  the service.
- Run `nanobot gateway --verbose` while debugging channel startup.
- Check port conflicts if the WebUI, WebSocket channel, or API endpoint fails to
  bind.

## Related nanobot docs

- [Deployment](../deployment.md)
- [Multiple Instances](../multiple-instances.md)
- [Configuration](../configuration.md)
- [Chat Apps](../chat-apps.md)
- [OpenAI-Compatible API](../openai-api.md)
