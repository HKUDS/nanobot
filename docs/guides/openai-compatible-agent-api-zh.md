# 如何使用 nanobot 运行兼容 OpenAI 的 Agent API

nanobot 可以在 `/v1/chat/completions` 后提供本地兼容 OpenAI 的端点。这使现有的 OpenAI 风格客户端能够与使用 tool 的 nanobot agent 通信，而不是直接与原始 model 通信。

## 你将构建的内容

- 一个可运行的 nanobot agent
- 一个位于 `127.0.0.1:8900` 的本地 API server
- 一个 `/v1/chat/completions` 请求
- 使用 `session_id` 进行可选的 session 隔离

## 适用场景

当现有客户端、另一种语言或独立进程已经知道如何调用兼容 OpenAI 的 API 时，请使用此方式。如果你希望在进程内访问 session、memory、runtime helper 和 hook，请使用 Python SDK。

## 安装

```bash
python -m pip install nanobot-ai
nanobot plugins enable api
nanobot onboard --wizard
nanobot agent -m "Hello!"
```

## 最小可运行示例

启动 API server：

```bash
nanobot serve
```

调用 chat endpoint：

```bash
curl http://127.0.0.1:8900/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [{"role": "user", "content": "hi"}],
    "session_id": "demo"
  }'
```

## 生产环境注意事项

- 传递 `session_id` 以隔离用户、任务或工作流。
- 当 `stream` 为 `true` 时，流式传输使用 Server-Sent Events。
- `/v1/models` 报告兼容客户端所需的固定 model 接口。
- 支持通过 JSON base64 或 multipart form data 上传文件。

## 安全注意事项

- 使用本地 `127.0.0.1` 不需要 API key。
- 如果 `api.host` 为 `0.0.0.0` 或 `::`，请在启动前配置 `api.apiKey`。
- 应将 API 视为 agent 访问，而不仅仅是 model 访问：tool 和 workspace 权限仍然很重要。

## 故障排除

- 如果 `/v1/chat/completions` 失败，请先测试 `nanobot agent -m "Hello!"`。
- 如果远程客户端无法连接，请检查 `api.host`、`api.port`、防火墙和 API key 配置。
- 如果 session 相互混合，请传递唯一的 `session_id` 值。

## 相关 nanobot 文档

- [Nanobot 兼容 OpenAI 的 API](../openai-api-zh.md)
- [Python SDK](../python-sdk-zh.md)
- [配置](../configuration-zh.md)
- [部署](../deployment-zh.md)
