---
name: whisper-stt
description: 本地语音转录（STT）技能，基于OpenAI Whisper。完全免费，无需API Key，支持中文。
---

# Whisper STT 技能

本地语音转文字，隐私安全，完全免费。

## 快速开始

### 1. 确保已安装 Whisper

```bash
pip3 install openai-whisper
```

### 2. 使用封装脚本

```python
from tools.whisper_stt import transcribe

# 转录音频
result = transcribe("audio.mp3", model="base", language="zh")

if result.get("success"):
    print(f"转录内容: {result['text']}")
else:
    print(f"错误: {result['error']}")
```

## 模型选择

| 模型 | 大小 | 速度 | 准确率 | 推荐场景 |
|------|------|------|--------|---------|
| tiny | 39MB | 最快 | 一般 | 测试 |
| base | 74MB | 快 | 良好 | **日常使用** ✅ |
| small | 244MB | 中等 | 好 | 平衡 |
| medium | 769MB | 较慢 | 很好 | 高质量 |
| large | 1550MB | 最慢 | 最佳 | 精确转录 |

## 命令行使用

```bash
# 基本用法
whisper audio.mp3

# 指定中文和模型
whisper audio.mp3 --model base --language zh

# 指定输出格式
whisper audio.mp3 --model base --language zh --output_format txt
```

## 与语音克隆结合

```python
from tools.whisper_stt import transcribe
from tools.voice_clone_api import generate_speech

# 语音转文字
stt_result = transcribe("user_voice.mp3")
text = stt_result["text"]

# AI处理...
response = f"收到: {text}"

# 文字转语音（克隆声音）
generate_speech(response, voice_id="wuna-001")
```

## 故障排除

| 问题 | 解决方案 |
|------|---------|
| 安装失败 | 先装PyTorch CPU: `pip3 install torch --index-url https://download.pytorch.org/whl/cpu` |
| 速度慢 | 换用tiny/base模型 |
| 中文不准 | 确认指定 `--language zh` |
| 内存不足 | 使用base/tiny模型 |

---
*基于OpenAI Whisper开源项目*
