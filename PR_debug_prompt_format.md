Improve debug prompt logging format for better readability
================================================================

## Summary

This PR improves the debug prompt logging mechanism in `LiteLLMProvider` to output human-readable, well-formatted text logs instead of JSONL. The logs now clearly show the full prompt (messages + tools) sent to the LLM in each call, making it much easier to debug and understand what context the model receives.

Upstream repository: https://github.com/HKUDS/nanobot

## Problem

Previously, the debug prompt logging (if implemented) would likely output raw JSON, which:
- Is hard to read when messages contain long system prompts, HTML fragments, or truncated content
- Causes syntax highlighting issues in editors when JSON contains unclosed quotes (e.g., from truncated HTML like `<img src="https://img.shields.io`)
- Makes it difficult to quickly scan what was actually sent to the LLM

## Changes

### 1. Added `_debug_log_prompt` method

A new method in `LiteLLMProvider` that:
- Formats the full prompt (messages + tools) in a human-readable text format
- Writes to `~/.nanobot/debug/prompts.log` (using `.log` extension instead of `.jsonl` to avoid JSON syntax highlighting issues)
- Only keeps the **most recent** LLM call (overwrites the file each time) to avoid disk bloat

### 2. Format improvements

The log format includes:
- **Header**: Timestamp and model name
- **Messages section**: Each message numbered `[1]`, `[2]`, etc., with:
  - Role and tool_calls hint (e.g., `[3] assistant (tool_calls: exec, read_file):`)
  - Content indented with 4 spaces for readability
  - Proper handling of both string and structured content
- **Tools section**: List of all tool definitions with names and descriptions

### 3. Integration

The method is called in `chat()` right before sending the request to LiteLLM, ensuring we capture exactly what gets sent to the provider.

## Behavior Impact

- **Before**: No debug prompt logging (or raw JSON that's hard to read)
- **After**: 
  - Each LLM call writes a clean, readable log to `~/.nanobot/debug/prompts.log`
  - The file always contains only the **latest** call (overwrites on each new call)
  - Format is optimized for human reading, with clear sections and indentation
  - No JSON syntax highlighting issues even when content contains unclosed quotes or HTML fragments

## Example Output

```
================================================================================
2026-02-26T11:28:17.941640  model=minimax/MiniMax-M2.5

=== MESSAGES ===

[1] system:
    # nanobot 🐈
    
    You are nanobot, a helpful AI assistant.
    ...

[2] user:
    比较openclaw和nanobot
    
    [Runtime Context]
    Current Time: 2026-02-26 11:28 (Thursday) (中国标准时间)
    Channel: cli
    Chat ID: direct

[3] assistant (tool_calls: web_fetch):
    
    让我获取更多信息来比较这两个项目：

=== TOOLS (definitions) ===
- read_file: Read the contents of a file at the given path.
- write_file: Write content to a file at the given path. Creates parent directories if needed.
- exec: Execute a shell command and return its output. Use with caution.
...
```

## Testing

1. Run any `nanobot agent` command that triggers an LLM call
2. Check `~/.nanobot/debug/prompts.log`
3. Verify:
   - The file contains a well-formatted, readable log
   - All messages are numbered and indented
   - Tool definitions are listed at the end
   - The file is overwritten on each new call (only latest call is kept)

## Benefits

- **Better debugging**: Developers can quickly see exactly what prompt was sent to the LLM
- **No syntax highlighting issues**: Using `.log` extension avoids JSON parsing problems
- **Clean format**: Indentation and sections make it easy to scan
- **Minimal disk usage**: Only keeps the latest call, not a growing history

## Future Work

This debug logging can be extended to:
- Support keeping a configurable number of recent calls (e.g., last 5)
- Add token counting and cost estimation
- Include response metadata (tokens used, finish reason, etc.)
