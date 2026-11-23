# Image Generation

nanobot can generate new images and edit existing ones directly in chat. Image generation is off by default—enable it in Settings, then describe the image you want in plain language.

## Quick Setup

**In the WebUI:**

1. Make sure your image provider is added under **Settings → Models → Provider → Add provider**.
2. Open **Settings → Capabilities → Image generation**.
3. Choose the provider and image model, turn on **Image generation**, and click **Save**.
4. Ask nanobot for a test image in chat (if the WebUI asks for a restart, restart first).

<details>
<summary>Manual configuration</summary>

Merge this snippet into `~/.nanobot/config.json`, replacing `provider` and `model` with any supported image provider and model you use:

```json
{
  "providers": {
    "openrouter": {
      "apiKey": "${OPENROUTER_API_KEY}"
    }
  },
  "tools": {
    "imageGeneration": {
      "enabled": true,
      "provider": "openrouter",
      "model": "openai/gpt-5.4-image-2"
    }
  }
}
```

</details>

> [!TIP]
> Prefer environment variables like `${OPENROUTER_API_KEY}` instead of pasting raw API keys into `config.json`.

## Using Image Generation in Chat

1. Describe the image you want—include aspect ratio or size if you want something other than the default.
2. Attach a reference image when you want to edit an existing picture (with a provider/model that supports editing).
3. Ask for follow-up tweaks in the same chat—such as *"make it warmer"*, *"change the background"*, or *"try a 16:9 version"*—and nanobot will build on the previous image automatically.

Generated images are saved locally under `~/.nanobot/media/generated/YYYY-MM-DD/`.

## Configuration Reference

| Option | Default | Description |
|---|---|---|
| `tools.imageGeneration.enabled` | `false` | Enable or disable image generation |
| `tools.imageGeneration.provider` | `"openrouter"` | Provider name (`openrouter`, `openai`, `openai_codex`, `custom`, `aihubmix`, `minimax`, `gemini`, `ollama`, `stepfun`, `zhipu`, `modelscope`, or a named custom connection) |
| `tools.imageGeneration.model` | `"openai/gpt-5.4-image-2"` | Image model ID |
| `tools.imageGeneration.defaultAspectRatio` | `"1:1"` | Default aspect ratio when not specified in chat |
| `tools.imageGeneration.defaultImageSize` | `"1K"` | Default size hint (e.g. `1K`, `2K`, `4K`, or `1024x1024`) |
| `tools.imageGeneration.maxImagesPerTurn` | `4` | Maximum images per request (`1`–`8`) |
| `tools.imageGeneration.saveDir` | `"generated"` | Subfolder inside nanobot's media directory for saved images |

### Custom connections and advanced options

You can reuse any custom connection created in **Settings → Models → Manage providers** as long as its endpoint supports the OpenAI Images API (`/images/generations`).

For image-only request differences (such as provider-specific quality or watermark parameters), use **Advanced options → Headers / Body parameters** in Image generation settings (or `tools.imageGeneration.extraHeaders` and `extraBody` in JSON). Switching image providers in the WebUI clears those overrides automatically so settings do not leak to another service.

## Provider Notes

For all providers below, configure the connection in **Settings → Models** and select it under **Settings → Capabilities → Image generation**. Expand **Manual configuration** if you edit `config.json` directly.

### OpenRouter

Use any OpenRouter model that supports image output (and image editing if you want reference-image edits).

<details>
<summary>Manual configuration</summary>

```json
{
  "tools": {
    "imageGeneration": {
      "enabled": true,
      "provider": "openrouter",
      "model": "openai/gpt-5.4-image-2"
    }
  }
}
```

</details>

### OpenAI Codex

Sign in with `nanobot provider login openai-codex`, then choose **OpenAI Codex** and `gpt-image-2` in image settings. Supports both generation and reference-image edits using your Codex subscription.

<details>
<summary>Manual configuration</summary>

```json
{
  "tools": {
    "imageGeneration": {
      "enabled": true,
      "provider": "openai_codex",
      "model": "gpt-image-2"
    }
  }
}
```

</details>

### Custom (OpenAI-compatible)

Works with services implementing `POST /v1/images/generations` (returning `b64_json` or `url`). Requires `apiBase`; `apiKey` is optional for local servers. Reference-image edits are not supported by the generic `custom` provider.

<details>
<summary>Manual configuration</summary>

```json
{
  "providers": {
    "custom": {
      "apiKey": "${CUSTOM_IMAGE_API_KEY}",
      "apiBase": "https://api.example.com/v1"
    }
  },
  "tools": {
    "imageGeneration": {
      "enabled": true,
      "provider": "custom",
      "model": "your-model-name"
    }
  }
}
```

Use `extraBody` for provider-specific options—for example, `"response_format": "url"` (Agnes AI), `"response_format": "base64"` (Together AI), or explicit `size` values (Volcengine Ark Seedream).

</details>

### AIHubMix

Supports `gpt-image-2-free`. Optional `extraBody: {"quality": "low"}` can make free generations faster and less likely to time out.

<details>
<summary>Manual configuration</summary>

