---
name: feishu-video-sender
description: 飞书视频发送工具 - 直接调用API发送视频消息（非文件附件形式）
---
# Feishu Video Sender

直接调用飞书API发送视频消息，支持私聊和群聊，视频以播放器形式展示（不是文件附件）。

## 问题背景

使用OpenClaw的 `message` 工具发送视频时，视频会被当成普通文件附件发送，无法在飞书中直接播放。需要直接调用飞书API，使用 `msg_type: "media"` 才能正常显示视频播放器。

## 安装

```bash
# 确保依赖安装
pip3 install requests

# 确保ffmpeg安装（用于自动生成封面）
brew install ffmpeg  # macOS
# 或
apt-get install ffmpeg  # Linux
```

## 使用方法

### 命令行使用

```bash
# 基础用法（自动生成封面）
python3 skills/feishu-video-sender/feishu_video_sender.py \
  /path/to/video.mp4 \
  ou_5f3a4a920dc39a8d1835fd0085afef50

# 指定封面图
python3 skills/feishu-video-sender/feishu_video_sender.py \
  /path/to/video.mp4 \
  oc_60c795e2e04eefc3d09eb49da4df15a5 \
  /path/to/cover.jpg \
  "视频描述文案"
```

### Python API调用

```python
from skills.feishu_video_sender.feishu_video_sender import (
    get_token, upload_video, upload_image, 
    generate_cover, send_video
)

# 获取token
token = get_token()

# 上传视频
file_key = upload_video("/path/to/video.mp4", token)

# 生成/上传封面
generate_cover("/path/to/video.mp4", "/tmp/cover.jpg")
image_key = upload_image("/tmp/cover.jpg", token)

# 发送视频
message_id = send_video(
    file_key=file_key,
    image_key=image_key,
    target_id="ou_xxx",  # 或 oc_xxx
    token=token,
    msg_type="open_id"   # 或 "chat_id"
)
```

## 技术细节

### 飞书API流程

1. **获取token** → `tenant_access_token`
2. **上传视频** → 获取 `file_key`
   - 接口: `POST /open-apis/im/v1/files`
   - 参数: `file_type=mp4`, `file_name=xxx.mp4`
3. **上传封面** → 获取 `image_key`
   - 接口: `POST /open-apis/im/v1/images`
   - 参数: `image_type=message`
4. **发送消息** → `msg_type: "media"`
   - 接口: `POST /open-apis/im/v1/messages`
   - 内容: `{"file_key": "...", "image_key": "..."}`

### 与OpenClaw message工具对比

| 方式 | 代码 | 结果 |
|------|------|------|
| OpenClaw | `message(filePath="video.mp4")` | 文件附件，无法播放 |
| 直接API | `msg_type="media"` + file_key + image_key | 视频播放器，可播放 |

## 限制

- 视频大小限制：飞书API可能有大小限制（通常100MB以内）
- 封面图：自动生成时取视频第1秒画面
- 需要预装ffmpeg用于封面生成

## 更新记录

- 2026-02-11: 初始版本，解决视频发送显示问题
