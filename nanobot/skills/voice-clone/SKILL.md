---
name: voice-clone
description: 使用 WaveSpeed AI MiniMax Voice Clone API 克隆声音并生成语音。支持吴娜等特定人物的声音克隆。
---

# 声音克隆技能

本技能指导如何使用 WaveSpeed AI 的 MiniMax Voice Clone 服务进行声音克隆和语音合成。

---

## 1. 功能概述

- **声音克隆**：从 5-20 秒音频样本创建自定义声音
- **语音合成**：使用克隆的声音生成任意文本的语音
- **云端服务**：无需本地安装，API 直接调用

---

## 2. API 配置

### 基础配置

```python
import requests
import base64
import os
import time

# API 配置
WAVESPEED_KEY = os.getenv("WAVESPEED_KEY", "b9c67f3def268385bb9734970b11531f12ea24ae0d153859242e48ae46227668")
BASE_URL = "https://api.wavespeed.ai/api/v3"
HEADERS = {"Authorization": f"Bearer {WAVESPEED_KEY}"}
JSON_HEADERS = {**HEADERS, "Content-Type": "application/json"}
```

---

## 3. 核心工作流

### 3.1 克隆声音（首次使用）

```python
def clone_voice(audio_path, voice_id, text="我是克隆的声音，很高兴为你服务。"):
    """
    克隆声音并创建 voice_id
    
    Args:
        audio_path: 音频样本路径（MP3/WAV，5-20秒）
        voice_id: 自定义声音ID（如 "wuna-001"）
        text: 测试文本
    
    Returns:
        request_id: 任务ID，用于查询结果
    """
    # 读取音频并转为 base64
    with open(audio_path, 'rb') as f:
        audio_base64 = base64.b64encode(f.read()).decode('utf-8')
    
    url = f"{BASE_URL}/minimax/voice-clone"
    payload = {
        "model": "speech-02-hd",
        "custom_voice_id": voice_id,
        "text": text,
        "audio": audio_base64,
        "need_noise_reduction": False,
        "need_volume_normalization": False,
        "accuracy": 0.8
    }
    
    response = requests.post(url, json=payload, headers=JSON_HEADERS)
    result = response.json()
    
    if response.status_code == 200:
        return result['data']['id']
    else:
        raise Exception(f"克隆失败: {result}")
```

### 3.2 使用克隆的声音生成语音

```python
def generate_speech(text, voice_id, model="speech-02-hd"):
    """
    使用克隆的声音生成语音
    
    Args:
        text: 要生成的文本
        voice_id: 克隆的声音ID
        model: 语音合成模型
    
    Returns:
        audio_url: 生成的音频URL
    """
    url = f"{BASE_URL}/minimax/{model}"
    payload = {
        "text": text,
        "voice_id": voice_id,
        "language": "zh-CN"
    }
    
    response = requests.post(url, json=payload, headers=JSON_HEADERS)
    result = response.json()
    
    if response.status_code == 200:
        return result['data']['id'], result['data']['urls']['get']
    else:
        raise Exception(f"生成失败: {result}")
```

### 3.3 查询任务结果

```python
def poll_result(request_id, timeout=60):
    """
    轮询任务结果
    
    Args:
        request_id: 任务ID
        timeout: 最大等待时间（秒）
    
    Returns:
        audio_url: 音频下载URL
    """
    url = f"{BASE_URL}/predictions/{request_id}/result"
    start_time = time.time()
    
    while time.time() - start_time < timeout:
        response = requests.get(url, headers=HEADERS)
        result = response.json()
        
        status = result.get('data', {}).get('status')
        
        if status == 'completed':
            outputs = result.get('data', {}).get('outputs', [])
            return outputs[0] if outputs else None
        elif status == 'failed':
            raise Exception(f"任务失败: {result}")
        
        time.sleep(3)
    
    raise TimeoutError("任务超时")
```

### 3.4 下载音频

```python
def download_audio(audio_url, output_path):
    """
    下载音频文件
    
    Args:
        audio_url: 音频URL
        output_path: 保存路径
    """
    response = requests.get(audio_url, stream=True)
    with open(output_path, 'wb') as f:
        for chunk in response.iter_content(chunk_size=8192):
            f.write(chunk)
    return output_path
```

---

## 4. 完整使用示例

### 示例1：克隆吴娜的声音并生成口播

