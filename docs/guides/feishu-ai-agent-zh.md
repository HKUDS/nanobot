# 使用 nanobot 构建 Feishu AI Agent

本指南通过 `feishu` channel 将 nanobot 连接到 Feishu 或 Lark。该
channel 使用 WebSocket 长连接，因此首次设置不需要公共 webhook URL。

## 本指南构建的内容

- 连接到 nanobot 的 Feishu/Lark bot app
- 在 `config.json` 中启用 `feishu` channel
- 一个通过 pairing 批准的 Feishu 或 Lark 用户
- 首次部署时仅响应提及的群组行为

## 前提条件

- 可正常运行的本地 nanobot 回复：

```bash
nanobot agent -m "Hello!"
```

- 一个可以创建或批准 bot app 的 Feishu 或 Lark 账户。
- 持续运行 `nanobot gateway` 的权限。

## 安装 nanobot

```bash
python -m pip install nanobot-ai
nanobot onboard --wizard
```

## 启用 Feishu channel

安装可选的 channel 依赖：

```bash
nanobot plugins enable feishu
```

最简单的方式是使用 QR 登录：

```bash
nanobot channels login feishu
```

打开打印出的 URL 或扫描 QR code。nanobot 会将生成的 `appId`、
`appSecret`、`domain` 和 `enabled` 字段写入活动配置。

如果 QR 登录不可用，请手动创建 Feishu/Lark app，并将以下结构合并到
`~/.nanobot/config.json`：

```json
{
  "channels": {
    "feishu": {
      "enabled": true,
      "appId": "cli_xxx",
      "appSecret": "xxx",
      "groupPolicy": "mention",
      "streaming": true,
      "domain": "feishu"
    }
  }
}
```

省略 `allowFrom` 会启用仅 pairing 模式。新用户应先向 bot 发送 DM，
获取 pairing code，并在正常使用 bot 前完成批准。

对于手动创建的 app，请启用 Bot capability、接收消息事件和 Long
Connection 模式。如果你的 app 无法获得 `cardkit:card:write` 权限，
请将 `"streaming": false`。

## 运行 nanobot gateway

```bash
nanobot channels status
nanobot gateway
```

## 测试消息

先向 bot 发送 DM。它应该返回一个 pairing code。通过受信任的
本地界面批准：

```bash
nanobot agent -m "/pairing approve ABCD-EFGH"
```

批准后，再次向 bot 发送 DM，或在群聊中提及它：

```text
@nanobot Hello from Feishu
```

## 安全注意事项

- 首次设置时，优先使用仅 pairing 模式。仅在需要静态 allowlist 时添加
  `allowFrom`。
- 在邀请 bot 加入活跃群组前，将 `groupPolicy` 保持为 `"mention"`。
- 对于已部署的服务，通过环境变量存储 app secret。
- 在添加更多用户前，检查 file、shell 和 web tool 的访问权限。

## 故障排除

- 如果 QR 登录不可用，请使用完整 chat-apps 参考中的手动 app 设置。
- 如果 streaming card 失败，请确认 `cardkit:card:write`，或设置
  `"streaming": false`。
- 如果没有收到消息，请检查 Feishu/Lark 事件权限、Long Connection
  模式以及 `nanobot gateway --verbose`。
- 如果首次 DM 返回 pairing code，请先批准它，再测试正常回复。

## 下一步：memory、automations、MCP tools

- [Chat Apps 参考](../chat-apps-zh.md)
- [Pairing](../configuration-zh.md#pairing)
- [AI Agent Memory](ai-agent-memory-zh.md)
- [配置 MCP tools](configure-mcp-tools-zh.md)
