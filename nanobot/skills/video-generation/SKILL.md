---
name: video-generation
description: 使用 DeerAPI (WaveSpeed AI) 生成、处理和超分视频。用于创建 Hero 背景视频、视频链和 4K 超分。
---

# 视频生成技能

本技能指导如何使用 WaveSpeed AI 平台生成和处理视频，包括图生视频、视频续写、视频链生成和 4K 超分。

---

## 1. 支持的模型

### 图生视频 (Image-to-Video)

| 模型 | API 路径 | 时长 | 特点 |
|------|---------|------|------|
| Wan-2.2 | `wavespeed-ai/wan-2.2/i2v-480p` | 5s/8s | 高质量、支持长视频 |
| Wan-2.2 720p | `wavespeed-ai/wan-2.2/i2v-720p` | 5s/8s | 更高分辨率 |
| Hailuo 2.3 | `minimax/hailuo-2.3/i2v-standard` | 6s | 快速、效果好 |
| Kling 1.6 | `kuaishou/kling-v1.6/i2v-pro` | 5s/10s | 稳定、细节丰富 |

### 视频超分 (Video Upscaling)

| 模型 | API 路径 | 分辨率选项 |
|------|---------|-----------|
| Video Upscaler Pro | `wavespeed-ai/video-upscaler-pro` | 720p, 1080p, 2k, 4k |

---

## 2. 基础工作流

### 2.1 图生视频

```python
import requests
import time

API_KEY = "your_api_key"
BASE_URL = "https://api.wavespeed.ai/api/v3"
HEADERS = {"Authorization": f"Bearer {API_KEY}"}
JSON_HEADERS = {**HEADERS, "Content-Type": "application/json"}

# 1. 上传图片
def upload_image(image_path):
    with open(image_path, 'rb') as f:
        r = requests.post(
            f"{BASE_URL}/media/upload/binary",
            headers=HEADERS,
            files={"file": f}
        )
    return r.json()["data"]["download_url"]

# 2. 提交视频生成任务
def submit_i2v_task(image_url, prompt, model="wavespeed-ai/wan-2.2/i2v-480p"):
    payload = {
        "image": image_url,
        "prompt": prompt,
        "duration": 5,  # 5 或 8 秒
        "enable_prompt_expansion": False
    }
    r = requests.post(f"{BASE_URL}/{model}", headers=JSON_HEADERS, json=payload)
    return r.json()["data"]

# 3. 轮询结果
def poll_result(task_id, get_url=None):
    poll_url = get_url or f"{BASE_URL}/predictions/{task_id}"
    while True:
        r = requests.get(poll_url, headers=HEADERS)
        data = r.json()["data"]
        if data["status"] == "completed":
            return data["outputs"][0]
        elif data["status"] == "failed":
            raise Exception(f"Task failed: {data}")
        time.sleep(5)

# 4. 下载视频
def download_video(video_url, output_path):
    r = requests.get(video_url, stream=True)
    with open(output_path, 'wb') as f:
        for chunk in r.iter_content(chunk_size=8192):
            f.write(chunk)
```

### 2.2 视频超分到 4K

```python
# 1. 上传视频
video_url = upload_video(video_path)  # 同 upload_image

# 2. 提交超分任务
payload = {
    "video": video_url,
    "target_resolution": "4k"  # 可选: 720p, 1080p, 2k, 4k
}
r = requests.post(
    f"{BASE_URL}/wavespeed-ai/video-upscaler-pro",
    headers=JSON_HEADERS,
    json=payload
)
task_data = r.json()["data"]

# 3. 轮询并下载（同上）
```

---

## 3. 视频链生成

视频链是指通过视频续写技术，将多个短视频连接成一个连贯的长视频。

### 核心概念

1. **首帧提取**: 使用 FFmpeg 提取视频最后一帧作为下一段的起始
2. **视频续写**: 使用相同的 prompt 风格生成连贯的续集
3. **视频拼接**: 使用 FFmpeg 无损拼接

### 示例：4 段视频链

```python
# 提取最后一帧
def extract_last_frame(video_path, output_path):
    import subprocess
    cmd = [
        "ffmpeg", "-y", "-sseof", "-0.1",
        "-i", video_path,
        "-vframes", "1", "-q:v", "2",
        output_path
    ]
    subprocess.run(cmd, check=True)

# 生成视频链
def generate_chain(initial_image, prompt, num_segments=4):
    videos = []
    current_image = initial_image
    
    for i in range(num_segments):
        # 上传当前图片
        image_url = upload_image(current_image)
        
        # 生成视频
        task = submit_i2v_task(image_url, prompt)
        video_url = poll_result(task["id"], task["urls"]["get"])
        
        # 下载视频
        video_path = f"v{i+1}.mp4"
        download_video(video_url, video_path)
        videos.append(video_path)
        
        # 提取最后一帧用于下一段
        current_image = f"v{i+1}_last_frame.jpg"
        extract_last_frame(video_path, current_image)
    
    return videos

# 拼接视频
def concat_videos(video_list, output_path):
    import subprocess
    # 创建文件列表
    with open("concat_list.txt", "w") as f:
        for v in video_list:
            f.write(f"file '{v}'\\n")
    
    cmd = [
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", "concat_list.txt", "-c", "copy",
        output_path
    ]
    subprocess.run(cmd, check=True)
```

---

## 4. 项目脚本说明

项目 `scripts/` 目录下的脚本：

| 脚本 | 功能 |
|------|------|
| `generate_hero_video.py` | 从海报图生成 Hero 背景视频 |
| `upscale_hero_video.py` | 将视频超分到 4K |
| `generate_latest_chains.py` | 生成完整视频链 |
| `wan_v1.py` ~ `wan_v4.py` | Wan 模型单段生成 |
| `upscale_intro_native_4k.py` | Intro 视频超分 |
| `upscale_loop_native_4k.py` | Loop 视频超分 |

---

## 5. 最佳实践

### Prompt 编写

```
# 好的 prompt 结构
[动作描述], [氛围/风格], [细节], [效果]

# 示例
"Gentle flowing motion with glowing particles moving slowly across the scene, 
subtle pulsing neon light effects, ethereal and dreamy atmosphere, 
smooth ambient movement, futuristic cyberpunk feeling"
```

### 注意事项

1. **避免过度后处理**: 不要用 FFmpeg 强制拉伸分辨率，使用原生 4K 输出
2. **保持风格一致**: 视频链各段使用相同的 prompt 风格
3. **预留缓冲**: 超分任务可能需要 10-15 分钟，设置足够的轮询超时
4. **备份原始文件**: 超分前备份原始视频

### 常见问题

| 问题 | 解决方案 |
|------|---------|
| 超分后边缘发虚 | 使用 `target_resolution: "4k"` 原生输出 |
| 视频链不连贯 | 确保提取的是真正的最后一帧 |
| 任务超时 | 增加 `max_attempts` 或检查 API 状态 |
| 上传失败 | 检查文件大小限制（通常 500MB） |

---

## 6. API 密钥配置

将 API 密钥存储在环境变量或 `.env` 文件中：

```bash
# .env
WAVESPEED_KEY=your_api_key_here
```

```python
import os
API_KEY = os.getenv("WAVESPEED_KEY")
```

**注意**: 不要将 API 密钥硬编码在脚本中或提交到版本控制。

---

*最后更新：2026-02-07*