```json
{
  "providers": {
    "aihubmix": {
      "apiKey": "${AIHUBMIX_API_KEY}",
      "extraBody": {
        "quality": "low"
      }
    }
  },
  "tools": {
    "imageGeneration": {
      "enabled": true,
      "provider": "aihubmix",
      "model": "gpt-image-2-free"
    }
  }
}
```

</details>

### MiniMax

Supports text-to-image and editing (up to 16 reference images) with `MiniMax-H3-Image` and `MiniMax-H3-Image-Highspeed`, plus legacy `image-01`. Accepts `1K`, `2K`, `4K`, or explicit dimensions like `2720x1536`. See [MiniMax's image docs](https://platform.minimax.io/docs/guides/image-generation) for size limits and pricing. Note that a timed-out H3 request may still complete and be billed.

<details>
<summary>Manual configuration</summary>

```json
{
  "providers": {
    "minimax": {
      "apiKey": "${MINIMAX_API_KEY}"
    }
  },
  "tools": {
    "imageGeneration": {
      "enabled": true,
      "provider": "minimax",
      "model": "MiniMax-H3-Image",
      "defaultAspectRatio": "1:1"
    }
  }
}
```

</details>

### Gemini

Supports `gemini-2.5-flash-image` (supports reference-image edits) and `imagen-4.0-generate-001` (text-to-image only; supports `1:1`, `9:16`, `16:9`, `3:4`, `4:3`). Sizing is controlled by `defaultAspectRatio` (`defaultImageSize` is ignored).

<details>
<summary>Manual configuration</summary>

```json
{
  "providers": {
    "gemini": {
      "apiKey": "${GEMINI_API_KEY}"
    }
  },
  "tools": {
    "imageGeneration": {
      "enabled": true,
      "provider": "gemini",
      "model": "gemini-2.5-flash-image"
    }
  }
}
```

</details>

### Ollama

Works with local Ollama (`http://localhost:11434/api`, no API key needed) and hosted `https://ollama.com/api` (requires API key). Reference images are not supported.

<details>
<summary>Manual configuration</summary>

```json
{
  "providers": {
    "ollama": {
      "apiBase": "http://localhost:11434/api"
    }
  },
  "tools": {
    "imageGeneration": {
      "enabled": true,
      "provider": "ollama",
      "model": "x/z-image-turbo",
      "defaultAspectRatio": "16:9",
      "defaultImageSize": "2K"
    }
  }
}
```

</details>

### StepFun

Supports `step-image-edit-2` (text-to-image) and `step-1x-medium` (adds style-reference edits). Shares `providers.stepfun.apiKey` with StepFun chat models. For StepPlan subscriptions, set `apiBase` to `https://api.stepfun.ai/step_plan/v1`.

<details>
<summary>Manual configuration</summary>

```json
{
  "providers": {
    "stepfun": {
      "apiKey": "${STEPFUN_API_KEY}"
    }
  },
  "tools": {
    "imageGeneration": {
      "enabled": true,
      "provider": "stepfun",
      "model": "step-image-edit-2"
    }
  }
}
```

</details>

### Zhipu

Supports `glm-image`, `cogview-4`, `cogview-4-250304`, and `cogview-3-flash` (text-to-image only). Supported aspect ratios: `1:1`, `16:9`, `9:16`, `3:4`, `4:3`, or explicit `WIDTHxHEIGHT`.

<details>
<summary>Manual configuration</summary>

```json
{
  "providers": {
    "zhipu": {
      "apiKey": "${ZAI_API_KEY}"
    }
  },
  "tools": {
    "imageGeneration": {
      "enabled": true,
      "provider": "zhipu",
      "model": "glm-image"
    }
  }
}
```

</details>

### ModelScope

Supports text-to-image and image editing (e.g. `Qwen/Qwen-Image-2512`). Supported aspect ratios: `1:1`, `16:9`, `9:16`, `3:4`, `4:3`, or explicit `WIDTHxHEIGHT`.

<details>
<summary>Manual configuration</summary>

```json
{
  "providers": {
    "modelscope": {
      "apiKey": "${MODELSCOPE_API_KEY}"
    }
  },
  "tools": {
    "imageGeneration": {
      "enabled": true,
      "provider": "modelscope",
      "model": "Qwen/Qwen-Image-2512"
    }
  }
}
```

</details>

## Prompting Tips

For better results, include the subject, composition, style/mood/lighting, any exact quoted text, and what should stay unchanged when editing:

```text
A minimal app icon for nanobot: friendly robot head, rounded square, soft blue and white palette, clean vector style, no text
```

```text
Use the reference image. Keep the same robot and composition, change the palette to warm orange, and add a subtle sunrise background.
```

## Troubleshooting

| Symptom | Fix |
|---|---|
| Image generation is unavailable | Enable it in **Settings → Capabilities → Image generation** and save (restart the gateway after manual JSON edits) |
| Missing API key | Configure the provider's API key; if using `${VAR_NAME}`, confirm the variable is set before starting nanobot |
| Unsupported image provider | Use one of the supported providers listed above or a saved custom connection |
| Generation times out | Try a smaller size, set `extraBody.quality: "low"` on AIHubMix, or retry later |
| Reference image rejected | Confirm the file is a valid image inside your workspace or nanobot media directory |
