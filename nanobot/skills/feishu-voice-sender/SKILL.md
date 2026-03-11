---
name: feishu-voice-sender
description: 飞书语音消息发送工具 - 将音频文件以语音条形式发送到飞书（非文件附件）
---

# Feishu Voice Sender

飞书语音消息发送工具 - 将 MP3 音频以语音条形式发送到飞书聊天。

## 功能

- 将 MP3 转换为飞书语音格式（AMR）
- 上传到飞书获取 file_key
- 以语音条形式发送（msg_type: voice）
- 支持私聊和群聊

## 使用方法

### Python API

```python
from skills.feishu_voice_sender import send_voice_message

# 发送语音到群聊
result = send_voice_message(
    audio_path="/tmp/voice.mp3",
    target_id="oc_xxx",  # 群ID
    target_type="chat"
)

# 发送语音到私聊
result = send_voice_message(
    audio_path="/tmp/voice.mp3",
    target_id="ou_xxx",  # 用户ID
    target_type="user"
)
```

### 命令行

```bash
# 发送到群聊
python3 skills/feishu-voice-sender/feishu_voice_sender.py /tmp/voice.mp3 oc_xxx --chat

# 发送到私聊
python3 skills/feishu-voice-sender/feishu_voice_sender.py /tmp/voice.mp3 ou_xxx --user
```

## 技术细节

### 飞书语音消息流程

1. **转换格式** - MP3 → AMR（飞书语音格式）
2. **上传音频** - 获取 file_key
3. **发送消息** - msg_type: "voice"

### 与音频文件的区别

| 方式 | 消息类型 | 用户体验 |
|------|----------|----------|
| 语音条 | `msg_type: "voice"` | ✅ 点击播放，类似微信语音 |
| 音频文件 | `msg_type: "file"` | ❌ 下载后播放 |

## 依赖

```bash
# 系统依赖
ffmpeg  # 用于格式转换

# Python依赖
pip install requests
```

## 配置

通过环境变量读取飞书凭证：
- `NANOBOT_CHANNELS__FEISHU__APP_ID`
- `NANOBOT_CHANNELS__FEISHU__APP_SECRET`
