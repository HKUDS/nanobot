# 自托管 AI Agent 的聊天应用

将 nanobot 连接到 Telegram、Discord、Slack、WeChat、Email、Mattermost 和
其他聊天平台。本页面是完整的聊天渠道参考。如果你希望获得针对某个平台的
设置路径，请从指南开始：

| 平台 | 指南 |
|---|---|
| Telegram | [使用 nanobot 构建 Telegram AI Agent](guides/telegram-ai-agent-zh.md) |
| Discord | [使用 nanobot 构建 Discord AI Agent](guides/discord-ai-agent-zh.md) |
| Slack | [使用 nanobot 构建 Slack AI Agent](guides/slack-ai-agent-zh.md) |
| Feishu | [使用 nanobot 构建 Feishu AI Agent](guides/feishu-ai-agent-zh.md) |
| WhatsApp | [使用 nanobot 构建 WhatsApp AI Agent](guides/whatsapp-ai-agent-zh.md) |
| WeChat | [使用 nanobot 构建 WeChat AI Agent](guides/wechat-ai-agent-zh.md) |
| QQ | [使用 nanobot 构建 QQ AI Agent](guides/qq-ai-agent-zh.md) |
| Email | [使用 nanobot 构建 Email AI Agent](guides/email-ai-agent-zh.md) |
| Mattermost | [使用 nanobot 构建 Mattermost AI Agent](guides/mattermost-ai-agent-zh.md) |

想要构建自己的渠道？请参阅[渠道包指南](channel-package-guide-zh.md)。

在配置聊天应用之前，请确保本地 CLI 路径可用：

```bash
nanobot agent -m "Hello!"
```

如果失败，请先根据 [`quick-start.md`](quick-start-zh.md)、[`providers.md`](providers-zh.md) 和 [`troubleshooting.md`](troubleshooting-zh.md) 修复安装、配置、提供商或模型设置。配置渠道后，聊天应用要求 `nanobot gateway` 持续运行。

## WebUI 中的推荐设置

对于常规本地设置，请让 WebUI 写入并验证渠道配置：

1. 运行 `nanobot webui`。
2. 打开 **设置 → 渠道**。
3. 搜索平台并打开其设置面板。
4. 按照凭据字段或 QR 流程操作。屏幕会告诉你它需要哪种平台侧令牌、权限、账户或 URL。
5. 出现提示时，让 nanobot 安装可选渠道支持。
6. 如果 WebUI 报告需要重启，请从 WebUI 重启。
7. 发送私密测试消息。如果渠道返回配对码，请在 WebUI 中批准待处理请求，然后再次发送消息。

