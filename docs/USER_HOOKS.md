# User-Defined Hooks

Nanobot supports user-defined hooks via JSON configuration. Hooks allow you to customize agent behavior without modifying nanobot's source code.

## Quick Start

Create `.nanobot/hooks.json` in your workspace:

```json
{
  "hooks": [
    {
      "name": "block-dangerous-commands",
      "event": "PreToolUse",
      "matcher": "^exec$",
      "command": "~/.nanobot/hooks/security-check.sh",
      "priority": 10
    }
  ]
}
```

Create the shell script `~/.nanobot/hooks/security-check.sh`:

```bash
#!/bin/bash

# Check if command contains dangerous patterns
if echo "$TOOL_ARGS" | grep -qE "rm -rf /|format|mkfs"; then
    echo "Dangerous command blocked for safety"
    exit 2  # Block execution
fi

exit 0  # Allow execution
```

Make it executable:

```bash
chmod +x ~/.nanobot/hooks/security-check.sh
```

Done! Nanobot will automatically load and execute your hook.

## Hook Configuration

### Required Fields

- `name`: Unique identifier for the hook
- `event`: Lifecycle event to listen to (see Events below)
- `command`: Shell command to execute

### Optional Fields

- `matcher`: Regex pattern to filter tool names (only for tool events)
- `priority`: Execution order (lower = earlier, default: 100)

### Events

| Event | When | Context Variables |
|-------|------|-------------------|
| `SessionStart` | Session initialization | `HOOK_EVENT` |
| `PreToolUse` | Before tool execution | `HOOK_EVENT`, `TOOL_NAME`, `TOOL_ARGS` |
| `PostToolUse` | After tool execution | `HOOK_EVENT`, `TOOL_NAME`, `TOOL_ARGS`, `TOOL_RESULT` |
| `PreBuildContext` | Before building system prompt | `HOOK_EVENT`, `CONTEXT_TYPE`, `CHANNEL`, `CHAT_ID` |
| `Stop` | Agent shutdown | `HOOK_EVENT` |

### Exit Codes

Your shell script must return:
- **0**: Allow execution (proceed)
- **2**: Block execution (stop)
- **Other**: Treated as error, execution proceeds

### Environment Variables

Hooks receive these environment variables:

- `HOOK_EVENT`: Event name (e.g., "PreToolUse")
- `TOOL_NAME`: Tool being called (for tool events)
- `TOOL_ARGS`: JSON-encoded tool arguments (for tool events)
- `TOOL_RESULT`: Tool execution result (for PostToolUse only)

## Examples

### Example 1: Block Dangerous Commands

```json
{
  "hooks": [
    {
      "name": "security-guard",
      "event": "PreToolUse",
      "matcher": "^exec$",
      "command": "~/.nanobot/hooks/security-check.sh"
    }
  ]
}
```

```bash
#!/bin/bash
# security-check.sh

if echo "$TOOL_ARGS" | jq -r '.command' | grep -qE "rm -rf /|sudo rm"; then
    echo "Dangerous command blocked"
    exit 2
fi

exit 0
```

### Example 2: Audit Log

```json
{
  "hooks": [
    {
      "name": "audit-logger",
      "event": "PostToolUse",
      "command": "~/.nanobot/hooks/audit-log.sh",
      "priority": 200
    }
  ]
}
```

```bash
#!/bin/bash
# audit-log.sh

LOG_FILE="$HOME/.nanobot/audit.log"
echo "$(date): $TOOL_NAME" >> "$LOG_FILE"
exit 0
```

### Example 3: Working Hours Restriction

```json
{
  "hooks": [
    {
      "name": "working-hours",
      "event": "PreToolUse",
      "matcher": "(exec|write_file)",
      "command": "~/.nanobot/hooks/check-hours.sh"
    }
  ]
}
```

```bash
#!/bin/bash
# check-hours.sh

HOUR=$(date +%H)

if [ "$HOUR" -lt 9 ] || [ "$HOUR" -gt 18 ]; then
    echo "Tool usage restricted to working hours (9am-6pm)"
    exit 2
fi

exit 0
```

### Example 4: Rate Limiting

```json
{
  "hooks": [
    {
      "name": "rate-limiter",
      "event": "PreToolUse",
      "matcher": "^web_search$",
      "command": "~/.nanobot/hooks/rate-limit.sh"
    }
  ]
}
```

