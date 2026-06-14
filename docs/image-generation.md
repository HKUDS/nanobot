# Image Generation

nanobot can generate and edit images through the `generate_image` tool. In the WebUI, users can enable **Image Generation** from the composer, choose an aspect ratio, and keep iterating on generated images inside the same chat.

The feature is disabled by default. Enable it in `~/.nanobot/config.json`, configure a supported image provider, then restart the gateway.

## Quick Setup

This snippet uses the current built-in image-generation default so the JSON has concrete names. It is not a provider recommendation; replace `provider` and `model` with any supported image provider and model you intend to use.

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

See [Provider Notes](#provider-notes) for Custom, AIHubMix, MiniMax, Gemini, Ollama, StepFun, and Zhipu configuration examples.

> [!TIP]
> Prefer environment variables for API keys. nanobot resolves `${VAR_NAME}` values from the environment at startup.

## WebUI Usage

In the WebUI composer:

1. Click **Image Generation**.
2. Choose an aspect ratio: `Auto`, `1:1`, `3:4`, `9:16`, `4:3`, or `16:9`.
3. Describe the image or the edit you want.
4. Attach reference images when editing an existing image.

Generated images are rendered as assistant media in the chat. Follow-up prompts such as "make it warmer", "change the background", or "try a 16:9 version" can reuse the most recent generated artifact.

The WebUI hides provider storage details from the user. The agent sees the saved artifact path internally and can pass it back to `generate_image` as `reference_images` for iterative edits.

## Configuration Reference

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `tools.imageGeneration.enabled` | boolean | `false` | Register the `generate_image` tool |
| `tools.imageGeneration.provider` | string | `"openrouter"` | Current built-in image provider default. Supported values: `openrouter`, `openai`, `openai_codex`, `custom`, `aihubmix`, `minimax`, `gemini`, `ollama`, `stepfun`, `zhipu` |
| `tools.imageGeneration.model` | string | `"openai/gpt-5.4-image-2"` | Provider model name |
| `tools.imageGeneration.defaultAspectRatio` | string | `"1:1"` | Default ratio when the prompt/tool call does not specify one |
| `tools.imageGeneration.defaultImageSize` | string | `"1K"` | Default size hint, for example `1K`, `2K`, `4K`, or `1024x1024` |
| `tools.imageGeneration.maxImagesPerTurn` | number | `4` | Maximum `count` accepted by one tool call. Valid range: `1` to `8` |
| `tools.imageGeneration.saveDir` | string | `"generated"` | Relative directory under nanobot's media directory for generated artifacts |

Provider settings reuse normal provider config fields:

| Option | Description |
|--------|-------------|
| `providers.<name>.apiKey` | Provider API key. Prefer `${ENV_VAR}` |
| `providers.<name>.apiBase` | Optional custom base URL |
| `providers.<name>.extraHeaders` | Headers merged into provider requests |
| `providers.<name>.extraBody` | Extra JSON fields merged into provider request bodies |

Both camelCase and snake_case config keys are accepted, but docs use camelCase to match `config.json`.

## Provider Notes

### OpenRouter

OpenRouter uses a chat-completions style image response. Configure:

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

Use a model that supports image generation and image editing if you want reference-image edits.

### Custom (OpenAI-compatible)

The `custom` image provider fits services that implement the synchronous OpenAI Images API:

```text
POST /v1/images/generations
```

The response must include generated images in `data[].b64_json` or `data[].url`. Native prediction APIs, such as Replicate's `/v1/models/{owner}/{model}/predictions`, are not directly compatible unless you put an OpenAI-compatible gateway in front of them.

Configure:

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

The `apiBase` is required. The provider sends requests to `{apiBase}/images/generations` using the OpenAI Images API format with `response_format: "b64_json"`. The `apiKey` is optional for local or unauthenticated endpoints. Reference-image edits are not supported by the generic `custom` provider.

`extraBody` can adapt provider-specific quirks because it is merged last into the request body. Examples:

- Agnes AI documents URL responses, so use `"extraBody": {"response_format": "url"}`.
- Together AI documents `"response_format": "base64"`, so override the default.
- Volcengine Ark Seedream models may require size hints such as `"2K"`, `"3K"`, `"4K"`, or explicit dimensions. Set `tools.imageGeneration.defaultImageSize` or `providers.custom.extraBody.size` to a value supported by the selected model.

For compatibility with the default nanobot setting, custom maps `defaultImageSize: "1K"` to `1024x1024`. Other explicit size hints are passed through unchanged.

### AIHubMix

AIHubMix `gpt-image-2-free` is supported through AIHubMix's unified predictions API. Internally nanobot calls:

```text
/v1/models/openai/gpt-image-2-free/predictions
```

Configure:

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

`quality: low` is optional. It can make free image models faster and less likely to time out, but it is not required for correctness.

### MiniMax

MiniMax `image-01` supports text-to-image and reference-image (subject reference) edits. Supported aspect ratios are `1:1`, `16:9`, `4:3`, `3:2`, `2:3`, `3:4`, `9:16`, and `21:9`.

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
      "model": "image-01",
      "defaultAspectRatio": "1:1"
    }
  }
}
```

### Gemini

nanobot supports two Gemini image generation model families via Google's Generative Language API:

| Model | Endpoint | Reference images |
|-------|----------|-----------------|
| `imagen-4.0-generate-001` | `:predict` | Not supported by this integration |
| `gemini-2.5-flash-image` | `:generateContent` | Supported |

For reference-image edits, use a Gemini Flash image model:

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

Imagen 4 supports the aspect ratios `1:1`, `9:16`, `16:9`, `3:4`, and `4:3`. Unsupported ratios are ignored and the model uses its default. The `defaultImageSize` setting has no effect on Gemini models; sizing is controlled by `defaultAspectRatio` only. Reference images passed with an Imagen model are ignored (with a warning logged).

### Ollama

Ollama's experimental native image generation API works with local servers and hosted ollama.com models. Local access at `http://localhost:11434/api` does not require an API key; set `providers.ollama.apiKey` only when targeting `https://ollama.com/api`.

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

