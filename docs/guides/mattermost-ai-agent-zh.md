# 使用 nanobot 构建 Mattermost AI Agent

本指南通过内置的 Mattermost channel 将 nanobot 连接到 Mattermost，使用 WebSocket 事件和 Mattermost REST API。

## 本指南构建的内容

- 一个 Mattermost bot 账户或令牌
- 在 nanobot 中启用的 `mattermost` channel
- 首次部署时仅响应提及的群组行为
- 一个通过配对批准的私信或提及测试

## 前提条件

- 可正常运行的本地 nanobot 回复：

```bash
nanobot agent -m "Hello!"
```

- Mattermost 服务器 URL。
- bot 账户的 bot 令牌或个人访问令牌。

## 安装 nanobot

```bash
python -m pip install nanobot-ai
nanobot onboard --wizard
```

## 启用 Mattermost channel

将此代码片段合并到 `~/.nanobot/config.json`：

```json
{
  "channels": {
    "mattermost": {
      "enabled": true,
      "serverUrl": "https://mattermost.example.com",
      "token": "YOUR_MATTERMOST_TOKEN",
      "teamId": "YOUR_TEAM_ID",
      "groupPolicy": "mention",
      "groupPolicyInThread": "open",
      "replyInThread": true,
      "dm": {
        "policy": "allowlist"
      }
    }
  }
}
```

`teamId` 将 channel 限定在某个 Mattermost 团队中。首次测试时，将
`groupPolicy` 保持为 `mention`。`groupPolicyInThread` 可以是 `"mention"`、
`"open"` 或 `"allowlist"`，用于控制在线程内回复的消息。如果省略该配置，
它会继承 `groupPolicy`，从而保留现有配置的行为。当线程中的后续消息不应
要求再次使用 @mention 时，将其显式设置为 `"open"`。

当 `groupPolicy` 为 `"allowlist"` 时，`groupAllowFrom` 仍是根帖子和线程回复的外层
channel 边界。线程策略无法开放不在该允许列表中的 channel。

Mattermost 私信默认处于开放状态。将 `dm.policy` 设置为 `"allowlist"` 且不添加
任何 `dm.allowFrom` 条目时，新私信发送者会收到配对代码。正常使用 bot 前，请批准
该代码。

## 运行 nanobot 网关

```bash
nanobot channels status
nanobot gateway
```

## 测试消息

向 bot 账户发送私信。它应返回配对代码。请从受信任的本地界面批准该代码：

```bash
nanobot agent -m "/pairing approve ABCD-EFGH"
```

然后再次向 bot 发送私信，或在 bot 有权访问的 channel 中提及它：

```text
@nanobot Hello from Mattermost
```

## 安全注意事项

- 对于已部署的服务，请将 Mattermost 令牌存储在环境变量中。
- 需要基于配对进行批准时，将 `dm.policy` 保持为 `"allowlist"`。
- 在向繁忙的 channel 开放 bot 之前，使用仅响应提及的群组行为。
- 在授予广泛的 channel 访问权限之前，检查文件和 shell 工具。

## 故障排除

- 如果启动日志显示 `serverUrl and token must be configured`，请检查
  camelCase 配置键。
- 如果私信被忽略，请检查 `dm` 策略和配对批准状态。
- 如果 channel 消息被忽略，请确认 bot 被提及，并且属于相应的团队/channel。
- 如果线程回复不符合预期，请检查 `groupPolicyInThread`、
  `replyInThread` 和 `includeThreadContext`。

## 下一步：memory、自动化、MCP 工具

- [Chat Apps 参考](../chat-apps-zh.md)
- [配对](../configuration-zh.md#pairing)
- [长时间运行的 AI Agent](long-running-ai-agent-zh.md)
- [部署](../deployment-zh.md)
