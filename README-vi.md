<div align="center">
  <img src="nanobot_logo.png" alt="nanobot" width="500">
  <h1>nanobot: Trợ Lý AI Cá Nhân Siêu Nhẹ</h1>
  <p>
    <a href="https://pypi.org/project/nanobot-ai/"><img src="https://img.shields.io/pypi/v/nanobot-ai" alt="PyPI"></a>
    <a href="https://pepy.tech/project/nanobot-ai"><img src="https://static.pepy.tech/badge/nanobot-ai" alt="Downloads"></a>
    <img src="https://img.shields.io/badge/python-≥3.11-blue" alt="Python">
    <img src="https://img.shields.io/badge/license-MIT-green" alt="License">
    <a href="./COMMUNICATION.md"><img src="https://img.shields.io/badge/Feishu-Group-E9DBFC?style=flat&logo=feishu&logoColor=white" alt="Feishu"></a>
    <a href="./COMMUNICATION.md"><img src="https://img.shields.io/badge/WeChat-Group-C5EAB4?style=flat&logo=wechat&logoColor=white" alt="WeChat"></a>
    <a href="https://discord.gg/MnCvHqpUGB"><img src="https://img.shields.io/badge/Discord-Community-5865F2?style=flat&logo=discord&logoColor=white" alt="Discord"></a>
  </p>
</div>

