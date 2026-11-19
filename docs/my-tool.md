# My Tool

The `my` tool lets nanobot inspect its own runtime state—such as which model, workspace, or iteration limit it is using—and optionally adjust safe runtime settings without editing `config.json`.

## What It Lets the Agent Do

- **Self-inspection (on by default):** Answer questions like *"What model are you using?"*, *"Which project folder is active?"*, *"Is web search enabled?"*, or *"What is your iteration limit?"*.
- **Runtime tuning (opt-in):** Switch the current session's model preset, raise or lower the per-turn iteration limit (`1`–`100`), or keep temporary scratchpad notes across turns.

## Configuration

The `my` tool is enabled in **read-only** mode by default. To let the agent adjust allowed runtime settings, merge this into `~/.nanobot/config.json`:

```json
{
  "tools": {
    "my": {
      "enable": true,
      "allowSet": false
    }
  }
}
```

Set `"allowSet": true` to allow runtime adjustments.

## What Persists and What Resets

| Change | Persists across turns? | Persists across gateway restart? |
|---|---|---|
| Switching `model_preset` | Yes (current session) | Yes (saved with the session) |
| Adjusting `max_iterations` | Yes (in memory) | No (resets to `config.json`) |
| Scratchpad notes | Yes (shared across turns in memory) | No (cleared on restart) |

> [!NOTE]
> The `my` tool **never** modifies `config.json` on disk. Do not store sensitive secrets or durable user preferences in scratchpad notes—use [Memory](./memory.md) for preferences that should last.

## Common Examples

You do not need to call the tool manually—just ask nanobot in plain language:

- *"What model and workspace are you using right now?"*
- *"Why didn't you search the web?"* (nanobot can check whether web search is enabled)
- *"Switch this conversation to my `deep` preset."* (when `allowSet` is enabled)
- *"Give yourself up to 80 iterations for this refactoring task."* (when `allowSet` is enabled)

Note that `context_window_tokens` reports the configured window capacity, not live token usage. To see live context usage and per-round stats, use the [WebUI context indicator](./webui.md#activity-and-context-usage).

## Safety Boundaries

- **Never accessible:** Secrets (`apiKey`, `token`, `password`, `secret`, etc.), internal system objects, and channel credentials are always hidden and blocked from both reading and writing.
- **Read-only:** Workspace security restrictions, shell sandbox settings, and web configuration can be inspected for self-diagnosis, but the agent cannot weaken or modify them.
- **Validated limits:** Writable settings like `max_iterations` (`1`–`100`) and `model_preset` (must be an existing configured preset) are strictly validated.
