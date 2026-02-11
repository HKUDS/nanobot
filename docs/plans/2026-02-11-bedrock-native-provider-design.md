# Nanobot Native AWS Bedrock Provider Design

**Date:** 2026-02-11
**Author:** Keith (AWS ML Engineer)
**Status:** Approved

## Overview

Add a native AWS Bedrock provider to nanobot that directly calls boto3 Converse API, bypassing LiteLLM. Supports dual authentication (IAM + Bedrock API Key), cross-region inference profiles, and Claude Opus 4.6 model.

## Motivation

- Direct control over Bedrock Converse API calls without LiteLLM translation layer
- Native support for Bedrock API Key authentication
- First-class support for Opus 4.6 and inference profile model IDs (global., us., eu., ap.)

## Configuration

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
      "model": "bedrock/anthropic.claude-opus-4-6-v1"
    }
  }
}
```

### Config Rules

- `providers.bedrock.apiKey` — Optional. Present: use Bedrock API Key auth. Absent: use IAM auth chain (env vars -> ~/.aws/credentials -> IAM Role)
- `providers.bedrock.region` — Optional, default `us-east-1`. Ignored when model ID has cross-region prefix
- Model name format: `bedrock/<model-id>`

### Supported Model IDs

| Model ID | Description |
|----------|-------------|
| `bedrock/anthropic.claude-opus-4-6-v1` | Single region, Opus 4.6 |
| `bedrock/us.anthropic.claude-opus-4-6-v1` | US cross-region |
| `bedrock/eu.anthropic.claude-opus-4-6-v1` | EU cross-region |
| `bedrock/ap.anthropic.claude-opus-4-6-v1` | AP cross-region |
| `bedrock/global.anthropic.claude-opus-4-6-v1` | Global cross-region |
| `bedrock/global.anthropic.claude-opus-4-6-v1[1m]` | Global, 1M context |
| `bedrock/anthropic.claude-opus-4-5-v2` | Claude 4.5 |

### Schema Addition (schema.py)

```python
class BedrockConfig(BaseModel):
    api_key: Optional[str] = None
    region: str = "us-east-1"
```

## Architecture

### BedrockProvider Class

File: `nanobot/providers/bedrock_provider.py`

```python
class BedrockProvider:
    def __init__(self, api_key, region, model)
    def _create_client(self, api_key, region, model) -> boto3.Client
    def _infer_region(self, model_id) -> str
    def _extract_model_id(self, model) -> str
    async def chat(self, messages, tools, stream) -> LLMResponse
    async def _converse(self, messages, tools) -> LLMResponse
    async def _converse_stream(self, messages, tools) -> AsyncGenerator
    def _convert_messages(self, messages) -> tuple[list, list]
    def _convert_tools(self, tools) -> list
```

### Core Methods

| Method | Responsibility |
|--------|---------------|
| `chat()` | Entry point, dispatches to sync/stream based on `stream` param |
| `_converse()` | Calls `client.converse()`, returns complete response |
| `_converse_stream()` | Calls `client.converse_stream()`, yields chunks |
| `_convert_messages()` | Converts nanobot OpenAI-format messages to Converse API format |
| `_convert_tools()` | Converts OpenAI tool definitions to Converse toolSpec format |

## Authentication

### IAM Authentication (default)

```python
boto3.client("bedrock-runtime", region_name=region)
```

Standard AWS credential chain: environment variables -> ~/.aws/credentials -> IAM Role.

### Bedrock API Key Authentication

boto3 does not natively support API Key auth. Implementation uses botocore event system to inject Authorization header and disable SigV4 signing:

```python
session = botocore.session.Session()
client = session.create_client(
    "bedrock-runtime",
    region_name=region,
    config=Config(signature_version=UNSIGNED),
)
client.meta.events.register(
    "before-sign.bedrock-runtime.*",
    lambda request, **kwargs: request.headers.update(
        {"Authorization": f"Bearer {api_key}"}
    ),
)
```

### Region Inference for Cross-Region Models

```python
def _infer_region(self, model_id):
    prefix = model_id.split(".")[0]  # "us" / "eu" / "ap" / "global"
    return {
        "us": "us-east-1",
        "eu": "eu-west-1",
        "ap": "ap-northeast-1",
        "global": "us-east-1",
    }.get(prefix, "us-east-1")
