# Image Generation

nanobot can generate and edit images through the `generate_image` tool. In the WebUI, users can enable **Image Generation** from the composer, choose an aspect ratio, and keep iterating on generated images inside the same chat.

The feature is disabled by default. Enable it in `~/.nanobot/config.json`, configure a supported image provider, then restart the gateway.

## Quick Setup

OpenRouter example:

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
      "model": "openai/gpt-5.4-image-2",
      "defaultAspectRatio": "1:1",
      "defaultImageSize": "1K"
    }
  }
}
```

AIHubMix example:

```json
{
  "providers": {
    "aihubmix": {
      "apiKey": "${AIHUBMIX_API_KEY}"
    }
  },
  "tools": {
    "imageGeneration": {
      "enabled": true,
      "provider": "aihubmix",
      "model": "gpt-image-2-free",
      "defaultAspectRatio": "1:1",
      "defaultImageSize": "1K"
    }
  }
}
```

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
| `tools.imageGeneration.provider` | string | `"openrouter"` | Image provider name. Currently `openrouter` and `aihubmix` are supported |
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
| `unsupported image generation provider` | Use `openrouter` or `aihubmix` |
| AIHubMix says `Incorrect model ID` | Use `model: "gpt-image-2-free"`; nanobot expands it to the required `openai/gpt-image-2-free` model path internally |
| Generation times out | Try a smaller/default image size, set AIHubMix `extraBody.quality` to `"low"`, or retry later |
| Reference image rejected | Reference image paths must be inside the workspace or nanobot media directory and must be valid image files |

