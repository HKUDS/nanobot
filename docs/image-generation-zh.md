# 图像生成

nanobot 可以通过 `generate_image` tool 生成和编辑图像。在 WebUI Settings 中启用该 tool，然后像平常一样在聊天中请求图像；agent 会决定何时调用它，并且可以在同一对话中持续迭代生成的图像。

此功能默认处于禁用状态。打开 **Settings → Image**，选择已配置的 provider 和 model，启用图像生成，然后保存。运行中的 gateway 会立即应用更改。如果已安装的版本中没有该页面，请使用下面的手动配置。

## 快速设置

**WebUI**

1. 如果尚未配置，请在 **Settings → Models** 下添加图像 provider 凭据。
2. 打开 **Settings → Image**。
3. 选择 provider 和图像 model，然后启用图像生成。
4. 保存并请求生成一张简单的测试图像。如果 gateway 无法实时应用更改，WebUI 会提示你重启它。

**手动配置**

此代码片段使用当前内置的图像生成默认值，因此 JSON 中包含具体名称。这不是对 provider 的推荐；请将 `provider` 和 `model` 替换为你计划使用的任何受支持的图像 provider 和 model。

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

有关 Custom、AIHubMix、MiniMax、Gemini、Ollama、StepFun、Zhipu 和 ModelScope 的配置示例，请参阅 [Provider Notes](#provider-notes)。

> [!TIP]
> API keys 优先使用环境变量。nanobot 会在启动时从环境中解析 `${VAR_NAME}` 值。

## WebUI 使用

1. 打开 Settings，使用已配置的 provider 和 model 启用 **Image Generation**。
2. 在聊天中描述你想要生成或编辑的图像。
3. 如果已配置的默认值不合适，请在请求中包含宽高比或尺寸。
4. 编辑现有图像时附加参考图像。

生成的图像会在聊天中以 assistant 媒体的形式呈现。后续提示词（例如“让它更暖一些”、“更换背景”或“尝试 16:9 版本”）可以复用最近生成的 artifact。

WebUI 会对用户隐藏 provider 存储详情。agent 可以在内部看到已保存的 artifact 路径，并将其作为 `reference_images` 传递给 `generate_image`，以进行迭代编辑。

## 配置参考

| 选项 | 类型 | 默认值 | 描述 |
|--------|------|---------|-------------|
| `tools.imageGeneration.enabled` | boolean | `false` | 注册 `generate_image` tool |
| `tools.imageGeneration.provider` | string | `"openrouter"` | 当前内置的图像 provider 默认值。支持的值：`openrouter`、`openai`、`openai_codex`、`custom`、`aihubmix`、`minimax`、`gemini`、`ollama`、`stepfun`、`zhipu`、`modelscope` |
| `tools.imageGeneration.model` | string | `"openai/gpt-5.4-image-2"` | provider model 名称 |
| `tools.imageGeneration.defaultAspectRatio` | string | `"1:1"` | 当提示词或 tool call 未指定宽高比时使用的默认比例 |
| `tools.imageGeneration.defaultImageSize` | string | `"1K"` | 默认尺寸提示，例如 `1K`、`2K`、`4K` 或 `1024x1024` |
| `tools.imageGeneration.maxImagesPerTurn` | number | `4` | 一次 tool call 接受的最大 `count` 值。有效范围：`1` 到 `8` |
| `tools.imageGeneration.saveDir` | string | `"generated"` | 用于保存生成 artifact 的 nanobot 媒体目录下的相对目录 |

Provider 设置复用常规 provider 配置字段：

| 选项 | 描述 |
|--------|-------------|
| `providers.<name>.apiKey` | Provider API key。优先使用 `${ENV_VAR}` |
| `providers.<name>.apiBase` | 可选的自定义基础 URL |
| `providers.<name>.extraHeaders` | 合并到 provider 请求中的 headers |
| `providers.<name>.extraBody` | 合并到 provider 请求 body 中的额外 JSON 字段 |
| `providers.<name>.proxy` | 用于 provider 请求和下载返回的图像 URL 的显式可信 HTTP proxy |

对于返回图像 URL 的 provider，直接下载使用 DNS pinning。当配置了显式 provider `proxy` 时，nanobot 会在初始 URL 和每次重定向时拒绝格式错误的 URL，以及在本地可识别为私有/内部目标的 URL。本地 DNS 无法解析的主机名会交由该可信 proxy 处理，由它负责最终的 DNS 解析和网络出口。这些下载不会使用进程级 proxy 环境变量。

camelCase 和 snake_case 配置 keys 均可接受，但文档使用 camelCase，以匹配 `config.json`。

## Provider 说明

### OpenRouter

OpenRouter 使用 chat-completions 风格的图像响应。配置如下：

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

如果需要参考图像编辑，请使用支持图像生成和图像编辑的 model。

### Custom（OpenAI 兼容）

`custom` 图像 provider 适用于实现同步 OpenAI Images API 的服务：

```text
POST /v1/images/generations
```

响应必须在 `data[].b64_json` 或 `data[].url` 中包含生成的图像。原生 prediction API（例如 Replicate 的 `/v1/models/{owner}/{model}/predictions`）并不直接兼容，除非在其前面部署 OpenAI 兼容的 gateway。

配置如下：

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

必须配置 `apiBase`。provider 会使用 OpenAI Images API 格式，并以 `response_format: "b64_json"` 向 `{apiBase}/images/generations` 发送请求。对于本地或无需身份验证的 endpoint，`apiKey` 可选。通用 `custom` provider 不支持参考图像编辑。

由于 `extraBody` 会在最后合并到请求 body 中，因此可以使用它适配 provider 特有的差异。例如：

- Agnes AI 文档说明使用 URL 响应，因此使用 `"extraBody": {"response_format": "url"}`。
- Together AI 文档说明使用 `"response_format": "base64"`，因此请覆盖默认值。
- Volcengine Ark Seedream model 可能要求使用 `"2K"`、`"3K"`、`"4K"` 等尺寸提示或明确的尺寸。请将 `tools.imageGeneration.defaultImageSize` 或 `providers.custom.extraBody.size` 设置为所选 model 支持的值。

为了兼容 nanobot 的默认设置，custom 会将 `defaultImageSize: "1K"` 映射为 `1024x1024`。其他明确的尺寸提示会原样传递。

### AIHubMix

AIHubMix `gpt-image-2-free` 通过 AIHubMix 的统一 predictions API 提供支持。nanobot 在内部调用：

```text
/v1/models/openai/gpt-image-2-free/predictions
```

配置如下：

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

`quality: low` 是可选的。它可以让免费图像 model 运行更快并降低超时概率，但不是正确运行所必需的。

### MiniMax

MiniMax `image-01` 支持文生图和参考图像（主体参考）编辑。支持的宽高比包括 `1:1`、`16:9`、`4:3`、`3:2`、`2:3`、`3:4`、`9:16` 和 `21:9`。

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

nanobot 通过 Google 的 Generative Language API 支持两类 Gemini 图像生成 model：

| Model | Endpoint | 参考图像 |
|-------|----------|---------|
| `imagen-4.0-generate-001` | `:predict` | 此集成不支持 |
| `gemini-2.5-flash-image` | `:generateContent` | 支持 |

如需参考图像编辑，请使用 Gemini Flash 图像 model：

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

Imagen 4 支持 `1:1`、`9:16`、`16:9`、`3:4` 和 `4:3` 宽高比。不支持的比例会被忽略，model 会使用其默认值。`defaultImageSize` 设置对 Gemini model 没有影响；尺寸仅由 `defaultAspectRatio` 控制。与 Imagen model 一起传递的参考图像会被忽略（并记录警告）。

### Ollama

Ollama 的实验性原生图像生成 API 可与本地服务器和托管的 ollama.com model 配合使用。在 `http://localhost:11434/api` 上进行本地访问不需要 API key；只有在目标为 `https://ollama.com/api` 时才设置 `providers.ollama.apiKey`。

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

Ollama 会将 `defaultAspectRatio` 和 `defaultImageSize` 映射为原生的 `width` 和 `height` 值。此集成不支持参考图像。

### StepFun

StepFun（阶跃星辰）`step-image-edit-2` 支持文生图。`step-1x-medium` 变体还支持**风格参考**图像编辑，即使用参考图像引导输出的视觉风格。

支持的宽高比：`1:1`、`16:9`、`9:16`、`3:4`、`4:3`。尺寸以 `WIDTHxHEIGHT` 指定（例如 `1024x1024`、`1280x800`、`800x1280`）。

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
> StepFun provider 复用现有的 `providers.stepfun` 配置块（与 StepFun 的 LLM API 使用同一个配置块）。只需设置一次 `providers.stepfun.apiKey`，文本和图像生成即可共享该设置。
>
> 使用 `step-image-edit-2` 时，`reference_images` 会被忽略（该 model 不支持风格参考）。切换到 `step-1x-medium` 即可使用参考图像引导生成。

#### StepPlan（订阅）

StepPlan 是 StepFun 的订阅层级，使用不同的 API 基础 URL。图像生成 endpoint 路径相同，只需覆盖 `apiBase`：

```json
{
  "providers": {
    "stepfun": {
      "apiKey": "${STEPFUN_API_KEY}",
      "apiBase": "https://api.stepfun.ai/step_plan/v1"
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

`apiBase` 的优先级高于 registry 默认值，因此配置 StepPlan 基础 URL 后，图像请求会发送到 `https://api.stepfun.ai/step_plan/v1/images/generations`，这是 LLM 调用使用的同一路径前缀。API key 与标准 StepFun provider 共享。

### Zhipu

Zhipu（智谱）的 `glm-image` model 支持文生图。API 返回临时图像 URL（有效期为 30 天）；nanobot 会下载这些 URL，并将其重新编码为 base64 data URL。

支持的宽高比：`1:1`、`16:9`、`9:16`、`3:4`、`4:3`。尺寸可以指定为 `WIDTHxHEIGHT`（例如 `1280x1280`、`1728x960`），也可以使用宽高比预设值。

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

其他受支持的 model：`cogview-4`、`cogview-4-250304`、`cogview-3-flash`。此集成不支持参考图像。
### ModelScope

ModelScope（魔搭社区）API-Inference 支持通过异步任务模式进行文生图和图像编辑。

支持的宽高比：`1:1`、`16:9`、`9:16`、`3:4`、`4:3`。尺寸可以指定为 `WIDTHxHEIGHT`（例如 `1024x1024`、`1664x928`），也可以使用宽高比预设。

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

## 生成产物

生成的图像存储在当前 nanobot 实例的媒体目录下：

```text
~/.nanobot/media/generated/YYYY-MM-DD/img_<id>.<ext>
~/.nanobot/media/generated/YYYY-MM-DD/img_<id>.json
```

对于非默认配置位置，媒体目录相对于当前配置文件所在的目录。

JSON sidecar 文件包含：

| 字段 | 含义 |
|-------|---------|
| `id` | 简短的生成图像 ID，例如 `img_ab12cd34ef56` |
| `path` | 内部用于后续编辑的本地图像路径 |
| `mime` | 检测到的图像 MIME 类型 |
| `prompt` | 用于生成的提示词 |
| `model` | provider model |
| `provider` | provider 名称 |
| `source_images` | 用于编辑的参考图像路径 |
| `created_at` | 创建时间戳 |

不要将 base64 图像负载粘贴到聊天中。除非用户明确要求调试详情，否则 agent 应将本地产物路径保留为内部信息。

## 提示词编写

好的图像提示词包括：

- 主体和场景。
- 构图、相机或布局。
- 风格、氛围、光照和配色方案。
- 必须出现在图像中的确切文本，并使用引号括起。
- “保持相同角色”或“保留 logo”等约束条件。

示例：

```text
A minimal app icon for nanobot: friendly robot head, rounded square, soft blue and white palette, clean vector style, no text
```

对于编辑，请描述需要更改的内容以及必须保持不变的内容：

```text
Use the reference image. Keep the same robot and composition, change the palette to warm orange, and add a subtle sunrise background.
```

## 故障排除

| 症状 | 检查项 |
|---------|-------|
| `generate_image` 不可用 | 在 **设置 → 图像** 中启用图像生成并保存。对于手动配置更改，请重启 gateway |
| API key 缺失错误 | 配置 `providers.<provider>.apiKey`；如果使用 `${VAR_NAME}`，请确认 gateway 进程可以访问该环境变量 |
| `unsupported image generation provider` | 使用 `openrouter`、`openai`、`openai_codex`、`custom`、`aihubmix`、`minimax`、`gemini`、`ollama`、`stepfun`、`zhipu` 或 `modelscope` |
| AIHubMix 提示 `Incorrect model ID` | 使用 `model: "gpt-image-2-free"`；nanobot 会在内部将其扩展为所需的 `openai/gpt-image-2-free` model 路径 |
| 生成超时 | 尝试较小的默认图像尺寸，将 AIHubMix 的 `extraBody.quality` 设置为 `"low"`，或稍后重试 |
| 参考图像被拒绝 | 参考图像路径必须位于 workspace 或 nanobot 媒体目录内，并且必须是有效的图像文件 |
