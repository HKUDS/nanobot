# CLI Reference

| Command | Description |
|---------|-------------|
| `blackcat onboard` | Initialize config & workspace at `~/.blackcat/` |
| `blackcat onboard --wizard` | Launch the interactive onboarding wizard |
| `blackcat onboard -c <config> -w <workspace>` | Initialize or refresh a specific instance config and workspace |
| `blackcat agent -m "..."` | Chat with the agent |
| `blackcat agent -w <workspace>` | Chat against a specific workspace |
| `blackcat agent -w <workspace> -c <config>` | Chat against a specific workspace/config |
| `blackcat agent` | Interactive chat mode |
| `blackcat agent --no-markdown` | Show plain-text replies |
| `blackcat agent --logs` | Show runtime logs during chat |
| `blackcat serve` | Start the OpenAI-compatible API |
| `blackcat gateway` | Start the gateway |
| `blackcat status` | Show status |
| `blackcat provider login openai-codex` | OAuth login for providers |
| `blackcat channels login <channel>` | Authenticate a channel interactively |
| `blackcat channels status` | Show channel status |

Interactive mode exits: `exit`, `quit`, `/exit`, `/quit`, `:q`, or `Ctrl+D`.
