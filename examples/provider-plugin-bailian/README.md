# Alibaba BaiLian Provider Plugin Example

This folder is a complete provider plugin example for nanobot.

It demonstrates how to provide Alibaba Cloud BaiLian (DashScope) from an external package instead of modifying nanobot core code.

## Why this demonstrates strong customization

Compared with nanobot core provider config, this plugin shows a custom capability:

- Use provider-level `extraBody` directly (transparent passthrough)
- Demonstrate Qwen3.5 multimodal understanding (image + text) on BaiLian OpenAI-compatible API

This means you can extend provider behavior in a plugin without adding new fields to nanobot core schema.

## What this plugin provides

- Provider spec entry point: `nanobot.provider_specs`
- Provider factory entry point: `nanobot.provider_factories`
- Provider name: `aliyun_bailian`

## Install in editable mode

```bash
cd examples/provider-plugin-bailian
uv pip install -e .
```

## Reload plugins in nanobot

```bash
nanobot provider reload
```

You should see `aliyun-bailian` in the plugin provider list.

## Configure nanobot

Merge this into `~/.nanobot/config.json`:

```json
{
  "providers": {
    "plugins": {
      "aliyun_bailian": {
        "apiKey": "YOUR_DASHSCOPE_API_KEY",
        "apiBase": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "extraBody": {
          "enable_thinking": true,
          "enable_search": true,
          "search_options": {
            "forced": true
          }
        },
        "extraHeaders": {
          "X-Trace-Id": "demo-request-id"
        }
      }
    }
  },
  "agents": {
    "defaults": {
      "provider": "aliyun_bailian",
      "model": "qwen3.5-plus"
    }
  }
}
```

Primary option:

- `extraBody`: object -> sent to BaiLian OpenAI-compatible request as `extra_body`

`extraHeaders` is only for real HTTP headers.

## Verify

```bash
nanobot status
nanobot agent -m "hello"
```

## Qwen3.5 multimodal example (image understanding)

This plugin targets BaiLian OpenAI-compatible API. You can also verify multimodal capability directly with the OpenAI SDK:

```python
import os
from openai import OpenAI

client = OpenAI(
  api_key=os.getenv("DASHSCOPE_API_KEY"),
  # US region: https://dashscope-us.aliyuncs.com/compatible-mode/v1
  # Singapore region: https://dashscope-intl.aliyuncs.com/compatible-mode/v1
  base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
)

completion = client.chat.completions.create(
  model="qwen3.5-plus",
  messages=[
    {
      "role": "user",
      "content": [
        {
          "type": "image_url",
          "image_url": {
            "url": "https://help-static-aliyun-doc.aliyuncs.com/file-manage-files/zh-CN/20241022/emyrja/dog_and_girl.jpeg"
          },
        },
        {"type": "text", "text": "What scene is depicted in this image?"},
      ],
    },
  ],
)

print(completion.choices[0].message.content)
```

## Notes

- This example intentionally uses `aliyun_bailian` as plugin provider name to avoid clashing with nanobot's current built-in `dashscope` provider.
- If one day the built-in `dashscope` entry is removed, the same pattern can be used to provide `dashscope` entirely from a plugin package.
- In this example, the custom `extra_body` mapping is implemented in plugin code (`provider_factory.py`), showcasing how plugins can add provider-specific behavior beyond core defaults.
