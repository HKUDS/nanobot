---
name: nanobot-document
description: "Explain how to use, configure, and troubleshoot nanobot using its bundled documentation. Use for nanobot setup, models, WebUI, chat apps, tools, memory, and deployment questions; also applies to 如何使用 nanobot、配置 nanobot、nanobot 排错."
---

# nanobot Documentation

Answer nanobot usage questions from the documentation shipped with this installation.

## Find the relevant documentation

The `references/` directory next to this `SKILL.md` is generated from the repository's
`docs/` during builds, including editable installs. Resolve it from this skill's
location in the skills summary, rather than from the user's project directory.
It is inside the built-in skills read root; no additional filesystem permission is needed.

Start with [the documentation index](references/README.md) when the topic is unclear.
For common questions, read the relevant page directly:

| Question | Read |
|---|---|
| First setup | [Quick start](references/quick-start.md), or [beginner walkthrough](references/start-without-technical-background.md) |
| Browser workbench and settings | [WebUI](references/webui.md) |
| Provider, model, or authentication | [Provider cookbook](references/provider-cookbook.md) and [providers](references/providers.md) |
| Exact configuration field or default | [Configuration](references/configuration.md) |
| Telegram, Discord, WeChat, or another chat app | [Chat apps](references/chat-apps.md) |
| CLI flags or slash commands | [CLI reference](references/cli-reference.md) or [chat commands](references/chat-commands.md) |
| MCP, search, or another integration | [Task guides](references/guides/README.md) |
| Scheduled tasks or triggers | [Automations](references/automations.md) |
| Memory and persistence | [Memory](references/memory.md) |
| Hosting or separate instances | [Deployment](references/deployment.md) or [multiple instances](references/multiple-instances.md) |
| Errors or unexpected behavior | [Troubleshooting](references/troubleshooting.md) |

Use `grep` with `glob="*.md"` and `output_mode="files_with_matches"` on the resolved
references directory to locate other topics or an exact error. Read only the relevant
pages or sections with `read_file`; follow links within `references/` as needed.
Links that leave `references/` point to repository files, not bundled skill resources.

## Explain and diagnose

- Reply in the user's language and adapt the steps to their operating system and
  interface. Prefer the documented WebUI flow for ordinary setup; preserve CLI
  instructions for headless or terminal workflows.
- Ground commands, configuration keys, defaults, and prerequisites in the pages you
  actually read. Distinguish documented behavior from your diagnosis of the user's
  environment. Ask for the missing version, error, or setup detail when it changes
  the answer.
- Treat configuration examples as snippets to merge, unless a page explicitly says
  otherwise. Do not ask users to paste API keys, bot tokens, passwords, or unredacted
  configuration files.
- A usage question authorizes explanation. Make configuration changes or run setup
  commands only when the user's request authorizes those actions.
- Cite the relevant bundled page by title and path. If a public link is useful, use
  a link present in that page rather than inventing a wiki route.

## Version scope

Bundled pages describe the source used to build this installation. Source/editable
installs can be ahead of the latest stable release. If the question concerns a
different installation, establish its version before applying these instructions.

For a question about the latest release, use available web tools to consult the
[published documentation](https://nanobot.wiki/docs/latest/getting-started/nanobot-overview)
and state when its version differs from the local installation. Do not substitute
the latest online instructions for local-version behavior silently.

If bundled references are missing, say that local documentation is unavailable and
use the published docs if web access is available, with the version limitation
made explicit. Do not guess an absolute checkout path or request broader file access.
