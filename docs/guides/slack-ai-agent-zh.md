# 使用 nanobot 构建 Slack AI Agent

本指南通过 Socket Mode 将 nanobot 连接到 Slack。首次完成设置无需公共 webhook URL。

## 本指南构建的内容

- 启用 Socket Mode 的 Slack app
- bot token 和 app-level token
- 在 nanobot 中启用 `slack` channel
- 来自已批准 Slack 用户的 DM 配对流程和提及测试

## 前提条件

- nanobot 能正常回复：

```bash
nanobot agent -m "Hello!"
```

- 有权在 workspace 中创建 Slack app。

## 安装 nanobot

```bash
python -m pip install nanobot-ai
nanobot onboard --wizard
```

## 启用 Slack channel

安装可选的 channel 依赖：

```bash
nanobot plugins enable slack
```

在 Slack 中创建 app，启用 Socket Mode，创建具有
`connections:write` 权限的 app-level token，添加 bot scopes，订阅 bot events，然后将
app 安装到 workspace。

将此代码片段合并到 `~/.nanobot/config.json`：

```json
{
  "channels": {
    "slack": {
      "enabled": true,
      "botToken": "xoxb-...",
      "appToken": "xapp-...",
      "groupPolicy": "mention",
      "dm": {
        "policy": "allowlist"
      }
    }
  }
}
```

Slack DMs 默认处于开放状态。将 `dm.policy` 设置为 `"allowlist"`，且不配置
`dm.allowFrom` 条目时，新的 DM 发送者会收到配对代码。正常使用 bot 前请先批准该代码。

## 运行 nanobot gateway

```bash
nanobot channels status
nanobot gateway
```

## 测试消息

直接向 Slack bot 发送 DM。它应返回一个配对代码。通过受信任的本地界面批准该代码：

```bash
nanobot agent -m "/pairing approve ABCD-EFGH"
```

然后再次向 bot 发送 DM，或在 channel 中提及它：

```text
@nanobot Hello from Slack
```

## 安全说明

- 除非明确希望 bot 监听每条 channel 消息，否则保持 `groupPolicy` 为 `mention`。
- 需要基于配对的批准时，保持 `dm.policy` 为 `"allowlist"`。
- 在 allowlist 模式下使用 `groupAllowFrom` 配置已批准的 channel。
- 更改 scopes 后重新安装 Slack app。
- 不要将 bot 和 app token 放入已提交的配置文件中。

## 故障排除

- 如果 Socket Mode 失败，请确认 app-level token 以 `xapp-` 开头。
- 如果 bot 无法发送文件，请添加 `files:write`，重新安装 app，然后重启 nanobot。
- 如果 DM 无需配对即可正常回复，请检查 `dm.policy` 是否为
  `"allowlist"`。
- 如果忽略 channel 消息，请检查 event subscriptions 和 group policy。

## 下一步：memory、automations、MCP tools

- [Chat Apps 参考](../chat-apps-zh.md)
- [配置 web search](configure-web-search-zh.md)
- [长时间运行的 AI Agent](long-running-ai-agent-zh.md)
- [Deployment](../deployment-zh.md)
