# 如何使用 nanobot 将 AI Agent 连接到聊天应用

nanobot 可以作为自托管聊天机器人或 AI agent 运行在 Telegram、Discord、
Slack、WeChat、Email、Mattermost 及其他聊天应用中。gateway 接收聊天
消息，运行 agent，并将回复发送回同一 channel。

## 你将构建的内容

- 一个可运行的本地 agent
- 一个已启用的聊天 channel
- 一个正在运行的 gateway
- 基于配对的批准流程或精确的静态 allowlist

## 何时使用此方案

当 agent 应该存在于用户已经进行沟通的地方时，请使用聊天应用：
私密 DM、团队 channel、群聊、邮件线程或机器人 workspace。

## 安装

```bash
python -m pip install nanobot-ai
nanobot onboard --wizard
nanobot webui
```

在添加 channel 之前，请先在 WebUI 中发送 `Hello!`。然后为机器人/账户前置条件选择一个平台指南：

- [Telegram AI agent](telegram-ai-agent-zh.md)
- [Discord AI agent](discord-ai-agent-zh.md)
- [Slack AI agent](slack-ai-agent-zh.md)
- [Feishu AI agent](feishu-ai-agent-zh.md)
- [WhatsApp AI agent](whatsapp-ai-agent-zh.md)
- [WeChat AI agent](wechat-ai-agent-zh.md)
- [QQ AI agent](qq-ai-agent-zh.md)
- [Email AI agent](email-ai-agent-zh.md)
- [Mattermost AI agent](mattermost-ai-agent-zh.md)

## 最小可运行示例

使用引导式 channel 设置：

1. 获取平台 token、登录状态、webhook 或邮箱凭据。
2. 在 WebUI 中打开 **设置 → Channels**。
3. 选择平台并打开其设置面板。
4. 完成凭据或 QR 流程，并在提示时安装可选支持。
5. 当 WebUI 请求时重启。
6. 发送一条私密测试消息。
7. 当支持 DM 的 channel 提出请求时，在 WebUI 中批准配对请求。

如果已安装的版本未显示 **设置 → Channels**，请使用完整的[聊天应用参考](../chat-apps-zh.md#manual-setup-pattern)手动配置 channel。

当需要更底层的确认时，可从终端检查状态：

```bash
nanobot channels status
```

`nanobot webui` 命令已运行 gateway。对于仅聊天或服务器部署，请直接启动它：

```bash
nanobot gateway
```

当你直接管理 `config.json` 或需要平台特定的高级设置时，请使用完整的[聊天应用参考](../chat-apps-zh.md)。

## 生产环境注意事项

- 对于始终在线的聊天应用，请将 gateway 作为服务持续运行。
- 在将机器人开放给繁忙的 channel 前，请使用仅提及的群组策略。
- 调试时一次只使用一个 channel。
- 首次测试时优先使用 DM；配对仅在 DM 中有效，群聊还会增加权限和路由行为。

## 安全注意事项

- 优先使用配对或显式 allowlist；除非是在有意创建的 sandbox 中，否则不要使用 `allowFrom: ["*"]`。
- 如果机器人 token 被粘贴到日志或共享文件中，请轮换它们。
- 在邀请其他用户之前，审查文件、shell 和 web tool 访问权限。

## 故障排除

- 如果 `nanobot channels status` 未显示该 channel，则可能缺少 config key 或可选依赖项。
- 如果第一个 DM 返回配对代码，请在 WebUI 中批准待处理请求，或从已获授权的聊天中使用 `/pairing approve <code>`。
- 如果消息未送达，请运行 `nanobot gateway --verbose`，并比较平台凭据、事件权限和 allow list。
- 如果群组回复不符合预期，请检查该 channel 的群组策略。

## 相关 nanobot 文档

- [聊天应用](../chat-apps-zh.md)
- [配置](../configuration-zh.md#channel-settings)
- [配对](../configuration-zh.md#pairing)
- [部署](../deployment-zh.md)
