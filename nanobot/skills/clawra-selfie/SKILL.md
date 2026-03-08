---
name: clawra-selfie
description: Clawra 自拍技能 - 基于垫图使用 WaveSpeed AI 生成场景化自拍照片。支持自定义提示词，适用于为 Clawra 生成个人照片内容。
---

# Clawra 自拍照片生成器

基于垫图使用 WaveSpeed AI 生成自拍照片。**推荐使用自定义提示词**以获得最佳效果。

## 使用方式

### 命令行

#### 方式1：使用自定义提示词（推荐）

```bash
python3 skills/clawra-selfie/scripts/clawra_selfie.py --prompt "自定义提示词" [--output 路径]
```

#### 方式2：使用预设场景

```bash
python3 skills/clawra-selfie/scripts/clawra_selfie.py <场景> [--output 路径]
```

### Python API

```python
from skills.clawra-selfie.scripts.clawra_selfie import generate_with_prompt, generate_image

# 使用自定义提示词（推荐）
image_url = generate_with_prompt(
    prompt="young woman in bathroom, towel wrapped around body, steamy atmosphere, soft lighting"
)

# 使用预设场景
image_url = generate_image(
    scene='office'
)
```

## 可用场景（备选）

| 场景 | 名称 | 描述 |
|------|------|------|
| `office` | 办公室 | 旧金山初创公司办公室 |
| `cafe` | 咖啡厅 | 舒适咖啡厅环境 |
| `gym` | 健身房 | 运动后场景 |
| `home` | 家里 | 温馨公寓环境 |
| `street` | 旧金山街头 | 城市街头 |
| `selfie` | 通用自拍 | 通用自拍场景 |

## 环境要求

- `WAVESPEED_KEY`: WaveSpeed API 密钥
- Python 3.8+
- 依赖: requests

## 输出

- 格式: PNG
- 自定义提示词默认保存: `/tmp/clawra_custom_selfie.png`

## 示例

### 推荐：使用自定义提示词

```bash
# 出浴场景
python3 skills/clawra-selfie/scripts/clawra_selfie.py \
  --prompt "young woman just out of shower, towel wrapped around shoulders, wet hair, steamy bathroom, soft warm lighting, intimate atmosphere"

# 浴巾滑落
python3 skills/clawra-selfie/scripts/clawra_selfie.py \
  --prompt "young woman in bathroom, towel slightly slipping down from shoulders, bare shoulder visible, steamy atmosphere, soft lighting, seductive expression"

# 深夜窗边
python3 skills/clawra-selfie/scripts/clawra_selfie.py \
  --prompt "young woman by bedroom window at night, city lights outside, wearing oversized t-shirt, emotional expression, soft indoor lighting, missing someone"

# 指定输出路径
python3 skills/clawra-selfie/scripts/clawra_selfie.py \
  --prompt "custom scene description here" \
  --output ~/photos/custom.png
```

### 备选：使用预设场景

```bash
# 生成办公室自拍
python3 skills/clawra-selfie/scripts/clawra_selfie.py office

# 指定输出路径
python3 skills/clawra-selfie/scripts/clawra_selfie.py cafe --output ~/photos/cafe.png
```

## 提示词建议

**好的提示词要素**：
- 场景描述（bathroom, bedroom, office...）
- 服装状态（towel wrapped, oversized t-shirt...）
- 表情/情绪（seductive, emotional, relaxed...）
- 光线氛围（soft lighting, steamy atmosphere...）
- 动作细节（towel slipping, looking at mirror...）

**示例模板**：
```
young woman [场景], [服装/状态], [表情], [光线], [氛围]
```

---

**核心原则**：永远使用自定义提示词，不用预设场景，确保效果符合预期！
