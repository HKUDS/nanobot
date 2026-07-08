# How to Deploy a Long-Running AI Agent Gateway with nanobot

The nanobot gateway is the long-running process behind WebUI sessions, chat app
messages, automations, local triggers, and WebSocket delivery.

## What you will build

- a configured nanobot instance
- a gateway process that survives terminal exits
- a service or container deployment path

## When to use this

Deploy the gateway when nanobot must keep receiving messages or running
automations after a one-off CLI command ends.

## Install

```bash
python -m pip install nanobot-ai
nanobot onboard --wizard
nanobot agent -m "Hello!"
```

## Minimal working example

Start the gateway in the foreground:

```bash
nanobot gateway
```

For browser usage, the WebUI launcher can manage the gateway:

```bash
nanobot webui --background
```

For server usage, configure Docker, systemd, or macOS LaunchAgent from the
deployment reference.

## Production notes

- Keep config and workspace paths explicit in services.
- Persist `~/.nanobot/config.json`, the workspace, sessions, and memory files.
- Use one process per config/workspace pair.
- Expose only the ports required by the surfaces you use.

## Security notes

- Bind local-only surfaces to `127.0.0.1`.
- Add an API key before exposing `nanobot serve` beyond localhost.
- Restrict chat app access and workspace tools before putting the gateway on a
  shared server.

## Troubleshooting

- Use `nanobot status` with the same config/workspace as the service.
- Check service logs for provider, port, channel, and permission errors.
- If WebUI works locally but not remotely, verify host binding, token settings,
  and firewall rules.

## Related nanobot docs

- [Deploy nanobot gateway](./deploy-nanobot-gateway.md)
- [Deployment](../deployment.md)
- [Multiple Instances](../multiple-instances.md)
- [WebUI](../webui.md)