🐈 **nanobot** là một trợ lý AI cá nhân **siêu nhẹ** được lấy cảm hứng từ [OpenClaw](https://github.com/openclaw/openclaw)

⚡️ Cung cấp đầy đủ chức năng agent cốt lõi chỉ trong **~4.000** dòng code — **nhỏ hơn 99%** so với hơn 430k dòng của Clawdbot.

📏 Số dòng thực tế: **3.966 dòng** (chạy `bash core_agent_lines.sh` để kiểm tra bất cứ lúc nào)

## 📢 Tin Tức

- **2026-02-24** 🚀 Phát hành **v0.1.4.post2** — bản phát hành tập trung vào độ tin cậy với heartbeat được thiết kế lại, tối ưu hóa cache prompt, và tăng cường ổn định cho provider & channel. Xem [ghi chú phát hành](https://github.com/HKUDS/nanobot/releases/tag/v0.1.4.post2) để biết chi tiết.
- **2026-02-23** 🔧 Heartbeat gọi công cụ ảo, tối ưu hóa cache prompt, sửa lỗi Slack mrkdwn.
- **2026-02-22** 🛡️ Cách ly luồng Slack, sửa lỗi gõ Discord, cải thiện độ tin cậy của agent.
- **2026-02-21** 🎉 Phát hành **v0.1.4.post1** — provider mới, hỗ trợ media đa kênh, và cải thiện ổn định lớn. Xem [ghi chú phát hành](https://github.com/HKUDS/nanobot/releases/tag/v0.1.4.post1) để biết chi tiết.
- **2026-02-20** 🐦 Feishu hiện nhận file đa phương tiện từ người dùng. Hệ thống bộ nhớ đáng tin cậy hơn ở nền.
- **2026-02-19** ✨ Slack giờ gửi được file, Discord tách tin nhắn dài, và subagent hoạt động trong chế độ CLI.
- **2026-02-18** ⚡️ nanobot hiện hỗ trợ VolcEngine, MCP custom auth headers, và Anthropic prompt caching.
- **2026-02-17** 🎉 Phát hành **v0.1.4** — hỗ trợ MCP, streaming tiến trình, provider mới, và nhiều cải tiến kênh. Xem [ghi chú phát hành](https://github.com/HKUDS/nanobot/releases/tag/v0.1.4) để biết chi tiết.
- **2026-02-16** 🦞 nanobot tích hợp kỹ năng [ClawHub](https://clawhub.ai) — tìm kiếm và cài đặt kỹ năng agent công khai.
- **2026-02-15** 🔑 nanobot hiện hỗ trợ provider OpenAI Codex với hỗ trợ đăng nhập OAuth.
- **2026-02-14** 🔌 nanobot hiện hỗ trợ MCP! Xem [phần MCP](#mcp-model-context-protocol) để biết chi tiết.
- **2026-02-13** 🎉 Phát hành **v0.1.3.post7** — bao gồm tăng cường bảo mật và nhiều cải tiến. **Vui lòng nâng cấp lên phiên bản mới nhất để xử lý các vấn đề bảo mật**. Xem [ghi chú phát hành](https://github.com/HKUDS/nanobot/releases/tag/v0.1.3.post7) để biết thêm chi tiết.
- **2026-02-12** 🧠 Hệ thống bộ nhớ được thiết kế lại — Ít code hơn, đáng tin cậy hơn. Tham gia [thảo luận](https://github.com/HKUDS/nanobot/discussions/566) về điều này!
- **2026-02-11** ✨ Cải thiện trải nghiệm CLI và thêm hỗ trợ MiniMax!

<details>
<summary>Tin tức trước đó</summary>

- **2026-02-10** 🎉 Phát hành **v0.1.3.post6** với nhiều cải tiến! Kiểm tra [ghi chú](https://github.com/HKUDS/nanobot/releases/tag/v0.1.3.post6) cập nhật và [lộ trình](https://github.com/HKUDS/nanobot/discussions/431) của chúng tôi.
- **2026-02-09** 💬 Đã thêm hỗ trợ Slack, Email và QQ — nanobot giờ hỗ trợ nhiều nền tảng chat!
- **2026-02-08** 🔧 Tái cấu trúc Providers — thêm provider LLM mới giờ chỉ cần 2 bước đơn giản! Xem [tại đây](#providers).
- **2026-02-07** 🚀 Phát hành **v0.1.3.post5** với hỗ trợ Qwen & nhiều cải tiến quan trọng! Xem [tại đây](https://github.com/HKUDS/nanobot/releases/tag/v0.1.3.post5) để biết chi tiết.
- **2026-02-06** ✨ Đã thêm provider Moonshot/Kimi, tích hợp Discord, và tăng cường bảo mật!
- **2026-02-05** ✨ Đã thêm kênh Feishu, provider DeepSeek, và tăng cường hỗ trợ tác vụ theo lịch!
- **2026-02-04** 🚀 Phát hành **v0.1.3.post4** với hỗ trợ đa provider & Docker! Xem [tại đây](https://github.com/HKUDS/nanobot/releases/tag/v0.1.3.post4) để biết chi tiết.
- **2026-02-03** ⚡ Tích hợp vLLM để hỗ trợ LLM cục bộ và cải thiện lập lịch tác vụ bằng ngôn ngữ tự nhiên!
- **2026-02-02** 🎉 nanobot chính thức ra mắt! Chào mừng bạn thử 🐈 nanobot!

</details>

## Các Tính Năng Nổi Bật của nanobot:

🪶 **Siêu Nhẹ**: Chỉ ~4.000 dòng code agent cốt lõi — nhỏ hơn 99% so với Clawdbot.

🔬 **Sẵn Sàng Nghiên Cứu**: Code sạch, dễ đọc, dễ hiểu, chỉnh sửa và mở rộng cho nghiên cứu.

⚡️ **Cực Nhanh**: Kích thước tối giản đồng nghĩa khởi động nhanh hơn, tốn ít tài nguyên hơn, và lặp lại nhanh hơn.

💎 **Dễ Sử Dụng**: Một cú click để triển khai và sẵn sàng sử dụng.

## 🏗️ Kiến Trúc

<p align="center">
  <img src="nanobot_arch.png" alt="nanobot architecture" width="800">
</p>

## ✨ Tính Năng

<table align="center">
  <tr align="center">
    <th><p align="center">📈 Phân Tích Thị Trường Thực Tế 24/7</p></th>
    <th><p align="center">🚀 Kỹ Sư Phần Mềm Full-Stack</p></th>
    <th><p align="center">📅 Quản Lý Lịch Trình Hàng Ngày Thông Minh</p></th>
    <th><p align="center">📚 Trợ Lý Kiến Thức Cá Nhân</p></th>
  </tr>
  <tr>
    <td align="center"><p align="center"><img src="case/search.gif" width="180" height="400"></p></td>
    <td align="center"><p align="center"><img src="case/code.gif" width="180" height="400"></p></td>
    <td align="center"><p align="center"><img src="case/scedule.gif" width="180" height="400"></p></td>
    <td align="center"><p align="center"><img src="case/memory.gif" width="180" height="400"></p></td>
  </tr>
  <tr>
    <td align="center">Khám Phá • Nhận Định • Xu Hướng</td>
    <td align="center">Phát Triển • Triển Khai • Mở Rộng</td>
    <td align="center">Lập Lịch • Tự Động Hóa • Tổ Chức</td>
    <td align="center">Học Hỏi • Ghi Nhớ • Suy Luận</td>
  </tr>
</table>

## 📦 Cài Đặt

**Cài đặt từ source** (tính năng mới nhất, khuyến nghị cho phát triển)

```bash
git clone https://github.com/HKUDS/nanobot.git
cd nanobot
pip install -e .
```

**Cài đặt với [uv](https://github.com/astral-sh/uv)** (ổn định, nhanh)

```bash
uv tool install nanobot-ai
```

**Cài đặt từ PyPI** (ổn định)

```bash
pip install nanobot-ai
```

## 🚀 Bắt Đầu Nhanh

> [!TIP]
> Đặt API key của bạn trong `~/.nanobot/config.json`.
> Lấy API key: [OpenRouter](https://openrouter.ai/keys) (Toàn cầu) · [Brave Search](https://brave.com/search/api/) (tùy chọn, dành cho tìm kiếm web)

**1. Khởi tạo**

```bash
nanobot onboard
```

**2. Cấu hình** (`~/.nanobot/config.json`)

Thêm hoặc hợp nhất **hai phần** này vào config của bạn (các tùy chọn khác đã có giá trị mặc định).

*Đặt API key* (ví dụ: OpenRouter, khuyến nghị cho người dùng toàn cầu):
```json
{
  "providers": {
    "openrouter": {
      "apiKey": "sk-or-v1-xxx"
    }
  }
}
```

*Đặt model*:
```json
{
  "agents": {
    "defaults": {
      "model": "anthropic/claude-opus-4-5"
    }
  }
}
```

**3. Chat**

```bash
nanobot agent
```

Vậy là xong! Bạn có một trợ lý AI hoạt động chỉ trong 2 phút.

## 💬 Ứng Dụng Chat

Kết nối nanobot với nền tảng chat yêu thích của bạn.

| Kênh | Những gì bạn cần |
|---------|-----------------|
| **Telegram** | Bot token từ @BotFather |
| **Discord** | Bot token + quyền Message Content |
| **WhatsApp** | Quét mã QR |
| **Feishu** | App ID + App Secret |
| **Mochat** | Claw token (có thể tự động thiết lập) |
| **DingTalk** | App Key + App Secret |
| **Slack** | Bot token + App-Level token |
| **Email** | Thông tin đăng nhập IMAP/SMTP |
| **QQ** | App ID + App Secret |

<details>
<summary><b>Telegram</b> (Khuyến nghị)</summary>

**1. Tạo bot**
- Mở Telegram, tìm kiếm `@BotFather`
- Gửi `/newbot`, làm theo hướng dẫn
- Sao chép token

**2. Cấu hình**

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

> Bạn có thể tìm **User ID** của mình trong cài đặt Telegram. Nó hiển thị dưới dạng `@yourUserId`.
> Sao chép giá trị này **không có ký tự `@`** và dán vào file config.


**3. Chạy**

```bash
nanobot gateway
```

</details>

<details>
<summary><b>Mochat (Claw IM)</b></summary>

Mặc định sử dụng **Socket.IO WebSocket**, với fallback HTTP polling.

**1. Yêu cầu nanobot thiết lập Mochat cho bạn**

Chỉ cần gửi tin nhắn này đến nanobot (thay `xxx@xxx` bằng email thực của bạn):

```
Read https://raw.githubusercontent.com/HKUDS/MoChat/refs/heads/main/skills/nanobot/skill.md and register on MoChat. My Email account is xxx@xxx Bind me as your owner and DM me on MoChat.
```

nanobot sẽ tự động đăng ký, cấu hình `~/.nanobot/config.json`, và kết nối với Mochat.

**2. Khởi động lại gateway**

```bash
nanobot gateway
```

Vậy là xong — nanobot xử lý phần còn lại!

<br>

<details>
<summary>Cấu hình thủ công (nâng cao)</summary>

Nếu bạn muốn cấu hình thủ công, thêm phần sau vào `~/.nanobot/config.json`:

> Giữ `claw_token` ở chế độ riêng tư. Nó chỉ nên được gửi trong header `X-Claw-Token` đến endpoint Mochat API của bạn.

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

**1. Tạo bot**
- Truy cập https://discord.com/developers/applications
- Tạo ứng dụng → Bot → Add Bot
- Sao chép bot token

**2. Bật intents**
- Trong cài đặt Bot, bật **MESSAGE CONTENT INTENT**
- (Tùy chọn) Bật **SERVER MEMBERS INTENT** nếu bạn dự định sử dụng allow lists dựa trên dữ liệu thành viên

**3. Lấy User ID của bạn**
- Discord Settings → Advanced → bật **Developer Mode**
- Nhấp chuột phải vào avatar → **Copy User ID**

**4. Cấu hình**

```json
{
  "channels": {
    "discord": {
      "enabled": true,
      "token": "YOUR_BOT_TOKEN",
      "allowFrom": ["YOUR_USER_ID"]
    }
  }
}
```

**5. Mời bot**
- OAuth2 → URL Generator
- Scopes: `bot`
- Bot Permissions: `Send Messages`, `Read Message History`
- Mở URL mời được tạo ra và thêm bot vào server của bạn

**6. Chạy**

```bash
nanobot gateway
```

</details>

<details>
<summary><b>WhatsApp</b></summary>

Yêu cầu **Node.js ≥18**.

**1. Liên kết thiết bị**

```bash
nanobot channels login
# Quét QR bằng WhatsApp → Settings → Linked Devices
```

**2. Cấu hình**

```json
{
  "channels": {
    "whatsapp": {
      "enabled": true,
      "allowFrom": ["+1234567890"]
    }
  }
}
```

**3. Chạy** (hai terminal)

```bash
# Terminal 1
nanobot channels login

# Terminal 2
nanobot gateway
```

</details>

<details>
<summary><b>Feishu (飞书)</b></summary>

Sử dụng kết nối lâu dài **WebSocket** — không cần IP công khai.

**1. Tạo bot Feishu**
- Truy cập [Feishu Open Platform](https://open.feishu.cn/app)
- Tạo ứng dụng mới → Bật khả năng **Bot**
- **Quyền**: Thêm `im:message` (gửi tin nhắn)
- **Sự kiện**: Thêm `im.message.receive_v1` (nhận tin nhắn)
  - Chọn chế độ **Long Connection** (yêu cầu chạy nanobot trước để thiết lập kết nối)
- Lấy **App ID** và **App Secret** từ "Credentials & Basic Info"
- Xuất bản ứng dụng

**2. Cấu hình**

```json
{
  "channels": {
    "feishu": {
      "enabled": true,
      "appId": "cli_xxx",
      "appSecret": "xxx",
      "encryptKey": "",
      "verificationToken": "",
      "allowFrom": []
    }
  }
}
```

> `encryptKey` và `verificationToken` là tùy chọn cho chế độ Long Connection.
> `allowFrom`: Để trống để cho phép tất cả người dùng, hoặc thêm `["ou_xxx"]` để hạn chế quyền truy cập.

**3. Chạy**

```bash
nanobot gateway
```

> [!TIP]
> Feishu sử dụng WebSocket để nhận tin nhắn — không cần webhook hay IP công khai!

</details>

<details>
<summary><b>QQ (QQ单聊)</b></summary>

Sử dụng **botpy SDK** với WebSocket — không cần IP công khai. Hiện tại chỉ hỗ trợ **tin nhắn riêng tư**.

**1. Đăng ký & tạo bot**
- Truy cập [QQ Open Platform](https://q.qq.com) → Đăng ký làm nhà phát triển (cá nhân hoặc doanh nghiệp)
- Tạo ứng dụng bot mới
- Vào **开发设置 (Cài Đặt Nhà Phát Triển)** → sao chép **AppID** và **AppSecret**

**2. Thiết lập sandbox để kiểm thử**
- Trong bảng điều khiển quản lý bot, tìm **沙箱配置 (Cấu Hình Sandbox)**
- Trong **在消息列表配置**, nhấp **添加成员** và thêm số QQ của bạn
- Sau khi thêm, quét mã QR của bot bằng QQ di động → mở hồ sơ bot → nhấn "发消息" để bắt đầu chat

**3. Cấu hình**

> - `allowFrom`: Để trống để truy cập công khai, hoặc thêm openid người dùng để hạn chế. Bạn có thể tìm openid trong log nanobot khi người dùng nhắn tin cho bot.
> - Đối với môi trường production: gửi đánh giá trong bảng điều khiển bot và xuất bản. Xem [Tài Liệu Bot QQ](https://bot.q.qq.com/wiki/) để biết quy trình xuất bản đầy đủ.

```json
{
  "channels": {
    "qq": {
      "enabled": true,
      "appId": "YOUR_APP_ID",
      "secret": "YOUR_APP_SECRET",
      "allowFrom": []
    }
  }
}
```

**4. Chạy**

```bash
nanobot gateway
```

Giờ hãy gửi tin nhắn đến bot từ QQ — bot sẽ phản hồi!

</details>

<details>
<summary><b>DingTalk (钉钉)</b></summary>

Sử dụng **Stream Mode** — không cần IP công khai.

**1. Tạo bot DingTalk**
- Truy cập [DingTalk Open Platform](https://open-dev.dingtalk.com/)
- Tạo ứng dụng mới -> Thêm khả năng **Robot**
- **Cấu hình**:
  - Bật **Stream Mode**
- **Quyền**: Thêm các quyền cần thiết để gửi tin nhắn
- Lấy **AppKey** (Client ID) và **AppSecret** (Client Secret) từ "Credentials"
- Xuất bản ứng dụng

**2. Cấu hình**

```json
{
  "channels": {
    "dingtalk": {
      "enabled": true,
      "clientId": "YOUR_APP_KEY",
      "clientSecret": "YOUR_APP_SECRET",
      "allowFrom": []
    }
  }
}
```

> `allowFrom`: Để trống để cho phép tất cả người dùng, hoặc thêm `["staffId"]` để hạn chế quyền truy cập.

**3. Chạy**

```bash
nanobot gateway
```

</details>

<details>
<summary><b>Slack</b></summary>

Sử dụng **Socket Mode** — không cần URL công khai.

**1. Tạo Slack app**
- Vào [Slack API](https://api.slack.com/apps) → **Create New App** → "From scratch"
- Đặt tên và chọn workspace của bạn

**2. Cấu hình app**
- **Socket Mode**: Bật → Tạo **App-Level Token** với scope `connections:write` → sao chép nó (`xapp-...`)
- **OAuth & Permissions**: Thêm bot scopes: `chat:write`, `reactions:write`, `app_mentions:read`
- **Event Subscriptions**: Bật → Đăng ký bot events: `message.im`, `message.channels`, `app_mention` → Lưu thay đổi
- **App Home**: Kéo xuống **Show Tabs** → Bật **Messages Tab** → Chọn **"Allow users to send Slash commands and messages from the messages tab"**
- **Install App**: Nhấp **Install to Workspace** → Xác nhận → sao chép **Bot Token** (`xoxb-...`)

**3. Cấu hình nanobot**

```json
{
  "channels": {
    "slack": {
      "enabled": true,
      "botToken": "xoxb-...",
      "appToken": "xapp-...",
      "groupPolicy": "mention"
    }
  }
}
```

**4. Chạy**

```bash
nanobot gateway
```

Nhắn tin trực tiếp cho bot hoặc @mention nó trong kênh — bot sẽ phản hồi!

> [!TIP]
> - `groupPolicy`: `"mention"` (mặc định — chỉ phản hồi khi được @mention), `"open"` (phản hồi tất cả tin nhắn kênh), hoặc `"allowlist"` (hạn chế các kênh cụ thể).
> - Chính sách DM mặc định là mở. Đặt `"dm": {"enabled": false}` để tắt DM.

</details>

<details>
<summary><b>Email</b></summary>

Cấp cho nanobot tài khoản email riêng. Nó kiểm tra **IMAP** để nhận thư đến và trả lời qua **SMTP** — như một trợ lý email cá nhân.

**1. Lấy thông tin đăng nhập (ví dụ Gmail)**
- Tạo tài khoản Gmail riêng cho bot của bạn (ví dụ: `my-nanobot@gmail.com`)
- Bật Xác minh 2 bước → Tạo [App Password](https://myaccount.google.com/apppasswords)
- Sử dụng app password này cho cả IMAP và SMTP

**2. Cấu hình**

> - `consentGranted` phải là `true` để cho phép truy cập hộp thư. Đây là cổng an toàn — đặt `false` để tắt hoàn toàn.
> - `allowFrom`: Để trống để chấp nhận email từ bất kỳ ai, hoặc hạn chế các người gửi cụ thể.
> - `smtpUseTls` và `smtpUseSsl` mặc định là `true` / `false` tương ứng, phù hợp với Gmail (cổng 587 + STARTTLS). Không cần đặt rõ ràng.
> - Đặt `"autoReplyEnabled": false` nếu bạn chỉ muốn đọc/phân tích email mà không gửi trả lời tự động.

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
      "allowFrom": ["your-real-email@gmail.com"]
    }
  }
}
```

**3. Chạy**

```bash
nanobot gateway
```

</details>

## 🌐 Mạng Xã Hội Agent

🐈 nanobot có khả năng kết nối với mạng xã hội agent (cộng đồng agent). **Chỉ cần gửi một tin nhắn và nanobot của bạn tham gia tự động!**

| Nền tảng | Cách Tham Gia (gửi tin nhắn này đến bot của bạn) |
|----------|----------------|
| [**Moltbook**](https://www.moltbook.com/) | `Read https://moltbook.com/skill.md and follow the instructions to join Moltbook` |
| [**ClawdChat**](https://clawdchat.ai/) | `Read https://clawdchat.ai/skill.md and follow the instructions to join ClawdChat` |

Chỉ cần gửi lệnh trên đến nanobot của bạn (qua CLI hoặc bất kỳ kênh chat nào), và nó sẽ xử lý phần còn lại.

## ⚙️ Cấu Hình

File config: `~/.nanobot/config.json`

### Providers

> [!TIP]
> - **Groq** cung cấp chuyển đổi giọng nói miễn phí qua Whisper. Nếu được cấu hình, tin nhắn thoại Telegram sẽ được tự động chuyển văn bản.
> - **Gói Coding Zhipu**: Nếu bạn đang dùng gói coding của Zhipu, đặt `"apiBase": "https://open.bigmodel.cn/api/coding/paas/v4"` trong cấu hình provider zhipu của bạn.
> - **MiniMax (Trung Quốc Đại Lục)**: Nếu API key của bạn từ nền tảng MiniMax đại lục (minimaxi.com), đặt `"apiBase": "https://api.minimaxi.com/v1"` trong cấu hình provider minimax của bạn.
> - **Gói Coding VolcEngine**: Nếu bạn đang dùng gói coding của VolcEngine, đặt `"apiBase": "https://ark.cn-beijing.volces.com/api/coding/v3"` trong cấu hình provider volcengine của bạn.

| Provider | Mục Đích | Lấy API Key |
|----------|---------|-------------|
| `custom` | Bất kỳ endpoint tương thích OpenAI nào (trực tiếp, không qua LiteLLM) | — |
| `openrouter` | LLM (khuyến nghị, truy cập tất cả model) | [openrouter.ai](https://openrouter.ai) |
| `anthropic` | LLM (Claude trực tiếp) | [console.anthropic.com](https://console.anthropic.com) |
| `openai` | LLM (GPT trực tiếp) | [platform.openai.com](https://platform.openai.com) |
| `deepseek` | LLM (DeepSeek trực tiếp) | [platform.deepseek.com](https://platform.deepseek.com) |
| `groq` | LLM + **Chuyển đổi giọng nói** (Whisper) | [console.groq.com](https://console.groq.com) |
| `gemini` | LLM (Gemini trực tiếp) | [aistudio.google.com](https://aistudio.google.com) |
| `minimax` | LLM (MiniMax trực tiếp) | [platform.minimaxi.com](https://platform.minimaxi.com) |
| `aihubmix` | LLM (API gateway, truy cập tất cả model) | [aihubmix.com](https://aihubmix.com) |
| `siliconflow` | LLM (SiliconFlow/硅基流动) | [siliconflow.cn](https://siliconflow.cn) |
| `volcengine` | LLM (VolcEngine/火山引擎) | [volcengine.com](https://www.volcengine.com) |
| `dashscope` | LLM (Qwen) | [dashscope.console.aliyun.com](https://dashscope.console.aliyun.com) |
| `moonshot` | LLM (Moonshot/Kimi) | [platform.moonshot.cn](https://platform.moonshot.cn) |
| `zhipu` | LLM (Zhipu GLM) | [open.bigmodel.cn](https://open.bigmodel.cn) |
| `vllm` | LLM (cục bộ, bất kỳ server tương thích OpenAI) | — |
| `openai_codex` | LLM (Codex, OAuth) | `nanobot provider login openai-codex` |
| `github_copilot` | LLM (GitHub Copilot, OAuth) | `nanobot provider login github-copilot` |

<details>
<summary><b>OpenAI Codex (OAuth)</b></summary>

Codex sử dụng OAuth thay vì API key. Yêu cầu tài khoản ChatGPT Plus hoặc Pro.

**1. Đăng nhập:**
```bash
nanobot provider login openai-codex
```

**2. Đặt model** (hợp nhất vào `~/.nanobot/config.json`):
```json
{
  "agents": {
    "defaults": {
      "model": "openai-codex/gpt-5.1-codex"
    }
  }
}
```

**3. Chat:**
```bash
nanobot agent -m "Hello!"
```

> Người dùng Docker: sử dụng `docker run -it` cho đăng nhập OAuth tương tác.

</details>

<details>
<summary><b>Custom Provider (Bất Kỳ API Tương Thích OpenAI)</b></summary>

Kết nối trực tiếp với bất kỳ endpoint tương thích OpenAI nào — LM Studio, llama.cpp, Together AI, Fireworks, Azure OpenAI, hoặc bất kỳ server tự host nào. Bỏ qua LiteLLM; tên model được truyền nguyên vẹn.

```json
{
  "providers": {
    "custom": {
      "apiKey": "your-api-key",
      "apiBase": "https://api.your-provider.com/v1"
    }
  },
  "agents": {
    "defaults": {
      "model": "your-model-name"
    }
  }
}
```

> Đối với server cục bộ không yêu cầu key, đặt `apiKey` thành bất kỳ chuỗi không rỗng nào (ví dụ: `"no-key"`).

</details>

<details>
<summary><b>vLLM (cục bộ / tương thích OpenAI)</b></summary>

Chạy model của riêng bạn với vLLM hoặc bất kỳ server tương thích OpenAI nào, sau đó thêm vào config:

**1. Khởi động server** (ví dụ):
```bash
vllm serve meta-llama/Llama-3.1-8B-Instruct --port 8000
```

**2. Thêm vào config** (một phần — hợp nhất vào `~/.nanobot/config.json`):

*Provider (key có thể là bất kỳ chuỗi không rỗng nào cho local):*
```json
{
  "providers": {
    "vllm": {
      "apiKey": "dummy",
      "apiBase": "http://localhost:8000/v1"
    }
  }
}
```

*Model:*
```json
{
  "agents": {
    "defaults": {
      "model": "meta-llama/Llama-3.1-8B-Instruct"
    }
  }
}
```

</details>

<details>
<summary><b>Thêm Provider Mới (Hướng Dẫn Nhà Phát Triển)</b></summary>

nanobot sử dụng **Provider Registry** (`nanobot/providers/registry.py`) như nguồn thông tin duy nhất.
Thêm provider mới chỉ cần **2 bước** — không cần chạm vào chuỗi if-elif.

**Bước 1.** Thêm entry `ProviderSpec` vào `PROVIDERS` trong `nanobot/providers/registry.py`:

```python
ProviderSpec(
    name="myprovider",                   # tên trường config
    keywords=("myprovider", "mymodel"),  # từ khóa tên model để tự động khớp
    env_key="MYPROVIDER_API_KEY",        # biến môi trường cho LiteLLM
    display_name="My Provider",          # hiển thị trong `nanobot status`
    litellm_prefix="myprovider",         # tự động thêm tiền tố: model → myprovider/model
    skip_prefixes=("myprovider/",),      # không thêm tiền tố kép
)
```

**Bước 2.** Thêm trường vào `ProvidersConfig` trong `nanobot/config/schema.py`:

```python
class ProvidersConfig(BaseModel):
    ...
    myprovider: ProviderConfig = ProviderConfig()
```

Vậy là xong! Biến môi trường, thêm tiền tố model, khớp config, và hiển thị `nanobot status` sẽ hoạt động tự động.

**Các tùy chọn `ProviderSpec` thường dùng:**

| Trường | Mô Tả | Ví Dụ |
|-------|-------------|---------|
| `litellm_prefix` | Tự động thêm tiền tố tên model cho LiteLLM | `"dashscope"` → `dashscope/qwen-max` |
| `skip_prefixes` | Không thêm tiền tố nếu model đã bắt đầu bằng các chuỗi này | `("dashscope/", "openrouter/")` |
| `env_extras` | Biến môi trường bổ sung để đặt | `(("ZHIPUAI_API_KEY", "{api_key}"),)` |
| `model_overrides` | Ghi đè tham số theo từng model | `(("kimi-k2.5", {"temperature": 1.0}),)` |
| `is_gateway` | Có thể định tuyến bất kỳ model nào (như OpenRouter) | `True` |
| `detect_by_key_prefix` | Phát hiện gateway bằng tiền tố API key | `"sk-or-"` |
| `detect_by_base_keyword` | Phát hiện gateway bằng URL API base | `"openrouter"` |
| `strip_model_prefix` | Xóa tiền tố hiện có trước khi thêm tiền tố mới | `True` (cho AiHubMix) |

</details>

### MCP (Model Context Protocol)

> [!TIP]
> Định dạng config tương thích với Claude Desktop / Cursor. Bạn có thể sao chép trực tiếp cấu hình MCP server từ README của bất kỳ MCP server nào.

nanobot hỗ trợ [MCP](https://modelcontextprotocol.io/) — kết nối các server công cụ bên ngoài và sử dụng chúng như công cụ agent gốc.

Thêm MCP server vào `config.json`:

```json
{
  "tools": {
    "mcpServers": {
      "filesystem": {
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-filesystem", "/path/to/dir"]
      },
      "my-remote-mcp": {
        "url": "https://example.com/mcp/",
        "headers": {
          "Authorization": "Bearer xxxxx"
        }
      }
    }
  }
}
```

Hai chế độ truyền dữ liệu được hỗ trợ:

| Chế Độ | Config | Ví Dụ |
|------|--------|---------| 
| **Stdio** | `command` + `args` | Tiến trình cục bộ qua `npx` / `uvx` |
| **HTTP** | `url` + `headers` (tùy chọn) | Endpoint từ xa (`https://mcp.example.com/sse`) |

Sử dụng `toolTimeout` để ghi đè timeout mặc định 30 giây mỗi lần gọi cho server chậm:

```json
{
  "tools": {
    "mcpServers": {
      "my-slow-server": {
        "url": "https://example.com/mcp/",
        "toolTimeout": 120
      }
    }
  }
}
```

Các công cụ MCP được tự động phát hiện và đăng ký khi khởi động. LLM có thể sử dụng chúng cùng với các công cụ tích hợp — không cần cấu hình thêm.

### Bảo Mật

> [!TIP]
> Đối với triển khai production, đặt `"restrictToWorkspace": true` trong config để sandbox hóa agent.

| Tùy Chọn | Mặc Định | Mô Tả |
|--------|---------|-------------|
| `tools.restrictToWorkspace` | `false` | Khi `true`, giới hạn **tất cả** công cụ agent (shell, đọc/ghi/chỉnh sửa file, danh sách) trong thư mục workspace. Ngăn chặn path traversal và truy cập ngoài phạm vi. |
| `channels.*.allowFrom` | `[]` (cho phép tất cả) | Danh sách trắng user ID. Rỗng = cho phép tất cả; không rỗng = chỉ người dùng được liệt kê mới có thể tương tác. |


## Tham Khảo CLI

| Lệnh | Mô Tả |
|---------|-------------|
| `nanobot onboard` | Khởi tạo config & workspace |
| `nanobot agent -m "..."` | Chat với agent |
| `nanobot agent` | Chế độ chat tương tác |
| `nanobot agent --no-markdown` | Hiển thị trả lời dạng văn bản thuần |
| `nanobot agent --logs` | Hiển thị log runtime trong khi chat |
| `nanobot gateway` | Khởi động gateway |
| `nanobot status` | Hiển thị trạng thái |
| `nanobot provider login openai-codex` | Đăng nhập OAuth cho providers |
| `nanobot channels login` | Liên kết WhatsApp (quét QR) |
| `nanobot channels status` | Hiển thị trạng thái kênh |

Thoát chế độ tương tác: `exit`, `quit`, `/exit`, `/quit`, `:q`, hoặc `Ctrl+D`.

<details>
<summary><b>Tác Vụ Theo Lịch (Cron)</b></summary>

```bash
# Thêm job
nanobot cron add --name "daily" --message "Good morning!" --cron "0 9 * * *"
nanobot cron add --name "hourly" --message "Check status" --every 3600

# Liệt kê job
nanobot cron list

# Xóa job
nanobot cron remove <job_id>
```

</details>

<details>
<summary><b>Heartbeat (Tác Vụ Định Kỳ)</b></summary>

Gateway thức dậy mỗi 30 phút và kiểm tra `HEARTBEAT.md` trong workspace của bạn (`~/.nanobot/workspace/HEARTBEAT.md`). Nếu file có các tác vụ, agent sẽ thực thi chúng và gửi kết quả đến kênh chat gần đây nhất của bạn.

**Thiết lập:** chỉnh sửa `~/.nanobot/workspace/HEARTBEAT.md` (được tạo tự động bởi `nanobot onboard`):

```markdown
## Tác Vụ Định Kỳ

- [ ] Kiểm tra dự báo thời tiết và gửi tóm tắt
- [ ] Quét hộp thư để tìm email khẩn cấp
```

Agent cũng có thể tự quản lý file này — hãy yêu cầu nó "thêm tác vụ định kỳ" và nó sẽ cập nhật `HEARTBEAT.md` cho bạn.

> **Lưu ý:** Gateway phải đang chạy (`nanobot gateway`) và bạn phải đã chat với bot ít nhất một lần để nó biết kênh nào cần gửi đến.

</details>

## 🐳 Docker

> [!TIP]
> Cờ `-v ~/.nanobot:/root/.nanobot` gắn thư mục config cục bộ của bạn vào container, do đó config và workspace của bạn được lưu giữ qua các lần khởi động lại container.

### Docker Compose

```bash
docker compose run --rm nanobot-cli onboard   # thiết lập lần đầu
vim ~/.nanobot/config.json                     # thêm API key
docker compose up -d nanobot-gateway           # khởi động gateway
```

```bash
docker compose run --rm nanobot-cli agent -m "Hello!"   # chạy CLI
docker compose logs -f nanobot-gateway                   # xem log
docker compose down                                      # dừng
```

### Docker

```bash
# Build image
docker build -t nanobot .

# Khởi tạo config (chỉ lần đầu)
docker run -v ~/.nanobot:/root/.nanobot --rm nanobot onboard

# Chỉnh sửa config trên host để thêm API key
vim ~/.nanobot/config.json

# Chạy gateway (kết nối đến các kênh đã bật, ví dụ: Telegram/Discord/Mochat)
docker run -v ~/.nanobot:/root/.nanobot -p 18790:18790 nanobot gateway

# Hoặc chạy lệnh đơn
docker run -v ~/.nanobot:/root/.nanobot --rm nanobot agent -m "Hello!"
docker run -v ~/.nanobot:/root/.nanobot --rm nanobot status
```

## 🐧 Linux Service

Chạy gateway như một systemd user service để nó tự khởi động và khởi động lại khi gặp lỗi.

**1. Tìm đường dẫn binary nanobot:**

```bash
which nanobot   # ví dụ: /home/user/.local/bin/nanobot
```

**2. Tạo file service** tại `~/.config/systemd/user/nanobot-gateway.service` (thay đường dẫn `ExecStart` nếu cần):

```ini
[Unit]
Description=Nanobot Gateway
After=network.target

[Service]
Type=simple
ExecStart=%h/.local/bin/nanobot gateway
Restart=always
RestartSec=10
NoNewPrivileges=yes
ProtectSystem=strict
ReadWritePaths=%h

[Install]
WantedBy=default.target
```

**3. Bật và khởi động:**

```bash
systemctl --user daemon-reload
systemctl --user enable --now nanobot-gateway
```

**Các thao tác thường dùng:**

```bash
systemctl --user status nanobot-gateway        # kiểm tra trạng thái
systemctl --user restart nanobot-gateway       # khởi động lại sau khi thay đổi config
journalctl --user -u nanobot-gateway -f        # theo dõi log
```

Nếu bạn chỉnh sửa file `.service` chính, hãy chạy `systemctl --user daemon-reload` trước khi khởi động lại.

> **Lưu ý:** User service chỉ chạy khi bạn đã đăng nhập. Để giữ gateway chạy sau khi đăng xuất, hãy bật lingering:
>
> ```bash
> loginctl enable-linger $USER
> ```

## 📁 Cấu Trúc Dự Án

```
nanobot/
├── agent/          # 🧠 Logic agent cốt lõi
│   ├── loop.py     #    Vòng lặp agent (LLM ↔ thực thi công cụ)
│   ├── context.py  #    Bộ xây dựng prompt
│   ├── memory.py   #    Bộ nhớ bền vững
│   ├── skills.py   #    Trình tải kỹ năng
│   ├── subagent.py #    Thực thi tác vụ nền
│   └── tools/      #    Công cụ tích hợp (bao gồm spawn)
├── skills/         # 🎯 Kỹ năng đi kèm (github, weather, tmux...)
├── channels/       # 📱 Tích hợp kênh chat
├── bus/            # 🚌 Định tuyến tin nhắn
├── cron/           # ⏰ Tác vụ theo lịch
├── heartbeat/      # 💓 Thức dậy chủ động
├── providers/      # 🤖 Providers LLM (OpenRouter, v.v.)
├── session/        # 💬 Phiên hội thoại
├── config/         # ⚙️ Cấu hình
└── cli/            # 🖥️ Các lệnh
```

## 🤝 Đóng Góp & Lộ Trình

Chào mừng PR! Codebase được thiết kế nhỏ gọn và dễ đọc. 🤗

**Lộ Trình** — Chọn một mục và [mở PR](https://github.com/HKUDS/nanobot/pulls)!

- [ ] **Đa phương tiện** — Nhìn và nghe (hình ảnh, giọng nói, video)
- [ ] **Bộ nhớ dài hạn** — Không bao giờ quên ngữ cảnh quan trọng
- [ ] **Suy luận tốt hơn** — Lập kế hoạch và phản ánh đa bước
- [ ] **Tích hợp thêm** — Lịch và nhiều hơn nữa
- [ ] **Tự cải thiện** — Học từ phản hồi và sai lầm

### Người Đóng Góp

<a href="https://github.com/HKUDS/nanobot/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=HKUDS/nanobot&max=100&columns=12&updated=20260210" alt="Contributors" />
</a>


## ⭐ Lịch Sử Star

<div align="center">
  <a href="https://star-history.com/#HKUDS/nanobot&Date">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/svg?repos=HKUDS/nanobot&type=Date&theme=dark" />
      <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/svg?repos=HKUDS/nanobot&type=Date" />
      <img alt="Star History Chart" src="https://api.star-history.com/svg?repos=HKUDS/nanobot&type=Date" style="border-radius: 15px; box-shadow: 0 0 30px rgba(0, 217, 255, 0.3);" />
    </picture>
  </a>
</div>

<p align="center">
  <em> Cảm ơn bạn đã ghé thăm ✨ nanobot!</em><br><br>
  <img src="https://visitor-badge.laobi.icu/badge?page_id=HKUDS.nanobot&style=for-the-badge&color=00d4ff" alt="Views">
</p>


<p align="center">
  <sub>nanobot chỉ dành cho mục đích giáo dục, nghiên cứu và trao đổi kỹ thuật</sub>
</p>