```

Cross-region inference profiles still need an entry region, but Bedrock auto-routes to optimal region.

## Message Format Conversion

### System Message

```
OpenAI: [{"role": "system", "content": "You are..."}]
Converse: converse(system=[{"text": "You are..."}], messages=[...])
```

### Text Message

```
OpenAI: {"role": "user", "content": "hello"}
Converse: {"role": "user", "content": [{"text": "hello"}]}
```

### Vision (Image)

```
OpenAI: {"type": "image_url", "image_url": {"url": "data:image/png;base64,xxx"}}
Converse: {"image": {"format": "png", "source": {"bytes": <decoded_bytes>}}}
```

### Tool Use (Assistant calling tool)

```
OpenAI: {"role": "assistant", "tool_calls": [{"id": "call_1", "function": {"name": "read_file", "arguments": "{...}"}}]}
Converse: {"role": "assistant", "content": [{"toolUse": {"toolUseId": "call_1", "name": "read_file", "input": {...}}}]}
```

### Tool Result

```
OpenAI: {"role": "tool", "tool_call_id": "call_1", "content": "result..."}
Converse: {"role": "user", "content": [{"toolResult": {"toolUseId": "call_1", "content": [{"text": "result..."}]}}]}
```

### Tool Definition

```
OpenAI: {"type": "function", "function": {"name": "x", "description": "...", "parameters": {...}}}
Converse: {"toolSpec": {"name": "x", "description": "...", "inputSchema": {"json": {...}}}}
```

## Streaming Response Handling

```python
response = client.converse_stream(modelId=..., messages=..., system=..., toolConfig=..., inferenceConfig=...)

for event in response["stream"]:
    if "contentBlockStart" in event:
        # tool_use start: get toolUseId and name
    elif "contentBlockDelta" in event:
        delta = event["contentBlockDelta"]["delta"]
        if "text" in delta:
            yield text_chunk
        elif "toolUse" in delta:
            accumulate_tool_input  # accumulate JSON fragments
    elif "contentBlockStop" in event:
        # content block end
    elif "messageStop" in event:
        # message end, get stopReason
    elif "metadata" in event:
        # usage info
```

Note: Tool use `input` JSON arrives in fragments during streaming. Must concatenate fully before `json.loads()`.

## Provider Registration & Routing

### Registry (providers/registry.py)

```python
ProviderMeta(
    name="bedrock",
    keywords=["bedrock", "anthropic.claude"],
    env_key=None,
    key_prefix=None,
    base_url=None,
    gateway=None,
)
```

### Routing (cli/commands.py)

```python
def _make_provider(config, model):
    if model.startswith("bedrock/"):
        from nanobot.providers.bedrock_provider import BedrockProvider
        bedrock_config = config.providers.bedrock
        return BedrockProvider(
            api_key=bedrock_config.api_key if bedrock_config else None,
            region=bedrock_config.region if bedrock_config else "us-east-1",
            model=model,
        )
    else:
        return LiteLLMProvider(...)  # existing logic unchanged
```

## Error Handling

```python
from botocore.exceptions import ClientError

except ClientError as e:
    code = e.response["Error"]["Code"]
    # ValidationException → invalid request
    # ModelNotReadyException → model not enabled in console
    # ThrottlingException → rate limited
    # AccessDeniedException → IAM or API key issue
    # ModelTimeoutException → timeout
```

No custom retry logic — boto3 built-in retry handles transient errors and throttling.

## File Changes

| File | Operation | Description |
|------|-----------|-------------|
| `providers/bedrock_provider.py` | **New** | BedrockProvider class, ~250 lines |
| `config/schema.py` | Modify | Add BedrockConfig, add bedrock field to ProvidersConfig |
| `providers/registry.py` | Modify | Add bedrock entry to PROVIDERS tuple |
| `cli/commands.py` | Modify | Add bedrock routing branch in _make_provider |
| `pyproject.toml` or `setup.py` | Modify | Add boto3 dependency |

### Files NOT Changed

- `providers/litellm_provider.py` — untouched
- `agent/loop.py` — untouched (BedrockProvider returns same LLMResponse format)
- `channels/*` — untouched
- `tools/*` — untouched

## Design Principles

- **Zero intrusion** — existing LiteLLM path completely untouched
- **Prefix routing** — `bedrock/` prefix in model name triggers BedrockProvider
- **Dual auth** — API Key (event hook injection) + IAM credential chain
- **Dual region** — single region config + cross-region/global inference profile auto-detection
- **Full feature parity** — chat + streaming + tool use + vision
