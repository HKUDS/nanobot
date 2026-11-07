# My Tool — Practical Examples

Concrete scenarios showing when and how to use the my tool effectively.

## Diagnosis

### "Why can't you search the web?"
```
→ my(action="check", key="web_config.enable")
  → False
→ "Web search is disabled. Set tools.web.enable: true in your config to enable it."
```

### "Why did you stop?"
```
→ my(action="check", key="max_iterations")
  → 40
→ "I hit the iteration limit (40). The task was complex. I can ask the user if they want to increase it."
```

### "What model are you running?"
```
→ my(action="check", key="model")
  → 'anthropic/claude-sonnet-4-6'
→ my(action="check", key="model_preset")
  → 'deep'
```

### "Which project can you access?"
```
→ my(action="check", key="workspace_sandbox.workspace_root")
  → workspace_sandbox.workspace_root: '/projects/nanobot'
→ my(action="check", key="workspace_sandbox.restrict_to_workspace")
  → workspace_sandbox.restrict_to_workspace: True
```

`workspace` is a legacy agent-directory display. Setting it does not switch the project or change file permissions.

## Adaptive Behavior

### Large codebase analysis
```
→ my(action="check")
  → context_window_tokens: 200000
→ my(action="set", key="model_preset", value="deep")
  → "Set model_preset = 'deep' for the next turn; context_window_tokens will be 262144"
→ "I've selected the configured deep preset for this session's next turn."
```

### Switching to a configured model preset
```
→ my(action="set", key="model_preset", value="fast")
  → "Set model_preset = 'fast' for the next turn; model will be 'openai/gpt-4.1-mini'"
→ "Selected the fast preset for this session's next turn."
```

## Temporary Runtime Notes

Scratchpad values survive across turns until the runtime restarts and are shared by its sessions. Use them only for non-sensitive temporary notes, not private per-session state or durable preferences.

### Keeping a temporary style preference
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
