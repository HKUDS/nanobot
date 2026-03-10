# PR: LLM Retries and Improved Error Messages

## Problem

When the LLM backend (e.g. hosted vLLM, local vLLM) returns transient errors like `500 Internal Server Error`, the request fails immediately with an opaque error message such as:

```
Error calling LLM: litellm.InternalServerError: Hosted_vllmException - {"error":{"message":"500 Internal Server Error: Internal Server Error",...}}
```

Users get no retries and a technical error string that is not actionable.

## Solution

This PR adds three small, surgical changes:

### 1. Retries for transient errors

- LiteLLM's `num_retries` is now passed to `acompletion()` so transient 500s, rate limits, and connection errors are retried automatically.
- Default: 2 retries.

### 2. Configurable retries

- New config option: `agents.defaults.llmRetries` (or `llm_retries` in snake_case).
- Example in `~/.nanobot/config.json`:

```json
{
  "agents": {
    "defaults": {
      "model": "anthropic/claude-opus-4-5",
      "llmRetries": 2
    }
  }
}
```

- Set to `0` to disable retries. Default is `2` if omitted.

### 3. Clearer user-facing error message

- When retries are exhausted, the user now sees:

  > The AI model server returned a temporary error. We retried 2 times. Please try again in a moment.

- The raw exception is still logged with `logger.error()` for debugging.

## Files changed

| File | Change |
|------|--------|
| `nanobot/config/schema.py` | Add `llm_retries` to `AgentDefaults` |
| `nanobot/providers/litellm_provider.py` | Add `num_retries` param, pass to LiteLLM, improve error message |
| `nanobot/cli/commands.py` | Pass `config.agents.defaults.llm_retries` to `LiteLLMProvider` |

## Backward compatibility

- No breaking changes. Existing configs work without `llmRetries`; default is 2 retries.
- Existing tests pass; `LiteLLMProvider` calls without `num_retries` use the default.
