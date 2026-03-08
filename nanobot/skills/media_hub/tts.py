#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TTS 文字转语音模块 - 使用 Edge TTS（免费）

支持：
- 中文语音（多种音色）
- 英文语音
- 长文本自动分段
- 保存为MP3文件
"""

import asyncio
import edge_tts
from pathlib import Path
from typing import Optional

# 常用中文语音
CHINESE_VOICES = {
    "xiaoxiao": "zh-CN-XiaoxiaoNeural",      # 晓晓 - 女声，温柔
    "xiaoyi": "zh-CN-XiaoyiNeural",          # 晓伊 - 女声，活泼
    "yunjian": "zh-CN-YunjianNeural",        # 云健 - 男声，新闻
    "yunxi": "zh-CN-YunxiNeural",            # 云希 - 男声，年轻
    "xiaochen": "zh-CN-XiaochenNeural",      # 晓辰 - 女声，知性
}

# 常用英文语音
ENGLISH_VOICES = {
    "jenny": "en-US-JennyNeural",            # Jenny - 女声
    "guy": "en-US-GuyNeural",                # Guy - 男声
    "aria": "en-US-AriaNeural",              # Aria - 女声
}


async def text_to_speech_async(
    text: str,
    output_path: str,
    voice: str = "zh-CN-XiaoxiaoNeural",
    rate: str = "+0%",
    volume: str = "+0%"
) -> str:
    """
    异步文字转语音
    
    Args:
        text: 要转换的文字
        output_path: 输出音频文件路径
        voice: 语音ID
        rate: 语速调整 (+10% 表示加快10%, -10% 表示减慢10%)
        volume: 音量调整
    
    Returns:
        输出文件路径
    """
    communicate = edge_tts.Communicate(text, voice, rate=rate, volume=volume)
    await communicate.save(output_path)
    return output_path


def text_to_speech(
    text: str,
    output_path: str = None,
    voice: str = "xiaoxiao",
    rate: str = "+0%",
    volume: str = "+0%"
) -> str:
    """
    文字转语音（同步接口）
    
    Args:
        text: 要转换的文字（支持长文本，自动分段）
        output_path: 输出路径（默认 /tmp/tts_时间戳.mp3）
        voice: 语音名称（xiaoxiao/xiaoyi/yunjian/yunxi/xiaochen）
        rate: 语速 (+0%/+10%/-10%)
        volume: 音量 (+0%)
    
    Returns:
        音频文件路径
    
    示例：
        # 简单使用
        path = text_to_speech("你好，这是测试")
        
        # 指定参数
        path = text_to_speech(
            "口播稿内容...",
            output_path="/tmp/podcast.mp3",
            voice="yunjian",  # 男声，适合新闻
            rate="+10%"       # 加快10%
        )
    """
    # 转换语音名称到ID
    voice_id = CHINESE_VOICES.get(voice, voice)
    
    # 默认输出路径
    if not output_path:
        from datetime import datetime
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = f"/tmp/tts_{timestamp}.mp3"
    
    # 长文本分段处理（Edge TTS有长度限制）
    max_length = 3000  # 每段最大字符数
    
    if len(text) <= max_length:
        # 短文本直接转换
        asyncio.run(text_to_speech_async(text, output_path, voice_id, rate, volume))
    else:
        # 长文本分段转换后合并
        output_path = _process_long_text(text, output_path, voice_id, rate, volume)
    
    print(f"✅ TTS完成: {output_path}")
    return output_path


def _process_long_text(text: str, output_path: str, voice: str, rate: str, volume: str) -> str:
    """处理长文本（分段转换后合并）"""
    import tempfile
    import subprocess
    
    # 按句子分段
    sentences = text.replace('。', '。|').replace('！', '！|').replace('？', '？|').split('|')
    
    segments = []
    current_segment = ""
    
    for sentence in sentences:
        if len(current_segment) + len(sentence) < 3000:
            current_segment += sentence
        else:
            if current_segment:
                segments.append(current_segment)
            current_segment = sentence
    
    if current_segment:
        segments.append(current_segment)
    
    # 分段转换
    temp_files = []
    for i, segment in enumerate(segments):
        temp_file = tempfile.mktemp(suffix='.mp3')
        asyncio.run(text_to_speech_async(segment, temp_file, voice, rate, volume))
        temp_files.append(temp_file)
    
    # 合并音频文件
    concat_file = tempfile.mktemp(suffix='.txt')
    with open(concat_file, 'w') as f:
        for temp_file in temp_files:
            f.write(f"file '{temp_file}'\n")
    
    cmd = [
        'ffmpeg', '-f', 'concat', '-safe', '0',
        '-i', concat_file, '-c', 'copy',
        output_path, '-y', '-loglevel', 'error'
    ]
    
    subprocess.run(cmd, check=True)
    
    # 清理临时文件
    for temp_file in temp_files:
        Path(temp_file).unlink(missing_ok=True)
    Path(concat_file).unlink(missing_ok=True)
    
    return output_path


def list_voices() -> dict:
    """列出所有可用语音"""
    return {
        "中文": CHINESE_VOICES,
        "英文": ENGLISH_VOICES
    }


# 便捷函数
def tts_xiaoxiao(text: str, output_path: str = None) -> str:
    """晓晓女声（温柔）"""
    return text_to_speech(text, output_path, voice="xiaoxiao")


def tts_yunjian(text: str, output_path: str = None) -> str:
    """云健男声（新闻）"""
    return text_to_speech(text, output_path, voice="yunjian")


def tts_xiaoyi(text: str, output_path: str = None) -> str:
    """晓伊女声（活泼）"""
    return text_to_speech(text, output_path, voice="xiaoyi")


if __name__ == "__main__":
    print("🎙️ Edge TTS 文字转语音")
    print("=" * 60)
    
    # 列出可用语音
    voices = list_voices()
    print("\n可用语音:")
    for lang, voice_list in voices.items():
        print(f"\n{lang}:")
        for name, voice_id in voice_list.items():
            print(f"  - {name}: {voice_id}")
    
    # 测试
    print("\n" + "=" * 60)
    print("测试转换...")
    
    test_text = "你好，这是Edge TTS文字转语音测试。支持中文和英文，免费使用。"
    output = text_to_speech(test_text, voice="xiaoxiao")
    
    print(f"\n✅ 测试完成: {output}")
    print("\n使用示例:")
    print('  from skills.media_hub.tts import text_to_speech')
    print('  path = text_to_speech("口播稿内容...", voice="yunjian")')
