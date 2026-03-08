---
name: clawra-video-selfie
description: 基于 Clawra 垫图生成场景化动态自拍视频。使用 WaveSpeed AI Seedance 模型，支持办公室、咖啡厅、健身房、家里、街头等场景。适用于为 Clawra 生成个人动态视频内容。
---

# Clawra 自拍视频生成器

基于垫图使用 WaveSpeed AI 生成场景化动态自拍视频。

## 使用方式

### 命令行

```bash
python3 skills/clawra-video-selfie/scripts/clawra_video_selfie.py <场景> [--duration 秒数] [--output 路径] [--ref 垫图路径]
```

### Python API

```python
from skills.clawra-video-selfie.scripts.clawra_video_selfie import generate_video

# 使用默认垫图
video_path = generate_video(
    scene='office',      # 场景
    duration=5,          # 时长(秒)
    output_path=None     # 输出路径(可选)
)

# 使用自定义垫图（如生成的照片）
video_path = generate_video(
    scene='office',
    duration=5,
    output_path=None,
    ref_image='/path/to/photo.png'  # 自定义垫图路径
)
```

## 可用场景

| 场景 | 名称 | 描述 |
|------|------|------|
| `office` | 办公室 | 旧金山初创公司办公室 |
| `cafe` | 咖啡厅 | 舒适咖啡厅环境 |
| `gym` | 健身房 | 运动后场景 |
| `home` | 家里 | 温馨公寓环境 |
| `street` | 街头 | 旧金山街头 |

## 环境要求

- `WAVESPEED_KEY`: WaveSpeed API 密钥
- Python 3.8+
- 依赖: requests

## 输出

- 格式: MP4 (H.264)
- 分辨率: 480p
- 比例: 竖屏
- 时长: 5 或 8 秒
- 默认保存: `/tmp/clawra_{场景}_video.mp4`

## 示例

```bash
# 使用默认垫图生成5秒办公室视频
python3 skills/clawra-video-selfie/scripts/clawra_video_selfie.py office

# 使用自定义照片作为垫图
python3 skills/clawra-video-selfie/scripts/clawra_video_selfie.py office --ref ~/photos/my_selfie.png

# 生成8秒视频并指定输出路径
python3 skills/clawra-video-selfie/scripts/clawra_video_selfie.py cafe --duration 8 --output ~/videos/cafe.mp4

# 完整流程：先用照片技能生成照片，再用照片生成视频
python3 skills/clawra-selfie/scripts/clawra_selfie.py office --output /tmp/photo.png
python3 skills/clawra-video-selfie/scripts/clawra_video_selfie.py office --ref /tmp/photo.png
```

## 工作流建议

**照片+视频组合生成：**
1. 先用 `clawra-selfie` 生成场景照片
2. 再用该照片作为垫图，用 `clawra-video-selfie` 生成视频
3. 这样视频和照片场景更连贯一致