如果已安装的稳定版本未显示 **设置 → 渠道**，请继续使用下方的[手动设置模式](#manual-setup-pattern)，或安装当前源码。

默认情况下，可选包安装可供同一台机器上的 WebUI 使用。除非管理员明确启用该功能，否则远程浏览器客户端无法更改 Python 环境。引导式安装不可用时，请在本地运行 `nanobot plugins enable <channel>`。

以下各节说明每个聊天平台的要求，并为直接管理 `config.json` 的部署提供手动配置。

> [!NOTE]
> 如果你正从默认安装聊天应用 SDK 的版本升级，
> 请在同一 Python 环境中启用渠道，以便 nanobot 安装其
> 清单声明的依赖项：
>
> ```bash
> nanobot plugins enable <channel>
> ```
>
> 将 `<channel>` 替换为 `telegram`、`slack`、`feishu`、
> `dingtalk`、`matrix`、`qq`、`napcat`、`weixin`、`wecom` 或 `msteams`
> 等名称。若要稍后关闭渠道，请运行 `nanobot plugins disable <channel>`。
> nanobot 会保留已保存的设置，但会在下次重启后停止加载该渠道。

## 手动设置模式

以下大多数示例都是要合并到 `~/.nanobot/config.json` 的片段。当片段包含 `allowFrom` 时，它展示的是静态允许列表。对于受支持渠道上的基于配对访问，请省略 `allowFrom`；Slack 和 Mattermost 还需要将 `dm.policy` 设为 `"allowlist"`，才能让私信发出配对码。

每个聊天应用都采用相同流程：

1. 在聊天平台中创建或准备机器人/账户。
2. 复制该平台提供的令牌、密钥、QR 登录状态、webhook URL 或账户 ID。
3. 将该平台的 JSON 片段合并到 `~/.nanobot/config.json`。
4. 对支持私信的渠道优先使用配对：省略 `allowFrom`，让第一条私信收到配对码，然后使用 `/pairing approve <code>` 批准它。
5. 对于不支持配对的渠道，例如 Email，请使用 `allowFrom` 或平台专属允许列表来严格限制访问。
6. 检查 nanobot 是否可以看到已配置的渠道：

```bash
nanobot channels status
```

7. 启动网关并保持该终端运行：

```bash
nanobot gateway
```

8. 发送测试私信。如果机器人返回配对码，请批准它并再次发送消息。在群聊中，请遵循该渠道的 `groupPolicy` 行为：许多渠道默认仅在被提及时回复，而 Matrix 和 WhatsApp 默认开放群组回复。

如果 `nanobot channels status` 未将渠道显示为已启用，则配置片段位置错误、渠道名称拼写错误，或者你编辑的配置文件不是 nanobot 正在读取的文件。如果渠道已启用但消息未到达，请运行 `nanobot gateway --verbose`，并对照平台侧凭据、事件权限和允许列表。

> `allowFrom: ["*"]` 会绕过配对，并允许任何能访问该渠道的人与机器人交谈。仅在你有意这样做时使用，或在私密沙盒中测试时临时使用。

| 渠道 | 所需内容 |
|---------|---------------|
| **Telegram** | 来自 @BotFather 的机器人令牌 |
| **Discord** | 机器人令牌 + Message Content intent |
| **WhatsApp** | 扫描 QR 码（`nanobot channels login whatsapp`） |
| **WeChat (Weixin)** | 扫描 QR 码（`nanobot channels login weixin`） |
| **Feishu** | 扫描 QR 码（`nanobot channels login feishu`）或 App ID + App Secret |
| **DingTalk** | App Key + App Secret |
| **Slack** | 机器人令牌 + App-Level 令牌 |
| **Matrix** | Homeserver URL + Access token |
| **Email** | IMAP/SMTP 凭据 |
| **QQ** | App ID + App Secret |
| **Napcat (QQ)** | Napcat Forward WebSocket URL + 访问令牌 |
| **Wecom** | Bot ID + Bot Secret |
| **Microsoft Teams** | App ID + App Password + 公共 HTTPS 端点 |
| **Mochat** | Claw 令牌（可自动设置） |
| **Signal** | signal-cli daemon + 电话号码 |

<details>
<summary><b>Telegram</b></summary>

**推荐的 WebUI 设置**

1. 使用 `@BotFather` 创建机器人并复制其令牌。
2. 运行 `nanobot webui`，然后打开 **设置 → 渠道 → Telegram**。
3. 粘贴令牌。如果网关无法直接访问 Telegram，请展开
   **高级**并添加 HTTP 或 SOCKS 代理。
4. 保存并启用 Telegram，然后向机器人发送私信。

配置徽标表示 nanobot 找到了已保存的令牌。实时连接
检查是独立的，因此临时的 Telegram 或代理故障不会使
现有配置消失。已保存的令牌和代理 URL 会保持掩码状态。

有关配对和故障排除，请参阅[分步 Telegram 指南](guides/telegram-ai-agent-zh.md)。

**手动设置**

安装可选渠道依赖项：

```bash
nanobot plugins enable telegram
```

**1. 创建机器人**
- 打开 Telegram，搜索 `@BotFather`
- 发送 `/newbot`，按照提示操作
- 复制令牌

**2. 配置**

```json
{
  "channels": {
    "telegram": {
      "enabled": true,
      "token": "YOUR_BOT_TOKEN",
      "allowFrom": ["YOUR_USER_ID"]
    }
  }
}
```

如果网关无法直接访问 Telegram，请在同一部分添加代理：

```json
{
  "channels": {
    "telegram": {
      "proxy": "http://127.0.0.1:7890"
    }
  }
}
```

支持 HTTP、HTTPS、SOCKS5 和 SOCKS5H 代理 URL。将包含用户名或密码的代理 URL
视为密钥。

> 你可以在 Telegram 设置中找到你的 **User ID**。它显示为 `@yourUserId`。请复制此值，**不要包含 `@` 符号**，然后将其粘贴到配置文件中。
>
> `richMessages` 默认为 `false`。仅当你的 Telegram 客户端支持 Bot API 10.1 富消息并且你希望获得更丰富的 markdown 渲染时，才将其设置为 `true`；Telegram Web 可能会为富消息显示不支持消息错误，因此请保持禁用。


**3. 运行**

```bash
nanobot gateway
```

**Webhook 模式（可选）**

Telegram 默认使用长轮询。若要通过 webhook 接收更新，请暴露一个将请求转发到 nanobot 本地监听器的公共 HTTPS URL，并将 `mode` 设置为 `webhook`：

```json
{
  "channels": {
    "telegram": {
      "enabled": true,
      "token": "YOUR_BOT_TOKEN",
      "mode": "webhook",
      "webhookUrl": "https://example.com/telegram",
      "webhookListenHost": "127.0.0.1",
      "webhookListenPort": 8081,
      "webhookPath": "/telegram",
      "webhookSecretToken": "CHANGE_ME_RANDOM_SECRET",
      "webhookMaxConnections": 4,
      "allowFrom": ["YOUR_USER_ID"]
    }
  }
}
```

> 在 webhook 模式下，`webhookSecretToken` 是必需的。不要在没有反向代理或隧道的情况下，将本地 webhook 监听器直接暴露到公共互联网。TLS/Host 策略由你的代理处理；nanobot 仅监听 `webhookListenHost:webhookListenPort`，并验证 Telegram 的 webhook 密钥令牌。`webhookMaxConnections` 默认为 `4`；在将 Telegram 更新转发给 agent 前，nanobot 仍会按会话串行处理它们。
>
> `webhookUrl` 是向 Telegram 注册的公共 HTTPS URL。`webhookPath` 是 nanobot 监听的本地路径。它们通常使用相同路径，但当反向代理或隧道重写请求路径时可能不同。

</details>

<details>
<summary><b>Mochat (Claw IM)</b></summary>

默认使用 **Socket.IO WebSocket**，并在失败时回退到 HTTP 轮询。

**安装可选实时依赖项**

```bash
nanobot plugins enable mochat
```

没有这些依赖项时，Mochat 仍可通过 HTTP 轮询运行。

**1. 让 nanobot 为你设置 Mochat**

只需向 nanobot 发送以下消息（将 `xxx@xxx` 替换为你的真实邮箱）：

```
Read https://raw.githubusercontent.com/HKUDS/MoChat/refs/heads/main/skills/nanobot/skill.md and register on MoChat. My Email account is xxx@xxx Bind me as your owner and DM me on MoChat.
```

nanobot 将自动注册、配置 `~/.nanobot/config.json` 并连接到 Mochat。

**2. 重启网关**

```bash
nanobot gateway
```

就是这样，nanobot 会处理其余事项！

<br>

<details>
<summary>手动配置（高级）</summary>

如果你希望手动配置，请将以下内容添加到 `~/.nanobot/config.json`：

> 请保持 `claw_token` 私密。它仅应通过 `X-Claw-Token` header 发送到你的 Mochat API 端点。

```json
{
  "channels": {
    "mochat": {
      "enabled": true,
      "base_url": "https://mochat.io",
      "socket_url": "https://mochat.io",
      "socket_path": "/socket.io",
      "claw_token": "claw_xxx",
      "agent_user_id": "6982abcdef",
      "sessions": ["*"],
      "panels": ["*"],
      "reply_delay_mode": "non-mention",
      "reply_delay_ms": 120000
    }
  }
}
```



</details>

</details>

<details>
<summary><b>Discord</b></summary>

**1. 创建机器人**
- 前往 https://discord.com/developers/applications
- 创建应用程序 → Bot → Add Bot
- 复制机器人令牌

**2. 启用 intents**
- 在 Bot 设置中，启用 **MESSAGE CONTENT INTENT**
- （可选）如果你计划使用基于成员数据的允许列表，请启用 **SERVER MEMBERS INTENT**

**3. 获取你的 User ID**
- Discord 设置 → 高级 → 启用 **Developer Mode**
- 右键点击你的头像 → **Copy User ID**

**4. 配置**

```json
{
  "channels": {
    "discord": {
      "enabled": true,
      "token": "YOUR_BOT_TOKEN",
      "allowFrom": ["YOUR_USER_ID"],
      "allowChannels": [],
      "groupPolicy": "mention",
      "streaming": true
    }
  }
}
```

> `groupPolicy` 控制机器人在群组渠道中的响应方式：
> - `"mention"`（默认）— 仅在被 @ 提及时响应
> - `"open"` — 响应所有消息
> 当发送者位于 `allowFrom` 中时，私信始终会响应。
> - 如果你将群组策略设为开放，请将新线程创建为私密线程，然后将机器人 @ 到其中。否则，该线程本身以及你创建它的渠道都会生成机器人会话。
> `allowChannels` 将机器人限制在特定 Discord 渠道 ID 中。空数组（默认）表示在机器人可见的每个渠道中响应。示例：`["1234567890", "0987654321"]`。该筛选在 `allowFrom` 之后应用，因此两者都必须通过。允许的父渠道下的 Discord 线程也会被允许；对于 Forum 渠道，允许父 Forum 渠道即允许该 forum 中的所有线程/帖子。
> `streaming` 默认为 `true`。仅当你明确需要非流式回复时才禁用它。

**5. 邀请机器人**
- OAuth2 → URL Generator
- Scopes：`bot`
- Bot Permissions：`Send Messages`、`Read Message History`
- 打开生成的邀请 URL，并将机器人添加到你的服务器

**6. 运行**

```bash
nanobot gateway
```

</details>

<details>
<summary><b>Matrix (Element)</b></summary>

先启用 Matrix 支持：

```bash
nanobot plugins enable matrix
```

> [!NOTE]
> Matrix 加密在 Windows 上默认禁用，因为 `matrix-nio[e2e]` 依赖于 `python-olm`，后者没有预构建的 Windows wheel。如果你需要 Matrix E2EE，请使用 macOS、Linux 或 WSL2。

**1. 创建/选择 Matrix 账户**

- 在你的 homeserver 上创建或复用 Matrix 账户（例如 `matrix.org`）。
- 确认你可以使用 Element 登录。

**2. 获取凭据**

- 你需要：
  - `userId`（示例：`@nanobot:matrix.org`）
  - `password`

（注意：出于兼容旧版本的原因，仍支持 `accessToken` 和 `deviceId`，但为获得可靠的加密，建议改用密码登录。如果提供了 `password`，将忽略 `accessToken` 和 `deviceId`。）

**3. 配置**

```json
{
  "channels": {
    "matrix": {
      "enabled": true,
      "homeserver": "https://matrix.org",
      "userId": "@nanobot:matrix.org",
      "password": "mypasswordhere",
      "e2eeEnabled": true,
      "sasVerification": true,
      "allowFrom": ["@your_user:matrix.org"],
      "groupPolicy": "open",
      "groupAllowFrom": [],
      "allowRoomMentions": false,
      "maxMediaBytes": 20971520
    }
  }
}
```

> 请保持持久化的 `matrix-store`，否则如果它们在重启之间发生变化，加密会话状态将丢失。

| 选项 | 说明 |
|--------|-------------|
| `allowFrom` | 允许交互的用户 ID。空数组会拒绝所有用户；使用 `["*"]` 以允许所有人。 |
| `groupPolicy` | `open`（默认）、`mention` 或 `allowlist`。 |
| `groupAllowFrom` | 房间允许列表（策略为 `allowlist` 时使用）。 |
| `allowRoomMentions` | 在提及模式下接受 `@room` 提及。 |
| `e2eeEnabled` | E2EE 支持（默认 `true`）。设为 `false` 可仅使用纯文本。 |
| `sasVerification` | 自动完成来自允许用户的 SAS 设备验证请求（默认 `false`）。对于不提供第三方设备手动信任功能的 Element X 很有用。 |
| `maxMediaBytes` | 最大附件大小（默认 `20MB`）。设为 `0` 可阻止所有媒体。 |




**4. 运行**

```bash
nanobot gateway
```

</details>

<details>
<summary><b>WhatsApp</b></summary>

需要 WhatsApp 可选依赖项：

```bash
nanobot plugins enable whatsapp
```

**1. 使用 QR 关联设备**

```bash
nanobot channels login whatsapp
# Scan QR with WhatsApp → Settings → Linked Devices
```

**2. 配置**

```json
{
  "channels": {
    "whatsapp": {
      "enabled": true,
      "allowFrom": ["1234567890"]
    }
  }
}
```

对于群组，`allowFrom` 可以包含参与者发送者 ID/LID 或
群组 JID/裸群组 ID。参与者条目允许该发送者在机器人
可见的任何位置使用；群组条目允许在该群组中回复。

可选会话数据库路径：

```json
{
  "channels": {
    "whatsapp": {
      "databasePath": "~/.nanobot/whatsapp-auth/neonize.db"
    }
  }
}
```

**从旧 bridge 迁移**

- 移除 `bridgeUrl` 和 `bridgeToken`；WhatsApp 不再运行本地 Node.js bridge。
- 重新运行 `nanobot channels login whatsapp`；旧 Baileys bridge 身份验证数据不会被 neonize 复用。
- 将 `allowFrom` 条目更新为不带前导 `+` 的 WhatsApp 发送者 ID。

**3. 运行**

```bash
nanobot gateway
```

**可选：静态 LID 映射**

现代 WhatsApp 可能会传递发送者的 LID 而不是其电话号码。nanobot
会在两个标识符同时存在时于运行时学习 LID 到电话的映射，但你也
可以预先设定映射，以便从
第一条消息开始解析电话号码：

```json
{
  "channels": {
    "whatsapp": {
      "enabled": true,
      "allowFrom": ["1234567890"],
      "lidMappings": { "123456789012345": "1234567890" }
    }
  }
}
```

</details>

<details>
<summary><b>Feishu</b></summary>

使用 **WebSocket** 长连接，无需公共 IP。

**快速设置：QR 登录**

```bash
nanobot plugins enable feishu
nanobot channels login feishu
# 使用 --force 创建/登录新机器人
```

在手机上使用飞书/Lark 打开打印出的 URL 或扫描二维码。如果安装了可选的 `qrcode` 包，nanobot 会显示终端二维码；否则会打印登录 URL。nanobot 会在活动配置文件的 `channels.feishu` 下写入 `appId`、`appSecret`、`domain` 和 `enabled`。使用 `--config <path>` 更新非默认配置。

如果你的账户无法使用二维码登录，请使用下方的手动设置。

**手动设置**

**1. 创建飞书机器人**
- 访问 [飞书开放平台](https://open.feishu.cn/app)
- 创建新应用 → 启用 **机器人** 能力
- **权限**：
  - `im:message`（发送消息）和 `im:message.p2p_msg:readonly`（接收消息）
  - **流式回复**（nanobot 中默认启用）：添加 **`cardkit:card:write`**（在飞书开发者控制台中通常标记为 **创建和更新卡片**）。这是 CardKit 实体和流式助手文本所必需的。旧应用可能尚未拥有此权限，打开 **权限管理**，启用该权限范围，然后如果控制台要求，请**发布**新应用版本。
  - 如果你**无法**添加 `cardkit:card:write`，请在 `channels.feishu` 下设置 `"streaming": false`（见下文）。机器人仍可正常工作；回复将使用普通交互式卡片，而非逐 token 流式传输。
- **事件**：添加 `im.message.receive_v1`（接收消息）
  - 选择 **长连接** 模式（需要先运行 nanobot 以建立连接）
- 从“凭证与基础信息”获取 **App ID** 和 **App Secret**
- 发布应用

**2. 配置**

```json
{
  "channels": {
    "feishu": {
      "enabled": true,
      "appId": "cli_xxx",
      "appSecret": "xxx",
      "encryptKey": "",
      "verificationToken": "",
      "allowFrom": ["ou_YOUR_OPEN_ID"],
      "groupPolicy": "mention",
      "reactEmoji": "OnIt",
      "doneEmoji": "DONE",
      "toolHintPrefix": "🔧",
      "streaming": true,
      "domain": "feishu"
    }
  }
}
```

> `streaming` 默认为 `true`。如果你的应用没有 **`cardkit:card:write`**，请使用 `false`（参见上方权限说明）。
> `encryptKey` 和 `verificationToken` 对于长连接模式是可选的。
> `allowFrom`：添加你的 open_id（向机器人发送消息时，可在 nanobot 日志中找到）。使用 `["*"]` 允许所有用户。
> `groupPolicy`：`"mention"`（默认，仅在被 @ 提及时回复），`"open"`（回复所有群消息）。私聊始终会回复。
> `reactEmoji`：“处理中”状态的表情符号（默认：`OnIt`）。参见[可用表情符号](https://open.larkoffice.com/document/server-docs/im-v1/message-reaction/emojis-introduce)。
> `doneEmoji`：“已完成”状态的可选表情符号（例如 `DONE`、`OK`、`HEART`）。设置后，机器人会在移除 `reactEmoji` 后添加此反应。
> `toolHintPrefix`：流式卡片中内联工具提示的前缀（默认：`🔧`）。
> `domain`：中国大陆使用 `"feishu"`（默认）（open.feishu.cn），国际版 Lark 使用 `"lark"`（open.larksuite.com）。

**3. 运行**

```bash
nanobot gateway
```

> [!TIP]
> 飞书使用 WebSocket 接收消息，无需 webhook 或公网 IP！

</details>

<details>
<summary><b>QQ（QQ 单聊）</b></summary>

使用带 WebSocket 的 **botpy SDK**，无需公网 IP。目前仅支持**私聊消息**。

**安装可选渠道依赖**

```bash
nanobot plugins enable qq
```

**1. 注册并创建机器人**
- 访问 [QQ 开放平台](https://q.qq.com) → 注册成为开发者（个人或企业）
- 创建新的机器人应用
- 前往 **开发设置 (Developer Settings)** → 复制 **AppID** 和 **AppSecret**

**2. 设置测试沙箱**
- 在机器人管理控制台中找到 **沙箱配置 (Sandbox Config)**
- 在 **在消息列表配置** 下，点击 **添加成员** 并添加你自己的 QQ 号码
- 添加后，使用手机 QQ 扫描机器人的二维码 → 打开机器人资料页 → 点击“发消息”开始聊天

**3. 配置**

> - `allowFrom`：添加你的 openid（向机器人发送消息时，可在 nanobot 日志中找到）。使用 `["*"]` 公开访问。
> - `msgFormat`：可选。对旧版 QQ 客户端使用 `"plain"`（默认）以获得最高兼容性，或在较新的客户端上使用 `"markdown"` 以获得更丰富的格式。
> - 对于生产环境：在机器人控制台提交审核并发布。有关完整发布流程，请参阅 [QQ 机器人文档](https://bot.q.qq.com/wiki/)。

```json
{
  "channels": {
    "qq": {
      "enabled": true,
      "appId": "YOUR_APP_ID",
      "secret": "YOUR_APP_SECRET",
      "allowFrom": ["YOUR_OPENID"],
      "msgFormat": "plain"
    }
  }
}
```

**4. 运行**

```bash
nanobot gateway
```

现在从 QQ 向机器人发送消息，它应当会回复！

</details>

<details>
<summary><b>Napcat（通过 OneBot v11 使用 QQ，支持群聊等功能）</b></summary>

通过其**正向 WebSocket**（OneBot v11）连接到 [Napcat](https://github.com/NapNeko/NapCatQQ) 实例。当你有自己的 QQ 账户通过 Napcat 运行，并且需要完整的私聊和群聊支持时，请使用此方式。

**1. 设置 Napcat**

- 安装并登录 Napcat，然后启用**正向 WebSocket** 服务器。参阅[官方 Napcat Docker 教程](https://github.com/NapNeko/NapCat-Docker)。
- 在 webui 中，依次选择“网络配置” -> “新建” -> “Websocket 服务器”，以创建正向 websocket 服务器。默认 URL 为 `ws://127.0.0.1:3001`
- 复制正向 websocket 服务器的 token
- （可选）在 webui 中，依次选择“系统配置” -> “登陆配置” -> “快速登录QQ”，以便在重启后自动登录

**安装可选渠道依赖**

```bash
nanobot plugins enable napcat
```

**2. 配置**

```json
{
  "channels": {
    "napcat": {
      "enabled": true,
      "wsUrl": "ws://127.0.0.1:3001",
      "accessToken": "YOUR_WEBSOCKET_TOKEN",
      "allowFrom": ["*"],
      "groupPolicy": "mention",
      "groupPolicyOverrides": {
        "123456789": "open",
        "987654321": 0.2
      },
      "welcomeNewMembers": true
    }
  }
}
```

| 选项 | 作用 |
|--------|--------------|
| `wsUrl` | Napcat 正向 WebSocket 端点。通过 `accessToken` 进行的 Bearer 认证会在 `Authorization` 标头中发送。 |
| `allowFrom` | 允许与机器人交谈的 QQ 号码。`["*"]` = 任何人。要触发 `welcomeNewMembers`，必须设置 `["*"]`（或包含新加入的用户）。 |
| `groupPolicy` | `"mention"`（默认）— 仅在 @ 提及或回复机器人自己的消息时回复。`"open"` — 回复每条群消息。`[0.0, 1.0]` 中的浮点数 `p` — @ 提及和回复机器人时始终回复；其他每条群消息以概率 `p` 回复（因此 `0.0` ≡ `"mention"`，`1.0` ≡ `"open"`）。私聊始终会回复。 |
| `groupPolicyOverrides` | 按群组覆盖 `groupPolicy` 的可选配置，以群 ID（字符串形式）为键。每个值的格式与 `groupPolicy` 相同（`"mention"`、`"open"` 或浮点数）。未列出的群组会回退到 `groupPolicy`。 |
| `welcomeNewMembers` | 当为 true 时，`notice.group_increase` 事件会作为合成消息推送到总线，以便智能体欢迎新加入者。 |
| `maxImageBytes` | 入站图片下载的硬性上限（字节）。默认为 20 MB。超过限制的图片会被丢弃并发出警告。 |

</details>

<details>
<summary><b>DingTalk（钉钉）</b></summary>

使用**流模式**，无需公网 IP。

**安装可选渠道依赖**

```bash
nanobot plugins enable dingtalk
```

**1. 创建钉钉机器人**
- 访问 [钉钉开放平台](https://open-dev.dingtalk.com/)
- 创建新应用 -> 添加 **机器人** 能力
- **配置**：
  - 开启**流模式**
- **权限**：添加发送消息所需的权限
- 从“凭证”获取 **AppKey**（Client ID）和 **AppSecret**（Client Secret）
- 发布应用

**2. 配置**

```json
{
  "channels": {
    "dingtalk": {
      "enabled": true,
      "clientId": "YOUR_APP_KEY",
      "clientSecret": "YOUR_APP_SECRET",
      "allowFrom": ["YOUR_STAFF_ID"],
      "groupUserIsolation": false
    }
  }
}
```

> `allowFrom`：添加你的员工 ID。使用 `["*"]` 允许所有用户。
>
> `groupUserIsolation`：可选。默认为 `false`，即每个群聊保留一个共享会话。设置为 `true` 后，钉钉群聊中的每个发送者都会拥有独立会话，但回复仍会发送回同一群组。

**3. 运行**

```bash
nanobot gateway
```

</details>

<details>
<summary><b>Slack</b></summary>

使用 **Socket Mode**，无需公网 URL。

**安装可选渠道依赖**

```bash
nanobot plugins enable slack
```

**1. 创建 Slack 应用**
- 前往 [Slack API](https://api.slack.com/apps) → **Create New App** → “From scratch”
- 选择名称并选择你的工作区

**2. 配置应用**
- **Socket Mode**：开启 → 生成具有 `connections:write` 权限范围的 **App-Level Token** → 复制它（`xapp-...`）
- **OAuth & Permissions**：添加机器人权限范围：`chat:write`、`reactions:write`、`app_mentions:read`、`files:read`、`files:write`、`channels:history`、`groups:history`、`im:history`、`mpim:history`
- **Event Subscriptions**：开启 → 订阅机器人事件：`message.im`、`message.channels`、`app_mention` → 保存更改
- **App Home**：滚动到 **Show Tabs** → 启用 **Messages Tab** → 勾选 **“Allow users to send Slash commands and messages from the messages tab”**
- **Install App**：点击 **Install to Workspace** → 授权 → 复制 **Bot Token**（`xoxb-...`）

> `files:read` 是读取用户发送给 nanobot 的文件所必需的。`files:write` 是 nanobot 发送图片、视频和其他文件上传内容所必需的。如果稍后添加任一权限范围，请重新将 Slack 应用安装到工作区，并重启 nanobot，使其使用更新后的机器人 token。

**3. 配置 nanobot**

```json
{
  "channels": {
    "slack": {
      "enabled": true,
      "botToken": "xoxb-...",
      "appToken": "xapp-...",
      "allowFrom": ["YOUR_SLACK_USER_ID"],
      "groupPolicy": "mention"
    }
  }
}
```

**4. 运行**

```bash
nanobot gateway
```

直接私信机器人，或在渠道中 @ 提及它，它应当会回复！

> [!TIP]
> - `groupPolicy`：`"mention"`（默认，仅在被 @ 提及时回复）、`"open"`（回复所有渠道消息），或 `"allowlist"`（通过 `groupAllowFrom` 限制为特定渠道）。
> - `groupAllowFrom`：当 `groupPolicy` 为 `"allowlist"` 时，机器人可以在其中回复的渠道 ID。
> - `groupRequireMention`：当为 `true` 且 `groupPolicy` 为 `"allowlist"` 时，机器人仅会回复 `groupAllowFrom` 中的渠道，且仅在被 @ 提及时回复（而非每条消息）。对 `"mention"`/`"open"` 无效。使用此项可将机器人限制在批准的渠道中，同时保留仅提及回复的行为。
> - 私信策略默认开放。设置 `"dm": {"enabled": false}` 可禁用私信。

</details>

<details>
<summary><b>电子邮件</b></summary>

为 nanobot 创建其专属电子邮件账户。它轮询 **IMAP** 获取传入邮件，并通过 **SMTP** 回复，如同个人电子邮件助手。

**1. 获取凭证（以 Gmail 为例）**
- 为你的机器人创建专用 Gmail 账户（例如 `my-nanobot@gmail.com`）
- 启用两步验证 → 创建[应用专用密码](https://myaccount.google.com/apppasswords)
- 对 IMAP 和 SMTP 都使用此应用专用密码

**2. 配置**

> - `consentGranted` 必须为 `true` 才允许访问邮箱。这是一项安全门控，设置为 `false` 可完全禁用。
> - `allowFrom`：添加你的电子邮件地址。使用 `["*"]` 接受任何人的电子邮件。
> - `smtpUseTls` 和 `smtpUseSsl` 分别默认为 `true` / `false`，这适用于 Gmail（端口 587 + STARTTLS）。无需显式设置它们。
> - 如果你只想读取/分析电子邮件而不发送自动回复，请设置 `"autoReplyEnabled": false`。
> - `postAction`：已处理电子邮件的可选后处理操作：`"delete"` 或 `"move"`（默认 `null`）。
>   仅在已接受的电子邮件成功送达 AI 管道后执行。
> - `postActionMoveMailbox`：当 `postAction` 为 `"move"` 时使用的目标邮箱（例如 `"Processed"` 或 `"[Gmail]/Trash"`）。
> - `postActionIgnoreSkipped`：如果为 `true`（默认），跳过的电子邮件将被忽略，不执行后处理操作，也不会被移动/删除。
> - `postActionExpunge`：当为 `true` 时，如果按 UID 范围的清除不可用或失败，该渠道允许使用全邮箱 `EXPUNGE` 回退方式（默认 `false`）。仅在缺少现代 UIDPLUS 支持的非常旧的 IMAP 服务器上启用。请注意，此回退方式会清除邮箱中**所有**标记为已删除的邮件，包括并非由智能体处理的邮件。对于所有现代 IMAP 服务器，保持关闭都是安全的。
> - `allowedAttachmentTypes`：保存匹配这些 MIME 类型的入站附件，`["*"]` 表示全部，例如 `["application/pdf", "image/*"]`（默认 `[]` = 禁用）。
> - `maxAttachmentSize`：每个附件的最大大小（字节）（默认 `2000000` / 2MB）。
> - `maxAttachmentsPerEmail`：每封电子邮件最多保存的附件数（默认 `5`）。

```json
{
  "channels": {
    "email": {
      "enabled": true,
      "consentGranted": true,
      "imapHost": "imap.gmail.com",
      "imapPort": 993,
      "imapUsername": "my-nanobot@gmail.com",
      "imapPassword": "your-app-password",
      "smtpHost": "smtp.gmail.com",
      "smtpPort": 587,
      "smtpUsername": "my-nanobot@gmail.com",
      "smtpPassword": "your-app-password",
      "fromAddress": "my-nanobot@gmail.com",
      "allowFrom": ["your-real-email@gmail.com"],
      "postAction": "move",
      "postActionMoveMailbox": "[Gmail]/Trash",
      "postActionIgnoreSkipped": true,
      "postActionExpunge": false,
      "allowedAttachmentTypes": ["application/pdf", "image/*"]
    }
  }
}
```


**3. 运行**

```bash
nanobot gateway
```

</details>

<details>
<summary><b>WeChat（微信 / Weixin）</b></summary>

通过 ilinkai 个人微信 API 使用带二维码登录的 **HTTP 长轮询**。无需本地微信桌面客户端。

**1. 启用 WeChat 支持**

```bash
nanobot plugins enable weixin
```

**2. 配置**

```json
{
  "channels": {
    "weixin": {
      "enabled": true,
      "allowFrom": ["YOUR_WECHAT_USER_ID"]
    }
  }
}
```

> - `allowFrom`：添加你在 nanobot 日志中看到的微信账户发送者 ID。使用 `["*"]` 允许所有用户。
> - `token`：可选。若省略，请交互式登录，nanobot 将为你保存 token。
> - `routeTag`：可选。当你的上游 Weixin 部署需要请求路由时，nanobot 会将其作为 `SKRouteTag` 标头发送。
> - `stateDir`：可选。默认使用 nanobot 的 Weixin 状态运行时目录。
> - `pollTimeout`：可选的长轮询超时时间（秒）。

**3. 登录**

```bash
nanobot channels login weixin
```

使用 `--force` 重新认证并忽略任何已保存的 token：

```bash
nanobot channels login weixin --force
```

**4. 运行**

```bash
nanobot gateway
```

</details>

<details>
<summary><b>Wecom（企业微信）</b></summary>

> 此处使用 [wecom-aibot-sdk-python](https://github.com/chengyongru/wecom_aibot_sdk)（官方 [@wecom/aibot-node-sdk](https://www.npmjs.com/package/@wecom/aibot-node-sdk) 的社区 Python 版本）。
>
> 使用 **WebSocket** 长连接，无需公网 IP。

**1. 启用 WeCom 支持**

```bash
nanobot plugins enable wecom
```

**2. 创建 WeCom AI 机器人**

前往 WeCom 管理控制台 → 智能机器人 → 创建机器人 → 选择使用**长连接**的 **API 模式**。复制 Bot ID 和 Secret。

**3. 配置**

```json
{
  "channels": {
    "wecom": {
      "enabled": true,
      "botId": "your_bot_id",
      "secret": "your_bot_secret",
      "allowFrom": ["your_id"]
    }
  }
}
```

**4. 运行**

```bash
nanobot gateway
```

</details>

<details>
<summary><b>Microsoft Teams</b>（MVP，仅私信）</summary>

> 直接消息文本收发、租户感知 OAuth、会话引用持久化。
> 使用公网 HTTPS webhook，不使用 WebSocket；你需要隧道或反向代理。

**1. 启用 Microsoft Teams 支持**

```bash
nanobot plugins enable msteams
```

**2. 创建 Teams / Azure 机器人应用注册**

创建或复用 Microsoft Teams / Azure 机器人应用注册。将机器人消息端点设置为以 `/api/messages` 结尾的公网 HTTPS URL。

**3. 配置**

```json
{
  "channels": {
    "msteams": {
      "enabled": true,
      "appId": "YOUR_APP_ID",
      "appPassword": "YOUR_APP_SECRET",
      "tenantId": "YOUR_TENANT_ID",
      "host": "0.0.0.0",
      "port": 3978,
      "path": "/api/messages",
      "allowFrom": ["*"],
      "replyInThread": true,
      "mentionOnlyResponse": "Hi — what can I help with?",
      "validateInboundAuth": true,
      "refTtlDays": 30,
      "pruneWebChatRefs": true,
      "pruneNonPersonalRefs": true,
      "refTouchIntervalS": 300
    }
  }
}
```

> - `replyInThread: true` 会在已存储的 `activity_id` 可用时回复触发的 Teams 活动。
> - `mentionOnlyResponse` 控制当用户仅发送机器人提及（`<at>Nanobot</at>`）时 Nanobot 收到的内容。设置为 `""` 可忽略仅提及消息。
> - `validateInboundAuth: true` 启用入站 Bot Framework bearer token 验证（签名、颁发者、受众、有效期、`serviceUrl`）。这是公网部署的安全默认值。仅针对本地开发或严格受控的测试将其设置为 `false`。
> - `refTtlDays`（默认 `30`）控制已存储会话引用在被清理前可保留的时长。
> - `pruneWebChatRefs`（默认 `true`）会删除服务 URL 为 `webchat.botframework.com` 的引用。
> - `pruneNonPersonalRefs`（默认 `true`）会删除其 `conversation_type` 不为 `personal` 的引用。
> - `refTouchIntervalS`（默认 `300`）限制成功发送为活跃引用刷新 `updated_at` 的频率。

**4. 运行**

```bash
nanobot gateway
```

</details>

<details>
<summary><b>Signal</b></summary>

使用 HTTP 模式下的 **signal-cli** 守护进程，通过 SSE 接收消息，通过 JSON-RPC 发送消息。

**1. 安装 signal-cli**

安装 [signal-cli](https://github.com/AsamK/signal-cli) 并注册电话号码：

```bash
signal-cli -u +1234567890 register
signal-cli -u +1234567890 verify <CODE>
```

启动守护进程：

```bash
signal-cli -a +1234567890 daemon --http localhost:8080
```

**2. 配置**

```json
{
  "channels": {
    "signal": {
      "enabled": true,
      "phoneNumber": "+1234567890",
      "daemonHost": "localhost",
      "daemonPort": 8080,

      "dm": {
        "enabled": true,
        "policy": "open"
      },
      "group": {
        "enabled": true,
        "policy": "open",
        "requireMention": true
      }
    }
  }
}
```

> - `phoneNumber`: 您已注册的 Signal 电话号码。
> - `daemonHost` / `daemonPort`: signal-cli 守护进程的监听位置（默认 `localhost:8080`）。
> - `dm.policy`: `"open"`（任何人均可发送私信）或 `"allowlist"`（仅限列出的号码/UUID）。使用 `"allowlist"` 时，未列出的私信发送者会收到配对码。
> - `dm.allowFrom`: 允许的电话号码或 UUID 列表（当策略为 `"allowlist"` 时使用）。
> - `group.policy`: `"open"`（所有群组）或 `"allowlist"`（仅限列出的群组 ID）。
> - `group.requireMention`: 当为 `true`（默认值）时，机器人仅在被 @提及时响应群组消息。
> - `group.allowFrom`: 允许的群组 ID 列表（当群组策略为 `"allowlist"` 时使用）。
> - `attachmentsDir`: 覆盖 signal-cli 存储入站附件的目录。默认为 `~/.local/share/signal-cli/attachments`（Linux 默认值）。如果 signal-cli 使用自定义 `XDG_DATA_HOME` 运行，或在 macOS/Windows 上运行，请设置此项。
> - `groupMessageBufferSize`: 为上下文保留的近期群组消息数量（默认 `20`，必须 > 0）。

**3. 运行**

```bash
nanobot gateway
```

> [!TIP]
> 如果连接断开，渠道会使用指数退避自动重新连接 signal-cli 守护进程。
> 机器人回复中的 Markdown 会自动转换为 Signal 文本样式（粗体、斜体、代码等）。

</details>
