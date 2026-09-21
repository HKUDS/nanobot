# Custom prompt commands

Custom commands are saved user prompts, not shell commands or a workflow engine. In the WebUI, open **Skills → Commands** to create, edit, enable/disable or delete one. Management is available only from the gateway device; authenticated remote clients can discover and invoke existing commands. Built-in names such as `/stop`, `/goal` and `/model` cannot be replaced.

Type `/review topic` in the existing composer menu. Tab completes without sending. The command body expands only when explicitly submitted and enters the normal agent turn or running turn's input queue. Tools, approvals and workspace restrictions remain unchanged. The CLI and chat channels use the same runtime expansion; `/help` lists effective custom commands. Normal responses and system/automation continuation messages do not expand commands.

## Files and scope

- **User**: `<active-config-directory>/commands/<name>.md`. This means the current instance, not a hard-coded home directory.
- **Workspace**: `<workspace>/.nanobot/commands/<name>.md`. WebUI conversations use their selected project; CLI and other channels use the configured default workspace.
- The settings editor manages the default workspace. Commands for another project can be edited in that project's directory. The composer refreshes on project/session change, app focus, and in-app saves.
- Workspace definitions shadow user definitions of the same name, including disabled or invalid definitions. Deleting a workspace override can reactivate the user definition. Sources and overrides are shown in the manager.

Example `review.md`:

```markdown
---
description: Review a patch carefully
argument_hint: "[files or topic]"
enabled: true
---
Review $ARGUMENTS for correctness and regressions. Explain findings before making changes.
```

Names use lowercase ASCII letters, digits and hyphens, start with a letter, and have at most 48 characters. Frontmatter permits only `description`, `argument_hint` and `enabled` with flat scalar values. Aliases, tags, nested structures, symlinked command files/directories, empty bodies and unknown fields are rejected. Each source has a 128-command limit; files are limited to 64 KiB and metadata to 4 KiB.

`$ARGUMENTS` is replaced with the literal text following the name. Without that marker, arguments are appended. No positional expressions, environment expansion, shell execution, file interpolation or recursive slash dispatch takes place. Review workspace commands before invoking them, just as you would review any prompt supplied by a repository.

The expanded prompt becomes normal user-message content and follows the conversation's existing retention policy. Temporary chats may invoke prompt commands but retain their existing restricted scope, disabled tools and non-persistent history. Saving a definition is an explicit durable operation independent of a temporary conversation; merely invoking one never writes to its definition.

## Updates and recovery

Saves use a file lock, revision check, fsync and atomic replacement. Concurrent stale edits return a conflict instead of overwriting newer content. Invalid files are counted in the manager and skipped; repair their frontmatter in a text editor. Renaming is create-new then delete-old. Deleting removes only the named definition, not prior conversations; keep these Markdown files in your normal configuration/project backup or version control. No existing file is migrated or removed at startup, and older nanobot versions ignore this new directory.
