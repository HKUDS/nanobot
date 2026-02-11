# Feature Request: Native AWS Bedrock Provider (boto3 Converse API)

## Summary

Add a native AWS Bedrock provider that directly calls boto3 Converse API, replacing the current LiteLLM-proxied Bedrock path. Support dual authentication (IAM + Bedrock API Key), cross-region inference profiles (including `global.*`), and first-class Claude Opus 4.6 support.

## Motivation

The current Bedrock support goes through LiteLLM as a translation layer:

```
nanobot → LiteLLM → boto3 → Bedrock API
```

This introduces unnecessary complexity:

- **No direct Converse API control** — LiteLLM abstracts away Bedrock-specific features and error messages
- **No Bedrock API Key support** — LiteLLM only supports IAM authentication for Bedrock
- **Model ID limitations** — inference profile IDs like `global.anthropic.claude-opus-4-6-v1[1m]` may not be handled correctly by LiteLLM's model resolution
- **Debugging difficulty** — errors are wrapped by LiteLLM, making it harder to diagnose Bedrock-specific issues

### Proposed architecture

```
nanobot → BedrockProvider → boto3 → Bedrock Converse API
```

Direct, transparent, and fully controllable.

## Proposed Functionality

### 1. Dual Authentication

| Method | When | How |
|--------|------|-----|
| **Bedrock API Key** | `apiKey` present in config | Inject `Authorization: Bearer` header via botocore event hook, disable SigV4 |
| **IAM credential chain** | `apiKey` absent | boto3 default: env vars → `~/.aws/credentials` → IAM Role |

### 2. Model Support

```
bedrock/anthropic.claude-opus-4-6-v1           # Single region, Opus 4.6
bedrock/anthropic.claude-opus-4-5-v2           # Single region, Claude 4.5
bedrock/us.anthropic.claude-opus-4-6-v1        # US cross-region inference
bedrock/eu.anthropic.claude-opus-4-6-v1        # EU cross-region inference
bedrock/ap.anthropic.claude-opus-4-6-v1        # AP cross-region inference
bedrock/global.anthropic.claude-opus-4-6-v1    # Global cross-region inference
bedrock/global.anthropic.claude-opus-4-6-v1[1m] # Global, 1M context window
```

Cross-region prefix (`us.`, `eu.`, `ap.`, `global.`) auto-detected — entry region inferred automatically.

### 3. Feature Parity

- [x] Chat completion (Converse API)
- [x] Streaming (ConverseStream API)
- [x] Tool use (toolUse / toolResult blocks)
- [x] Vision — image input (base64 / URL)
- [x] System prompt (separate `system` parameter)

### 4. Configuration

```json
{
  "providers": {
    "bedrock": {
      "region": "us-east-1",
      "apiKey": "bedrock-api-key-xxx"
    }
  },
  "agents": {
    "defaults": {
      "model": "bedrock/global.anthropic.claude-opus-4-6-v1"
    }
  }
}
```

- `region` — optional, default `us-east-1`, ignored for cross-region models
- `apiKey` — optional, absent means IAM auth

## Implementation Scope

### New Files

| File | Description |
|------|-------------|
| `nanobot/providers/bedrock_provider.py` | BedrockProvider class (~250 lines) |

### Modified Files

| File | Change |
|------|--------|
| `nanobot/config/schema.py` | Add `BedrockConfig` model, add `bedrock` field to `ProvidersConfig` |
| `nanobot/providers/registry.py` | Add bedrock entry to `PROVIDERS` tuple |
| `nanobot/cli/commands.py` | Add `bedrock/` routing branch in `_make_provider()` |
| `pyproject.toml` / `setup.py` | Add `boto3` to dependencies |

### Files NOT Changed

- `providers/litellm_provider.py` — zero changes
- `agent/loop.py` — zero changes (same `LLMResponse` interface)
- `channels/*` — zero changes
- `tools/*` — zero changes

## Technical Details

### Message Format Conversion (OpenAI → Converse API)

| Type | OpenAI Format | Converse Format |
|------|---------------|-----------------|
| System | `{"role": "system", "content": "..."}` in messages array | Separate `system=[{"text": "..."}]` parameter |
| Text | `{"role": "user", "content": "hello"}` | `{"role": "user", "content": [{"text": "hello"}]}` |
| Image | `{"type": "image_url", "image_url": {"url": "data:..."}}` | `{"image": {"format": "png", "source": {"bytes": ...}}}` |
| Tool call | `{"tool_calls": [{"id": "x", "function": {...}}]}` | `{"content": [{"toolUse": {"toolUseId": "x", ...}}]}` |
| Tool result | `{"role": "tool", "tool_call_id": "x", "content": "..."}` | `{"role": "user", "content": [{"toolResult": {...}}]}` |

### Error Handling

Maps Bedrock `ClientError` codes to user-friendly `ProviderError` messages:

- `ValidationException` → invalid request format
- `ModelNotReadyException` → model not enabled in Bedrock console
- `ThrottlingException` → rate limited
- `AccessDeniedException` → IAM permissions or API key issue
- `ModelTimeoutException` → request timeout

No custom retry — relies on boto3 built-in retry for transient errors.

### Streaming Implementation

ConverseStream events processed in order:
1. `contentBlockStart` — begin text or tool_use block
2. `contentBlockDelta` — incremental text or tool input JSON fragments
3. `contentBlockStop` — block complete
4. `messageStop` — message complete with stopReason
5. `metadata` — token usage

Tool use JSON fragments accumulated and parsed only after `contentBlockStop`.

## Labels

`enhancement` `provider` `aws` `bedrock`

## Priority

High — enables direct AWS Bedrock integration for enterprise/ML engineering use cases without LiteLLM dependency.