```python
# 配置
AUDIO_SAMPLE = "~/.nanobot/workspace/01-Projects/career-coaching/03-completed/短视频学习/吴娜短视频样例.mp3"
VOICE_ID = "wuna-001"
KOUBO_TEXT = """我是外企面试官。2026年求职，你一定要学会用人工智能！
不懂人工智能的简历直接被淘汰，会用的轻松拿下高薪offer！"""

# 步骤1：克隆声音（仅需执行一次）
print("步骤1: 克隆声音...")
clone_request_id = clone_voice(AUDIO_SAMPLE, VOICE_ID)
print(f"克隆任务已提交: {clone_request_id}")

# 等待克隆完成（可选，克隆结果会自动保存 voice_id）
time.sleep(5)

# 步骤2：使用克隆的声音生成语音
print("\n步骤2: 生成语音...")
tts_request_id, result_url = generate_speech(KOUBO_TEXT, VOICE_ID)
print(f"TTS任务已提交: {tts_request_id}")

# 步骤3：获取结果
print("\n步骤3: 等待结果...")
audio_url = poll_result(tts_request_id)
print(f"音频URL: {audio_url}")

# 步骤4：下载音频
print("\n步骤4: 下载音频...")
download_audio(audio_url, "/tmp/wuna_koubo.mp3")
print("✅ 音频已保存")
```

### 示例2：批量生成口播

```python
def batch_generate(voice_id, texts, output_dir="/tmp"):
    """批量生成语音"""
    results = []
    
    for i, text in enumerate(texts):
        print(f"生成 {i+1}/{len(texts)}...")
        
        # 提交任务
        request_id, _ = generate_speech(text, voice_id)
        
        # 等待结果
        audio_url = poll_result(request_id, timeout=120)
        
        # 下载
        output_path = f"{output_dir}/audio_{i+1:03d}.mp3"
        download_audio(audio_url, output_path)
        results.append(output_path)
        
        print(f"✅ 已保存: {output_path}")
    
    return results

# 批量生成
texts = [
    "第一段口播文本...",
    "第二段口播文本...",
    "第三段口播文本...",
]

batch_generate("wuna-001", texts)
```

---

## 5. 已配置的声音

| 声音ID | 来源 | 状态 | 说明 |
|--------|------|------|------|
| `wuna-001` | 吴娜短视频样例 | ✅ 可用 | 温柔知性带干练职业风格 |
| `zhuoran-001` | HiperOne | ✅ 可用 | *** |

---

## 6. 支持的模型

### 声音克隆
- **端点**: `POST /api/v3/minimax/voice-clone`
- **定价**: $0.5/次

### 语音合成
| 模型 | 特点 | 延迟 |
|------|------|------|
| `speech-02-hd` | 高清音质 | 中等 |
| `speech-02-turbo` | 低延迟 | 低 |
| `speech-2.6-hd` | 下一代高清，40+语言 | 中等 |
| `speech-2.6-turbo` | 超低延迟 | 极低 |

---

## 7. 音频样本要求

- **格式**: MP3、WAV
- **时长**: 5-20秒最佳
- **大小**: 建议不超过 1MB
- **质量要求**:
  - 清晰、无杂音
  - 无背景音乐
  - 单人声
  - 正常语速，避免喊叫或耳语

---

## 8. 常见问题

### Q: Voice ID 会过期吗？
A: 会。创建的 voice_id 需在 7 天内至少使用一次，否则会被删除。

### Q: 可以克隆多个人的声音吗？
A: 可以。每个声音使用不同的 `custom_voice_id` 即可。

### Q: 克隆后的声音可以跨模型使用吗？
A: 可以。克隆的声音 ID 可用于所有 MiniMax Speech 模型（02 HD/Turbo、2.6 HD/Turbo）。

### Q: 中文效果怎么样？
A: 效果非常好，支持标准普通话，发音清晰自然。

### Q: 可以控制语速和情感吗？
A: 当前 API 不直接支持，可通过标点符号和文本结构调整节奏。

---

## 9. 最佳实践

1. **音频样本质量**: 高质量的 10 秒样本比低质量的 1 分钟样本效果更好
2. **唯一 Voice ID**: 使用有意义的命名（如 `wuna-001`、`zhangsan-voice`）
3. **及时使用**: 创建 voice_id 后立即测试生成一次，避免过期
4. **批量生成**: 先测试单条，效果满意后再批量
5. **备份音频**: 保存好原始音频样本，voice_id 过期后可重新克隆

---

## 10. 完整脚本

项目 `scripts/` 目录下的脚本：

| 脚本 | 功能 |
|------|------|
| `clone_voice.py` | 克隆声音样本 |
| `generate_speech.py` | 使用克隆声音生成语音 |
| `batch_generate.py` | 批量生成口播音频 |

---

*最后更新：2026-02-13*  
*验证状态：✅ 吴娜声音克隆测试通过*