Ollama maps `defaultAspectRatio` and `defaultImageSize` to native `width` and `height` values. Reference images are not supported by this integration.

### StepFun

StepFun (阶跃星辰) `step-image-edit-2` supports text-to-image generation.  The `step-1x-medium` variant additionally supports **style-reference** image edits, where a reference image guides the visual style of the output.

Supported aspect ratios: `1:1`, `16:9`, `9:16`, `3:4`, `4:3`.  Sizes are specified as `WIDTHxHEIGHT` (e.g. `1024x1024`, `1280x800`, `800x1280`).

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

> [!NOTE]
> The StepFun provider reuses the existing `providers.stepfun` config block (the same one used for StepFun's LLM API).  Set `providers.stepfun.apiKey` once and it is shared between text and image generation.
>
> When `step-image-edit-2` is used, `reference_images` are ignored (the model does not support style reference).  Switch to `step-1x-medium` to use reference-image-guided generation.

#### StepPlan (Subscription)

StepPlan is StepFun's subscription tier and uses a different API base URL. The image generation endpoint path is the same — just override `apiBase`:

```json
{
  "providers": {
    "stepfun": {
      "apiKey": "${STEPFUN_API_KEY}",
      "apiBase": "https://api.stepfun.com/step_plan/v1"
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

`apiBase` takes precedence over the registry default, so with the StepPlan base URL configured, image requests are sent to `https://api.stepfun.com/step_plan/v1/images/generations` — the same path prefix used for LLM calls. The API key is shared with the standard StepFun provider.

### Zhipu

Zhipu (智谱) `glm-image` model supports text-to-image generation. The API returns temporary image URLs (valid for 30 days); nanobot downloads and re-encodes them as base64 data URLs.

Supported aspect ratios: `1:1`, `16:9`, `9:16`, `3:4`, `4:3`. Sizes can be specified as `WIDTHxHEIGHT` (e.g. `1280x1280`, `1728x960`) or using aspect ratio presets.

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

Other supported models: `cogview-4`, `cogview-4-250304`, `cogview-3-flash`. Reference images are not supported by this integration.

## Artifacts

Generated images are stored under the active nanobot instance's media directory:

```text
~/.nanobot/media/generated/YYYY-MM-DD/img_<id>.<ext>
~/.nanobot/media/generated/YYYY-MM-DD/img_<id>.json
```

For non-default config locations, the media directory is relative to the active config file's directory.

The JSON sidecar stores:

| Field | Meaning |
|-------|---------|
| `id` | Short generated image id, such as `img_ab12cd34ef56` |
| `path` | Local image path used internally for follow-up edits |
| `mime` | Detected image MIME type |
| `prompt` | Prompt used for the generation |
| `model` | Provider model |
| `provider` | Provider name |
| `source_images` | Reference image paths used for edits |
| `created_at` | Creation timestamp |

Do not paste base64 image payloads into chat. The agent should keep local artifact paths internal unless the user explicitly asks for debugging details.

## Prompting

Good image prompts include:

- Subject and scene.
- Composition, camera, or layout.
- Style, mood, lighting, and color palette.
- Exact text that must appear in the image, quoted.
- Constraints such as "keep the same character" or "preserve the logo".

Example:

```text
A minimal app icon for nanobot: friendly robot head, rounded square, soft blue and white palette, clean vector style, no text
```

For edits, describe what should change and what must stay fixed:

```text
Use the reference image. Keep the same robot and composition, change the palette to warm orange, and add a subtle sunrise background.
```

## Troubleshooting

| Symptom | Check |
|---------|-------|
| `generate_image` is not available | Set `tools.imageGeneration.enabled` to `true` and restart the gateway |
| Missing API key error | Configure `providers.<provider>.apiKey`; if using `${VAR_NAME}`, confirm the environment variable is visible to the gateway process |
| `unsupported image generation provider` | Use `openrouter`, `openai`, `openai_codex`, `custom`, `aihubmix`, `minimax`, `gemini`, `ollama`, `stepfun`, or `zhipu` |
| AIHubMix says `Incorrect model ID` | Use `model: "gpt-image-2-free"`; nanobot expands it to the required `openai/gpt-image-2-free` model path internally |
| Generation times out | Try a smaller/default image size, set AIHubMix `extraBody.quality` to `"low"`, or retry later |
| Reference image rejected | Reference image paths must be inside the workspace or nanobot media directory and must be valid image files |
