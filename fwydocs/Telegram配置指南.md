# Telegram 配置与打通指南

## 快速开始（5 分钟）

### 步骤 1：获取 Bot Token

你已经有了 token：
```
8377475570:AAHapEBid-IbPVF-K5voINU6M_t-unZLCdc
```

### 步骤 2：配置 nanobot

编辑 `~/.nanobot/config.json`（如果文件不存在，先运行 `nanobot onboard`）

找到 `channels.telegram` 部分，配置如下：

```json
{
  "channels": {
    "telegram": {
      "enabled": true,
      "token": "8377475570:AAHapEBid-IbPVF-K5voINU6M_t-unZLCdc",
      "allowFrom": [],
      "replyToMessage": false,
      "proxy": null
    }
  }
}
```

**配置说明：**

| 字段 | 必需 | 说明 |
|------|------|------|
| `enabled` | ✓ | 是否启用 Telegram 通道，必须设为 `true` |
| `token` | ✓ | Bot token，从 @BotFather 获得 |
| `allowFrom` | ✗ | 允许的用户列表（空数组 = 所有人都允许）<br>格式: `["user_id\|username"]` 或 `["user_id"]` |
| `replyToMessage` | ✗ | 是否引用原消息回复（推荐 `false`） |
| `proxy` | ✗ | 代理 URL，如需翻墙时使用<br>格式: `"http://127.0.0.1:7890"` 或 `"socks5://127.0.0.1:1080"` |

### 步骤 3：确保 API 密钥配置

nanobot 需要 LLM API 密钥。在 `~/.nanobot/config.json` 中配置 `providers` 部分：

```json
{
  "providers": {
    "anthropic": {
      "apiKey": "sk-ant-xxx..."
    }
  },
  "agents": {
    "defaults": {
      "model": "anthropic/claude-opus-4-5"
    }
  }
}
```

### 步骤 4：启动 nanobot

```bash
nanobot agent
```

或后台运行：

```bash
nanobot agent &
```

**预期输出：**

```
[INFO] Starting Telegram bot (polling mode)...
[INFO] Telegram bot @nanobot_username connected
[DEBUG] Telegram bot commands registered
```

### 步骤 5：在 Telegram 中测试

1. 在 Telegram 中搜索你的 bot（例如 `@your_bot_username`）
2. 点击 "开始" 按钮或发送 `/start`
3. 给 bot 发送一条消息

如果 bot 有所回应，说明连接成功！

---

## 配置细节

### 用户白名单（allowFrom）

如果需要限制只有特定用户能与 bot 交互：

```json
{
  "channels": {
    "telegram": {
      "enabled": true,
      "token": "...",
      "allowFrom": [
        "123456789",                    // 用户 ID
        "123456789|john_doe",           // 用户 ID | 用户名
        "john_doe"                      // 仅用户名（不推荐）
      ]
    }
  }
}
```

**获取你的 Telegram 用户 ID：**

1. 在 Telegram 中搜索 `@userinfobot`
2. 点击 "开始" 并点击按钮
3. 复制你的 User ID

### 代理配置（翻墙）

如果在需要翻墙的环境使用：

```json
{
  "channels": {
    "telegram": {
      "enabled": true,
      "token": "...",
      "proxy": "http://127.0.0.1:7890"  // Clash 等代理的默认端口
    }
  }
}
```

### 引用回复

启用后，bot 的回复将引用（引用）你的原消息：

```json
{
  "channels": {
    "telegram": {
      "enabled": true,
      "token": "...",
      "replyToMessage": true
    }
  }
}
```

---

## 常见问题

### Q: 为什么 bot 不响应？

**检查清单：**

1. ✓ `enabled` 是否为 `true`
2. ✓ Token 是否正确（从 @BotFather 获取）
3. ✓ API 密钥是否配置（`providers` 部分）
4. ✓ 用户是否在 `allowFrom` 白名单中（如果配置了）
5. ✓ 查看日志：`nanobot agent 2>&1 | grep -i error`

### Q: Token 是什么格式？

Token 由数字、冒号和字母组成：

```
<BOT_ID>:<BOT_TOKEN>
```

例如：
```
8377475570:AAHapEBid-IbPVF-K5voINU6M_t-unZLCdc
```

**安全提示：** 不要将 token 分享给他人或提交到公开仓库。

### Q: 如何更新 token？

1. 在 @BotFather 中生成新 token：`/revoke` 旧 token，`/newtoken`
2. 更新 `~/.nanobot/config.json` 中的 `token` 字段
3. 重启 nanobot

### Q: 支持群组吗？

支持。Bot 可以被添加到群组中。但需要给 bot 赋予必要的权限：

1. 在群组中添加 bot
2. 在 @BotFather 中，编辑 bot 的设置，启用"Group Privacy"（设为关闭）
3. 在群组中邀请 bot 加入

**注意：** 群组中的消息处理与私聊相同，需要 `allowFrom` 中包含用户 ID。

### Q: 支持媒体（图片、视频、语音）吗？

支持。Nanobot 会：
- 自动下载媒体到 `~/.nanobot/media/`
- 语音/音频通过 Groq API 转录
- 在处理消息时包含媒体信息

**需要配置 Groq API Key：**

```json
{
  "providers": {
    "groq": {
      "apiKey": "gsk_xxx..."
    }
  }
}
```

获取密钥：https://console.groq.com/keys

### Q: 如何调试？

启用调试日志：

```bash
nanobot agent --log-level debug 2>&1 | grep -i telegram
```

---

## 文件位置

| 文件 | 位置 | 说明 |
|------|------|------|
| 配置文件 | `~/.nanobot/config.json` | 全局配置 |
| 工作空间 | `~/.nanobot/workspace/` | 对话历史、笔记等 |
| 媒体文件 | `~/.nanobot/media/` | 下载的图片、音频等 |
| 日志 | 控制台输出 | 实时日志（可重定向到文件） |

---

## 实现细节

详见 [telegram打通细节.md](./telegram打通细节.md)

主要包括：
- 长轮询机制（10 秒超时）
- 媒体组缓冲（0.6 秒）
- 打字指示器（每 4 秒发送一次）
- 消息格式转换（Markdown → HTML）
