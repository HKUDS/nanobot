# 使用 nanobot 构建 WeChat AI Agent

本指南通过 `weixin` channel 将 nanobot 连接到 WeChat。该 channel 通过受支持的上游 API，使用带二维码登录的 HTTP 长轮询。

## 本指南构建的内容

- 在 nanobot 中启用 `weixin` channel
- 一个二维码登录 session
- 一个通过配对批准的 WeChat 发送者
- 一个用于传递消息的运行中 gateway

## 前提条件

- 可正常运行的本地 nanobot 回复：

```bash
nanobot agent -m "Hello!"
```

- 一个可以完成二维码登录的 WeChat 账户。

## 安装 nanobot

```bash
python -m pip install nanobot-ai
nanobot onboard --wizard
```

## 启用 WeChat channel

安装可选的 channel 依赖：

```bash
nanobot plugins enable weixin
```

将此代码片段合并到 `~/.nanobot/config.json`：

```json
{
  "channels": {
    "weixin": {
      "enabled": true
    }
  }
}
```

省略 `allowFrom` 会启用仅配对模式。来自新发送者的第一条私人 WeChat 消息会收到配对代码，而不是获得 agent 访问权限。

登录：

```bash
nanobot channels login weixin
```

如果需要丢弃已保存的登录状态并重新进行身份验证，请使用 `--force`。

## 运行 nanobot gateway

```bash
nanobot channels status
nanobot gateway
```

## 测试消息

向 bot 发送一条私人 WeChat 消息。它应该回复一个配对代码。从受信任的本地界面批准该代码：

```bash
nanobot agent -m "/pairing approve ABCD-EFGH"
```

批准后再次发送该消息，并查看 gateway 日志中的发送者 ID 和回复。

## 安全注意事项

- 首次设置时优先使用仅配对模式。仅在需要静态 allowlist 时添加 `allowFrom`。
- 将已保存的登录状态视为敏感的账户访问凭据。
- 避免将个人账户连接到不受信任的 workspace 或授予过于宽泛的 tool 权限。

## 故障排除

- 如果登录失败，请重新运行 `nanobot channels login weixin --force`。
- 如果第一条私人消息返回配对代码，这是预期行为。在测试正常的 agent 回复前批准该代码。
- 如果消息在没有配对代码的情况下被拒绝，请检查 gateway 日志，确认 WeChat 是否提供了 nanobot 回复所需的上下文令牌。
- 如果轮询断开，请重启 gateway，并检查到上游服务的网络可达性。

## 下一步：memory、自动化和 MCP tools

- [Chat Apps 参考](../chat-apps-zh.md)
- [AI Agent Memory](ai-agent-memory-zh.md)
- [安全的本地 AI agent](secure-local-ai-agent-zh.md)
- [部署](../deployment-zh.md)
