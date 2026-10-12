# How to Run a Self-Hosted AI Agent with nanobot

This guide sets up nanobot as a self-hosted AI agent runtime on your own machine or server. The result is a gateway process that can serve the WebUI, chat apps, automations, and API integrations.

## What you will build

- a nanobot config and workspace under your control
- a model provider connected through `config.json`
- a long-running `nanobot gateway`
- optional browser, chat app, and API access

## When to use this

Use this path when you want local or server-side ownership of the agent process, workspace files, memory files, and provider keys. It is also the right path when the agent must keep running after one terminal command finishes.

## Choose your starting point

**Already chatting in the WebUI:** you already have a self-hosted agent and a running gateway. Open **Channels** to connect a chat platform; use the same running gateway. If you want it to survive closing the launcher, follow [long-running gateway setup](./deploy-nanobot-gateway.md).

**New desktop installation:** follow the [quick start](../quick-start.md), configure a model in **Settings → Models**, and send `Hello!`. A normal browser reply confirms the setup; no additional CLI test or second gateway is required.

**New headless server:** follow the [Docker setup](../deployment.md#docker-compose), or install on the host using the [quick start's terminal setup](../quick-start.md). Verify the selected provider before installing a persistent service.

Self-hosting keeps the agent runtime and its state on your machine. A hosted model provider still receives prompts and any file content included in them. For local model inference, use the [Ollama setup](../provider-cookbook.md#recipe-ollama-local-model); local inference alone does not disable network-capable tools.

## Confirm the result

Send a message through the interface you intend to use. Check that it replies, then confirm the chosen gateway or service stays running after you close the setup terminal. Browser, chat channels, and automations use the gateway; the optional OpenAI-compatible API has its own [service setup](./openai-compatible-agent-api.md).

## Production notes

- Use Docker, systemd, or a macOS LaunchAgent when the process should survive terminal exits.
- Give every deployed instance a distinct config path, workspace path, and port set.
- Keep secrets in environment variables and start the service from the same environment.
- Use health checks against the gateway or API process, not chat app delivery as the only signal.

## Security notes

- Bind local-only services to `127.0.0.1` unless you intentionally expose them.
- Set an API key before binding the OpenAI-compatible API to a public interface.
- Prefer pairing for DM-capable chat apps, and keep any static `allowFrom` allowlists strict.
- Enable `tools.restrictToWorkspace`; on Linux, use the bubblewrap sandbox for shell execution.

## Troubleshooting

- Run `nanobot status` with the same `--config` and `--workspace` flags used by the service.
- Run `nanobot gateway --verbose` while debugging channel startup.
- Check port conflicts if the WebUI, WebSocket channel, or API endpoint fails to bind.

## Related nanobot docs

- [Deployment](../deployment.md)
- [Multiple Instances](../multiple-instances.md)
- [Configuration](../configuration.md)
- [Chat Apps](../chat-apps.md)
- [OpenAI-Compatible API](../openai-api.md)