```bash
#!/bin/bash
# rate-limit.sh

COUNTER_FILE="/tmp/nanobot-search-count"
MAX_SEARCHES=10

# Read current count
COUNT=$(cat "$COUNTER_FILE" 2>/dev/null || echo 0)

if [ "$COUNT" -ge "$MAX_SEARCHES" ]; then
    echo "Search rate limit exceeded ($MAX_SEARCHES per session)"
    exit 2
fi

# Increment counter
echo $((COUNT + 1)) > "$COUNTER_FILE"
exit 0
```

## Built-in Hooks

Nanobot includes one built-in hook:

- **SkillsEnabledFilter**: Filters disabled skills from the system prompt
  - Managed via `nanobot skills disable/enable` commands
  - State stored in `hooks/state.json`

## Dynamic Prompt Injection

Hooks can inject content into the system prompt at build time using the `PreBuildContext` event with `CONTEXT_TYPE=prompt_injection`. This enables use cases like topic-specific memory, per-channel personality, or any runtime-conditional prompt content.

### How It Works

1. During context building, nanobot fires `PreBuildContext` with `CONTEXT_TYPE=prompt_injection`
2. Your hook receives `CHANNEL` and `CHAT_ID` as environment variables
3. Your hook prints content to stdout and exits with code 0
4. The output is collected and wrapped in `<dynamic_context>` tags in the system prompt

Multiple hooks can each contribute content — injections are accumulated, not chained.

### Environment Variables

| Variable | Description |
|----------|-------------|
| `HOOK_EVENT` | Always `PreBuildContext` |
| `CONTEXT_TYPE` | Always `prompt_injection` for this flow |
| `CHANNEL` | Current channel name (may be empty) |
| `CHAT_ID` | Current chat/conversation ID (may be empty) |

### Exit Codes

- **0**: Proceed; stdout is captured as injected content
- **2**: Block; stops further injection collection
- **Other**: Treated as error, skipped

### Example: Topic Memory

Inject topic-specific notes based on the chat ID:

```json
{
  "hooks": [
    {
      "name": "topic-memory",
      "event": "PreBuildContext",
      "command": "~/.nanobot/hooks/topic-memory.sh",
      "priority": 50
    }
  ]
}
```

```bash
#!/bin/bash
# topic-memory.sh — inject topic-specific context

[ "$CONTEXT_TYPE" != "prompt_injection" ] && exit 0

MEMORY_DIR="$HOME/.nanobot/topics"
TOPIC_FILE="$MEMORY_DIR/${CHAT_ID}.md"

if [ -f "$TOPIC_FILE" ]; then
    cat "$TOPIC_FILE"
fi

exit 0
```

### Example: Per-Channel Personality

```bash
#!/bin/bash
# channel-personality.sh

[ "$CONTEXT_TYPE" != "prompt_injection" ] && exit 0

case "$CHANNEL" in
  "support")
    echo "You are a patient, helpful support agent. Always ask clarifying questions."
    ;;
  "engineering")
    echo "You are a senior engineer. Be concise and technical."
    ;;
esac

exit 0
```

### Limits

Injected content is capped at 4000 characters total across all hooks. Content beyond this limit is truncated.

## Debugging

Enable debug logging to see hook execution:

```bash
export LOGURU_LEVEL=DEBUG
nanobot agent -m "test message"
```

You'll see logs like:

```
DEBUG | Loaded user hook: security-guard
INFO  | Hook 'security-guard' blocked: Dangerous command blocked
```

## Best Practices

1. **Keep hooks fast**: Hooks run synchronously and block agent execution
2. **Use matcher**: Filter by tool name to avoid unnecessary executions
3. **Handle errors**: Always return exit code 0 or 2, never crash
4. **Test thoroughly**: Test your hooks with various inputs before deploying
5. **Log decisions**: Use `echo` to explain why a hook blocked execution

## Troubleshooting

**Hook not loading?**
- Check JSON syntax: `cat ~/.nanobot/workspace/.nanobot/hooks.json | jq`
- Check file permissions: `ls -la ~/.nanobot/hooks/`
- Enable debug logging: `export LOGURU_LEVEL=DEBUG`

**Hook not blocking?**
- Verify exit code: Add `echo "Exit code: $?"` after your check
- Check matcher regex: Test with `echo "tool_name" | grep -E "your_pattern"`
- Verify environment variables: Add `env | grep TOOL` to your script

**Hook timing out?**
- Hooks have a 30-second timeout
- Optimize slow operations (database queries, API calls)
- Consider using PostToolUse for async operations
