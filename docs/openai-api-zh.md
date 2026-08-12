# Nanobot OpenAI 兼容 API：在 /v1/chat/completions 后运行本地 Agent

nanobot 可以为本地集成提供一个精简的 OpenAI 兼容端点：

```bash
nanobot plugins enable api
nanobot agent -m "Hello!"
nanobot serve
```

先运行 CLI 检查。如果 `nanobot agent -m "Hello!"` 失败，请先修复 provider 或配置设置，然后再调试 API 服务器。默认情况下，API 绑定到 `127.0.0.1:8900`。你可以在 `config.json` 中更改此设置。

有关设置帮助，请参阅 [`quick-start.md`](quick-start-zh.md)、[`providers.md`](providers-zh.md) 和 [`troubleshooting.md`](troubleshooting-zh.md)。

## 身份验证

仅限本地的 `127.0.0.1` 使用不需要 API 密钥。如果使用 `api.host: "0.0.0.0"` 或 `"::"` 将 API 服务器绑定到所有接口，nanobot 要求设置 `api.apiKey`；否则启动将失败，以避免在网络上暴露未经身份验证的 Agent 端点。

```json
{
  "api": {
    "host": "0.0.0.0",
    "port": 8900,
    "apiKey": "${NANOBOT_API_KEY}"
  }
}
```

设置 `api.apiKey` 后，请在 API 路由上将其作为 Bearer token 发送。健康检查端点仍无需身份验证，因此本地探针和负载均衡器仍可检查进程健康状况。

```bash
curl http://127.0.0.1:8900/v1/models \
  -H "Authorization: Bearer $NANOBOT_API_KEY"
```

## 行为

- 会话隔离：在请求正文中传递 `"session_id"` 以隔离对话；省略该参数则使用共享的默认会话（`api:default`）
- 单消息输入：每个请求必须恰好包含一条 `user` 消息
- 固定 model：省略 `model`，或传递 `/v1/models` 显示的相同 model
- 流式传输：设置 `stream=true` 以接收带有 OpenAI 兼容增量块的服务器发送事件（`text/event-stream`），以 `data: [DONE]` 结束；省略 `stream` 或将其设置为 `stream=false` 可获得单个 JSON 响应
- **文件上传**：通过 JSON base64 或 `multipart/form-data` 支持图像、PDF、Word（.docx）、Excel（.xlsx）、PowerPoint（.pptx）（每个文件最大 10MB）
- API 请求在合成的 `api` channel 中运行，因此 `message` tool **不会**自动发送到 Telegram/Discord 等平台。若要主动发送到其他聊天，请为启用的 channel 调用 `message`，并明确指定 `channel` 和 `chat_id`。

从 API session 跨 channel 发送的 tool 调用示例：

```json
{
  "content": "Build finished successfully.",
  "channel": "telegram",
  "chat_id": "123456789"
}
```

如果 `channel` 指向配置中未启用的 channel，nanobot 会将出站事件加入队列，但不会进行平台发送。

## 端点

- `GET /health`
- `GET /v1/models`
- `POST /v1/chat/completions`

## curl

```bash
curl http://127.0.0.1:8900/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [{"role": "user", "content": "hi"}],
    "session_id": "my-session"
  }'
```

## 文件上传（JSON base64）

使用 OpenAI 多模态内容格式内联发送图像：

```bash
curl http://127.0.0.1:8900/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [{"role": "user", "content": [
      {"type": "text", "text": "Describe this image"},
      {"type": "image_url", "image_url": {"url": "data:image/png;base64,iVBOR..."}}
    ]}]
  }'
```

## 文件上传（multipart/form-data）

通过 multipart 上传任何受支持的文件类型（图像、PDF、Word、Excel、PPT）：

```bash
# Single file
curl http://127.0.0.1:8900/v1/chat/completions \
  -F "message=Summarize this report" \
  -F "files=@report.docx"

# Multiple files with session isolation
curl http://127.0.0.1:8900/v1/chat/completions \
  -F "message=Compare these files" \
  -F "files=@chart.png" \
  -F "files=@data.xlsx" \
  -F "session_id=my-session"
```

支持的文件类型：
- **图像**：PNG、JPEG、GIF、WebP（以 base64 形式发送给 AI 进行视觉分析）
- **文档**：PDF、Word（.docx）、Excel（.xlsx）、PowerPoint（.pptx）（提取文本后发送给 AI）
- **文本**：TXT、Markdown、CSV、JSON 等（直接读取）

## Python（`requests`）

```python
import requests

resp = requests.post(
    "http://127.0.0.1:8900/v1/chat/completions",
    json={
        "messages": [{"role": "user", "content": "hi"}],
        "session_id": "my-session",  # optional: isolate conversation
    },
    timeout=120,
)
resp.raise_for_status()
print(resp.json()["choices"][0]["message"]["content"])
```

## Python（`openai`）

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://127.0.0.1:8900/v1",
    api_key="dummy",
)

resp = client.chat.completions.create(
    model="MiniMax-M2.7",
    messages=[{"role": "user", "content": "hi"}],
    extra_body={"session_id": "my-session"},  # optional: isolate conversation
)
print(resp.choices[0].message.content)
```
