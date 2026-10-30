# AI Agent Memory in nanobot

nanobot keeps recent conversation history separate from longer-term information such as your preferences. Conversations are summarized as they grow or when you run `/compact`; if Dream is enabled, it can use those summaries to update long-term memory on its schedule, or when you run `/dream`. You can inspect and correct saved preferences. A reply saying it understood your preference does not by itself confirm that the preference was saved.

## The Design

nanobot does not treat memory as one giant file.

It separates memory into layers, because different kinds of remembering deserve different tools:

- `session.messages` holds the living short-term conversation.
- `memory/history.jsonl` is the running archive of compressed past turns.
- `SOUL.md`, `USER.md`, and `memory/MEMORY.md` are the durable knowledge files.
- `GitStore` records how those durable files change over time.

This keeps the system light in the moment, but reflective over time.

## The Flow

Long-term memory is updated in two stages.

### Stage 1: Consolidator

When a conversation grows large, nanobot summarizes the conversation covered by compaction and appends the result to `memory/history.jsonl`. The model continues with the summary and any messages after it. The original messages remain in your saved chat history, but messages covered by the summary are no longer sent to the model verbatim. Each summary preserves useful long-term facts and a short handoff for active work.

Compaction also runs after a configured period of inactivity, or when you send `/compact`. See [Auto Compact](./configuration.md#auto-compact) for idle timing and how to disable automatic idle compaction.

Automatic compaction does not post lifecycle notices to built-in chat channels by default. This only silences chat messages: compaction still runs, and WebUI/TUI retain structured status and history. Manual `/compact` keeps its start and outcome feedback. Set `channels.showCompactionNotices: true` to enable automatic notices globally, or set `showCompactionNotices` in a channel's configuration to override that default. Omitted or `null` channel overrides inherit the global value; existing explicit QQ overrides are preserved.

This file is updated as conversations are summarized. It uses one JSON record per line so nanobot can track which summaries have already been processed; it is primarily an internal working history, not a permanent archive.

Each line is a JSON object:

```json
{"cursor": 42, "timestamp": "2026-04-03 00:02", "content": "- User prefers dark mode\n- Decided to use PostgreSQL"}
```

After scheduled or manual Dream runs, nanobot can prune the oldest entries already processed by Dream and atomically rewrite the file. The default retention target is 1000 entries; entries Dream has not processed are retained even when this exceeds the target. The journal is therefore not a permanent archive of every summary.

It is not the final memory. It is the material from which final memory is shaped.

### Stage 2: Dream

`Dream` is the slower, more thoughtful layer. It runs on a cron schedule while the gateway is running and Dream is enabled, and can also be triggered manually. A standalone Python SDK instance does not start this scheduler.

Dream reads:

- new entries from `memory/history.jsonl`
- the current `SOUL.md`
- the current `USER.md`
- the current `memory/MEMORY.md`

Then it edits the long-term files surgically in a single pass — not by rewriting everything, but by making the smallest honest change that keeps memory coherent.

This is why nanobot's memory is not just archival. It is interpretive.

## The Files

In this page, `workspace` means the configured **agent workspace** (the default is `~/.nanobot/workspace/`, or the path passed with `--workspace`). Selecting a different project in the WebUI changes that chat's project context and tool working directory; it does not relocate the files below.

```text
workspace/
├── .git/                # Version history for long-term memory files
├── SOUL.md              # The bot's long-term voice and communication style
├── USER.md              # Stable knowledge about the user
├── prompts/
│   ├── README.md        # Notes for memory guidance files
│   └── dream.md         # Optional instructions for how Dream organizes memory
└── memory/
    ├── MEMORY.md        # Project facts, decisions, and durable context
    ├── history.jsonl    # History summaries with bounded retention after Dream
    ├── .cursor          # Consolidator write cursor
    └── .dream_cursor    # Dream consumption cursor
```

A selected project may provide its own `AGENTS.md`, but project-local `SOUL.md`, `USER.md`, and `memory/` do not replace the agent-owned files above. This keeps one agent's profile and memory continuous while it works across projects. Use a [separate configured agent workspace](multiple-instances.md) when identity or memory must be isolated. A new chat, SDK `session_key`, or selected project does not create separate long-term memory.

These files play different roles:

- `SOUL.md` remembers how nanobot should sound.
- `USER.md` remembers who the user is and what they prefer.
- `MEMORY.md` remembers what remains true about the work itself.
- `history.jsonl` remembers what happened on the way there.

## Why `history.jsonl`

The old `HISTORY.md` format was pleasant for casual reading, but it was too fragile as an operational substrate.

`history.jsonl` gives nanobot:

- stable incremental cursors
- safer machine parsing
- easier batching
- cleaner migration and compaction
- a better boundary between raw history and curated knowledge

You can still search it with familiar tools:

```bash
# grep
grep -i "keyword" memory/history.jsonl

# jq
cat memory/history.jsonl | jq -r 'select(.content | test("keyword"; "i")) | .content' | tail -20

# Python: last 20 matching entries
python - <<'PY'
import json
from collections import deque

matches = deque(maxlen=20)
with open('memory/history.jsonl', encoding='utf-8') as history:
    for line in history:
        if line.strip():
            content = json.loads(line).get('content', '')
            if 'keyword' in content.lower():
                matches.append(content)
print('\n'.join(matches))
PY
```

The difference is philosophical as much as technical:

- `history.jsonl` is for structure
- `SOUL.md`, `USER.md`, and `MEMORY.md` are for meaning

## Commands

Memory is not hidden behind the curtain. Users can inspect and guide it.

| Command | What it does |
|---------|--------------|
| `/compact` | Summarize the current conversation context while keeping saved chat history |
| `/dream` | Run Dream immediately |
| `/dream-log` | Show the latest Dream memory change |
| `/dream-log <sha>` | Show a specific Dream change |
| `/dream-restore` | List recent Dream memory versions |
| `/dream-restore <sha>` | Restore memory to the state before a specific change |
| `/dream-prompt` | Show how Dream is being guided for memory |
| `/dream-prompt init` | Create an editable Dream memory guide at `prompts/dream.md` |

These commands exist for a reason: automatic memory is powerful, but users should always retain the right to inspect, understand, and restore it.

## Save and Check a Preference

In your existing WebUI or TUI chat, send a specific preference, for example:

```text
For Acme release notes, use concise bullet points and British spelling.
```

To consolidate it now, send `/compact` and wait for its completion, then send `/dream` and wait for the completion message. Dream reads compacted history, so running `/dream` immediately after a short conversation without compaction may find nothing new. Model-based consolidation may decide that no durable change is needed.

Use `/dream-log` to review what changed. Inspect `USER.md` and `memory/MEMORY.md` in the configured agent workspace with your local editor, or select that workspace before asking the agent to read them. A Restricted chat in another project may not have permission to read these files directly. A conversational acknowledgement alone does not confirm that a durable file changed. Start a new chat in the same instance and ask which release-note style is saved to check reuse.

To correct a preference, state what should replace the old value, then repeat compaction, Dream, and inspection. You can also edit the durable files directly; review unprocessed history for old conflicting instructions. `/dream-restore` lists versions, and `/dream-restore <sha>` restores the memory state before that change, including other changes made in that version.

For separate clients with private context, create separate [instances](multiple-instances.md). Labelling a fact with a client name helps organization but does not isolate access.

## Versioned Memory

After Dream changes long-term memory files, nanobot can record that change with `GitStore`.

This gives memory a history of its own:

- you can inspect what changed
- you can compare versions
- you can restore a previous state

That turns memory from a silent mutation into an auditable process.

## Guiding Dream

Dream decides what to keep, update, or forget using nanobot's built-in memory instructions. Most users can leave this alone.

If one workspace needs a different memory style, create an editable guide:

```text
/dream-prompt init
```

This creates:

```text
workspace/prompts/dream.md
```

Edit that file in plain Markdown. When it has content, Dream follows it for this workspace before reading the latest conversation history. You do not need to paste history into the file; Dream adds the current `## Conversation History` block automatically.

To return to nanobot's default behavior, delete `prompts/dream.md` or leave it empty.

Each workspace has its own guide. Changing this file does not affect other nanobot workspaces.

## Configuration

Enable or disable Dream through **Settings → Capabilities → Memory consolidation**. Its frequency, cron override, and model override have no graphical controls; configure those fields directly below.

Dream is configured under `agents.defaults.dream`:

```json
{
  "agents": {
    "defaults": {
      "dream": {
        "intervalH": 2,
        "modelOverride": null
      }
    }
  }
}
```

| Field | Meaning |
|-------|---------|
| `intervalH` | How often Dream runs, in hours |
| `cron` | Cron expression override (takes precedence over `intervalH`) |
| `modelOverride` | Optional model preset name used for Dream |

In practical terms:

- `intervalH` is the normal way to configure Dream frequency. Internally it runs as an `every` schedule.
- `cron` overrides `intervalH` when set, allowing precise cron expressions (e.g. `0 */4 * * *`).
- `modelOverride` selects a named entry from `model_presets` for Dream. It accepts preset names only; raw model identifiers are not supported. If omitted, Dream uses the main agent's selected runtime.

## In Practice

What this means in daily use is simple:

- conversations can stay fast without carrying infinite context
- durable facts can become clearer over time instead of noisier
- the user can inspect and restore memory when needed

Memory should not feel like a dump. It should feel like continuity.

That is what this design is trying to protect.
