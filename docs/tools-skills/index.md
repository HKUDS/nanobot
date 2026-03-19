# Tools & Skills Overview

Nanobot’s capabilities expand across two layers: **Tools** provide built-in execution primitives, while **Skills** package reusable knowledge and workflows. Together they create a flexible assistant framework.

---

## Tools

Tools are the core operations the agent can invoke—run shell commands, read/write files, search the web, schedule tasks, and more. They are provided by nanobot and controlled via configuration.

| Tool | Description |
|------|-------------|
| `exec` | Run shell commands and scripts |
| `read_file` | Read file contents (supports pagination) |
| `write_file` | Write files (creates directories automatically) |
| `edit_file` | Replace specific text fragments in files |
| `list_dir` | List directory trees |
| `web_search` | Search the web (multiple providers) |
| `web_fetch` | Fetch and parse web pages |
| `cron` | Schedule reminders and periodic jobs |
| `spawn` | Launch sub-agents for complex background work |
| `message` | Send messages to users (attachments supported) |

See the [Tools guide](tools.md) for full details.

---

## Skills

Skills are Markdown-based knowledge/workflow modules that teach the agent how to perform a task. When a skill loads, it enriches the agent context with instructions, example commands, scripts, and references.

Skills follow the [OpenClaw](https://github.com/openclaw/openclaw) spec so they remain compatible with the OpenClaw skill ecosystem.

| Skill | Description |
|-------|-------------|
| `github` | Interact with GitHub via the `gh` CLI |
| `weather` | Retrieve weather data (wttr.in / Open-Meteo) |
| `summarize` | Summarize URLs, YouTube videos, or local files |
| `tmux` | Control tmux sessions remotely |
| `memory` | Two-layer memory system (facts + history) |
| `cron` | Operate scheduled reminders and recurring tasks |
| `clawhub` | Search and install skills from the ClawHub marketplace |
| `skill-creator` | Step-by-step guide to author custom skills |

See the [Skills guide](skills.md) for more information.

---

## Tools vs. Skills

| Aspect | Tools | Skills |
|--------|-------|--------|
| Nature | Python code callable by the agent | Markdown documents that load into context |
| Extension path | Update nanobot core or use MCP | Anyone can write `.md` skills |
| Trigger | Agent decides based on context | `description` field triggers load |
| Capability | Perform actions (shell, network, files…) | Teach processes, scripts, references |
| Distribution | Bundled with nanobot | `.skill` packages uploadable to ClawHub |

---

## MCP integration

[Model Context Protocol](https://modelcontextprotocol.io/) lets nanobot load external tool servers without changing the core. MCP tools appear just like built-in tools.

Connection modes:

- **Stdio** – Local process using stdin/stdout
- **HTTP/SSE** – Remote server via URL

Each tool is exposed as `mcp_<server>_<tool>`, which the agent can call immediately.

See the [MCP integration guide](mcp.md) for setup instructions.
