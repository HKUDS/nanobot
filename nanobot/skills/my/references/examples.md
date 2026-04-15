# My Tool — Practical Examples

Concrete scenarios showing when and how to use the my tool effectively.

## Diagnosis

### "Why can't you search the web?"
```
→ my(action="check", key="web_config.enable")
  → False
→ "Web search is disabled. Add web.enable: true to your config to enable it."
```

### "Why did you stop?"
```
→ my(action="check", key="max_iterations")
  → 40
→ my(action="check", key="_last_usage")
  → {"prompt_tokens": 62000, "completion_tokens": 3000}
→ "I hit the iteration limit (40). The task was complex. I can ask the user if they want to increase it."
```

### "What model are you running?"
```
→ my(action="check", key="model")
  → 'anthropic/claude-sonnet-4-20250514'
```

## Adaptive Behavior

### Large codebase analysis
```
→ my(action="check")
  → context_window_tokens: 65536
→ my(action="set", key="context_window_tokens", value=131072)
  → "Set context_window_tokens = 131072 (was 65536)"
→ "I've expanded my context window to handle this large codebase."
```

### Switching to a faster model for repetitive tasks
```
→ my(action="set", key="model", value="anthropic/claude-haiku-4-5-20251001")
  → "Set model = 'anthropic/claude-haiku-4-5-20251001' (was 'anthropic/claude-sonnet-4-20250514')"
→ "Switched to a faster model for these batch tasks."
```

## Cross-Turn Memory

### Remembering user preferences
```
# Turn 1: user says "keep it brief"
→ my(action="set", key="user_style", value="concise")
  → "Set scratchpad.user_style = 'concise'"

# Turn 3: new topic
→ my(action="check", key="user_style")
  → 'concise'
  (adjusts response style accordingly)
```

### Tracking project context
```
→ my(action="set", key="active_branch", value="feat/auth")
→ my(action="set", key="test_framework", value="pytest")
→ my(action="set", key="has_docker", value=true)
```

## Budget Awareness

### Token-conscious behavior
```
→ my(action="check", key="_last_usage")
  → {"prompt_tokens": 58000, "completion_tokens": 12000}
→ "I've consumed ~70k tokens. I'll keep my remaining responses focused."
```
