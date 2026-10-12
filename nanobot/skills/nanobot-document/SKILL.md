---
name: nanobot-document
description: "Explain how to use, configure, and troubleshoot nanobot using its bundled documentation. Use for nanobot setup, models, WebUI, chat apps, tools, memory, and deployment questions."
---

# nanobot Documentation

Answer nanobot usage questions from the documentation shipped with this installation.

## Find the relevant documentation

The `references/` directory next to this `SKILL.md` is generated from the repository's
`docs/` during builds, including editable installs. Resolve it from this skill's
location in the skills summary, rather than from the user's project directory.
It is inside the built-in skills read root; no additional filesystem permission is needed.

Start with [the documentation index](references/README.md) when the topic is unclear.
For a clear question, start with the smallest relevant guide or reference section:

| Question | Read |
|---|---|
| First setup | [Quick start](references/quick-start.md), or [beginner walkthrough](references/start-without-technical-background.md) |
| Browser workbench and settings | [WebUI](references/webui.md) |
| Provider setup or authentication steps | Matching recipe in [Provider cookbook](references/provider-cookbook.md) |
| Provider/model matching or selection behavior | Relevant section in [Providers](references/providers.md) |
| Exact configuration field or default | [Configuration](references/configuration.md) |
| Connect a specific chat app | Matching platform guide from [Task guides](references/guides/README.md); use [Chat apps](references/chat-apps.md) for details the guide does not cover |
| CLI flags or slash commands | [CLI reference](references/cli-reference.md) or [chat commands](references/chat-commands.md) |
| MCP, search, or another integration | [Task guides](references/guides/README.md) |
| Scheduled tasks or triggers | [Automations](references/automations.md) |
| Memory and persistence | [Memory](references/memory.md) |
| Hosting or separate instances | [Deployment](references/deployment.md) or [multiple instances](references/multiple-instances.md) |
| Errors or unexpected behavior | [Troubleshooting](references/troubleshooting.md) |

If the file is unknown, use `grep` with `glob="*.md"` and
`output_mode="files_with_matches"` on the resolved references directory, or use
`list_dir` to discover files and subdirectories.

Within a long reference, use `grep` with `output_mode="content"` to locate the
relevant heading, configuration key, or error. Then use `read_file` with `offset`
and `limit` to read that section, including its prerequisites and limitations.
Short task guides can be read in full. Collapsed HTML sections still appear in
raw Markdown; they do not reduce how much text a tool read returns.

Stop reading once the documentation supports the requested answer or next
diagnostic step. Follow links or expand the search only to resolve a remaining gap.
Links that leave `references/` point to repository files, not bundled skill resources.

## Explain and diagnose

- Reply in the user's language and adapt the steps to their operating system and
  interface. Give the documented graphical setup steps first when the setting is
  available in the WebUI. Treat manual configuration inside collapsed documentation
  sections as an alternative for headless or explicitly requested config-file work.
  Give direct config-file instructions when the setting has no graphical control.
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
