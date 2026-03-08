#!/usr/bin/env python3
"""
声音克隆工具 - 使用 WaveSpeed AI MiniMax Voice Clone

用法:
    python voice_clone.py clone <audio_path> <voice_id>
    python voice_clone.py generate <voice_id> <text> <output_path>
    python voice_clone.py batch <voice_id> <texts_file> <output_dir>
"""

import requests
import base64
import os
import sys
import time
import json

# API 配置
WAVESPEED_KEY = os.getenv("WAVESPEED_KEY")
if not WAVESPEED_KEY:
    print("❌ 错误: WAVESPEED_KEY 环境变量未设置")
    sys.exit(1)
BASE_URL = "https://api.wavespeed.ai/api/v3"
HEADERS = {"Authorization": f"Bearer {WAVESPEED_KEY}"}
JSON_HEADERS = {**HEADERS, "Content-Type": "application/json"}


def clone_voice(audio_path, voice_id, text="我是克隆的声音，很高兴为你服务。"):
    """克隆声音"""
    print(f"🎙️  正在克隆声音...")
    print(f"   音频样本: {audio_path}")
    print(f"   Voice ID: {voice_id}")
    
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
        request_id = result['data']['id']
        print(f"✅ 克隆任务已提交: {request_id}")
        return request_id
    else:
        raise Exception(f"❌ 克隆失败: {result}")


def generate_speech(text, voice_id, model="speech-02-hd"):
    """使用克隆的声音生成语音"""
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
        raise Exception(f"❌ 生成失败: {result}")


def poll_result(request_id, timeout=120):
    """轮询任务结果"""
    url = f"{BASE_URL}/predictions/{request_id}/result"
    start_time = time.time()
    
    print("⏳ 等待任务完成...", end="", flush=True)
    
    while time.time() - start_time < timeout:
        response = requests.get(url, headers=HEADERS)
        result = response.json()
        
        status = result.get('data', {}).get('status')
        
        if status == 'completed':
            print(" ✅")
            outputs = result.get('data', {}).get('outputs', [])
            return outputs[0] if outputs else None
        elif status == 'failed':
            print(" ❌")
            raise Exception(f"任务失败: {result}")
        
        print(".", end="", flush=True)
        time.sleep(3)
    
    print(" ⏰")
    raise TimeoutError("任务超时")


def download_audio(audio_url, output_path):
    """下载音频"""
    response = requests.get(audio_url, stream=True)
    with open(output_path, 'wb') as f:
        for chunk in response.iter_content(chunk_size=8192):
            f.write(chunk)
    return output_path


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    
    command = sys.argv[1]
    
    if command == "clone":
        if len(sys.argv) < 4:
            print("用法: python voice_clone.py clone <audio_path> <voice_id>")
            sys.exit(1)
        
        audio_path = sys.argv[2]
        voice_id = sys.argv[3]
        
        request_id = clone_voice(audio_path, voice_id)
        
        # 等待完成
        print("\n等待克隆完成...")
        time.sleep(5)
        
        try:
            result = poll_result(request_id, timeout=60)
            print(f"✅ 声音克隆成功！Voice ID: {voice_id}")
            print(f"   现在可以使用这个 Voice ID 生成语音了")
        except Exception as e:
            print(f"⚠️  克隆任务进行中，voice_id 已创建: {voice_id}")
            print(f"   7天内至少使用一次即可永久保存")
    
    elif command == "generate":
        if len(sys.argv) < 5:
            print("用法: python voice_clone.py generate <voice_id> <text> <output_path>")
            sys.exit(1)
        
        voice_id = sys.argv[2]
        text = sys.argv[3]
        output_path = sys.argv[4]
        
        print(f"🎵 正在生成语音...")
        print(f"   Voice ID: {voice_id}")
        print(f"   文本: {text[:50]}...")
        
        request_id, _ = generate_speech(text, voice_id)
        audio_url = poll_result(request_id)
        
        download_audio(audio_url, output_path)
        print(f"✅ 音频已保存: {output_path}")
    
    elif command == "batch":
        if len(sys.argv) < 5:
            print("用法: python voice_clone.py batch <voice_id> <texts_file> <output_dir>")
            sys.exit(1)
        
        voice_id = sys.argv[2]
        texts_file = sys.argv[3]
        output_dir = sys.argv[4]
        
        # 读取文本列表
        with open(texts_file, 'r', encoding='utf-8') as f:
            texts = [line.strip() for line in f if line.strip()]
        
        os.makedirs(output_dir, exist_ok=True)
        
        print(f"🎵 批量生成 {len(texts)} 条语音...")
        
        for i, text in enumerate(texts):
            print(f"\n[{i+1}/{len(texts)}] {text[:50]}...")
            
            request_id, _ = generate_speech(text, voice_id)
            audio_url = poll_result(request_id)
            
            output_path = os.path.join(output_dir, f"audio_{i+1:03d}.mp3")
            download_audio(audio_url, output_path)
            print(f"   ✅ 已保存: {output_path}")
        
        print(f"\n🎉 全部完成！共生成 {len(texts)} 个音频文件")
    
    else:
        print(f"未知命令: {command}")
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
