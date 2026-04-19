# CLI Reference

| Command | Description |
|---------|-------------|
| `nanobot onboard` | Initialize config & workspace at `~/.nanobot/` |
| `nanobot onboard --wizard` | Launch the interactive onboarding wizard |
| `nanobot onboard -c <config> -w <workspace>` | Initialize or refresh a specific instance config and workspace |
| `nanobot agent -m "..."` | Chat with the agent |
| `nanobot agent -w <workspace>` | Chat against a specific workspace |
| `nanobot agent -w <workspace> -c <config>` | Chat against a specific workspace/config |
| `nanobot agent` | Interactive chat mode |
| `nanobot agent --no-markdown` | Show plain-text replies |
| `nanobot agent --logs` | Show runtime logs during chat |
| `nanobot serve` | Start the OpenAI-compatible API |
| `nanobot gateway` | Start the gateway |
| `nanobot status` | Show status |
| `nanobot provider login openai-codex` | OAuth login for providers |
| `nanobot channels login <channel>` | Authenticate a channel interactively |
| `nanobot channels status` | Show channel status |

Interactive mode exits: `exit`, `quit`, `/exit`, `/quit`, `:q`, or `Ctrl+D`.
